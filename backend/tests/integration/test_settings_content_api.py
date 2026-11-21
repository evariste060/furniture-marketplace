"""Module 19 (settings & content, approved 2026-10-29): the public store contact and announcement
bar, policy pages in English and Kinyarwanda, and business quote requests from the Contact page.
Covers public versus private keys, a missing translation answering 404 rather than another
language, the permission matrix, validation, rate limits and the audit trail."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.kigali_time import KIGALI
from app.models import AuditRecord, QuoteRequest
from app.models.content import PAGE_SLUGS
from app.schemas.pages import PageSlug

PUBLIC_SETTINGS = "/api/v1/settings"
STAFF_SETTINGS = "/api/v1/staff/settings"
PAGES = "/api/v1/pages"
STAFF_PAGES = "/api/v1/staff/pages"
QUOTES = "/api/v1/quote-requests"
STAFF_QUOTES = "/api/v1/staff/quote-requests"

CONTACT = {
    "store.name": "3 Sixty Technologies",
    "contact.phone": "+250 788 123 456",
    "contact.whatsapp": "+250788123456",
    "contact.email": "Info@Example.RW",
    "contact.address": "KN 5 Ave, Kigali, Rwanda",
    "contact.hours": "Mon – Sat: 8:00 AM – 6:00 PM",
}
PRIVATE = {
    "delivery.free_delivery_threshold": 50_000,
    "seller.legal_name": "Private Legal Name Ltd",
    "seller.tin": "PRIVATE-TIN-123",
    "seller.address": "Private seller address",
}
PAGE = {
    "title": "Delivery information",
    "body": "We deliver.\n\n## Fees\n\n- Kigali",
    "is_published": True,
}
QUOTE = {
    "company": "Green Hills Academy",
    "contact_name": "Aline Uwase",
    "phone": "0788 123 456",
    "email": " Procurement@Example.RW ",
    "lines": [{"product": "HP Pavilion 15 Laptop", "quantity": 25}],
    "delivery_location": "Gasabo",
    "message": "Invoices with our TIN.\n\nThanks",
    "locale": "rw",
}


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


# ---- public settings ------------------------------------------------------------------------
def test_public_settings_serve_only_the_public_keys(client, admin_auth):
    empty = client.get(PUBLIC_SETTINGS)
    assert empty.status_code == 200
    assert empty.headers["cache-control"] == "public, max-age=60"
    assert empty.json() == {
        "store_name": None,
        "phone": None,
        "whatsapp": None,
        "email": None,
        "address": None,
        "hours": None,
        "announcement": None,
        "social": {
            "facebook": None,
            "instagram": None,
            "x": None,
            "youtube": None,
            "tiktok": None,
            "linkedin": None,
        },
    }
    res = client.patch(STAFF_SETTINGS, json={**CONTACT, **PRIVATE}, headers=admin_auth["headers"])
    assert res.status_code == 200, res.text
    body = client.get(PUBLIC_SETTINGS).json()
    assert body == {
        "store_name": "3 Sixty Technologies",
        "phone": "+250 788 123 456",
        "whatsapp": "+250788123456",
        "email": "info@example.rw",  # stored in lower case
        "address": "KN 5 Ave, Kigali, Rwanda",
        "hours": "Mon – Sat: 8:00 AM – 6:00 PM",
        "announcement": None,
        "social": {
            "facebook": None,
            "instagram": None,
            "x": None,
            "youtube": None,
            "tiktok": None,
            "linkedin": None,
        },
    }
    text = str(body)
    for value in PRIVATE.values():
        assert str(value) not in text


def test_the_announcement_is_public_only_while_switched_on_with_both_messages(
    client, db, admin_auth
):
    h = admin_auth["headers"]
    refused = client.patch(STAFF_SETTINGS, json={"announcement.enabled": True}, headers=h)
    assert refused.status_code == 422
    assert refused.json()["error"]["details"][0]["loc"] == ["body", "announcement.enabled"]
    half = {"announcement.enabled": True, "announcement.text_en": "Free delivery this week"}
    assert client.patch(STAFF_SETTINGS, json=half, headers=h).status_code == 422
    assert audits(db, "settings.update") == []

    texts = {"announcement.text_en": "Free delivery this week", "announcement.text_rw": "Ubuntu"}
    assert client.patch(STAFF_SETTINGS, json=texts, headers=h).status_code == 200
    assert client.get(PUBLIC_SETTINGS).json()["announcement"] is None  # still off
    on = client.patch(STAFF_SETTINGS, json={"announcement.enabled": True}, headers=h)
    assert on.status_code == 200, on.text
    assert client.get(PUBLIC_SETTINGS).json()["announcement"] == {
        "en": "Free delivery this week",
        "rw": "Ubuntu",
    }
    assert client.patch(STAFF_SETTINGS, json={"announcement.enabled": False}, headers=h).is_success
    assert client.get(PUBLIC_SETTINGS).json()["announcement"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"contact.phone": "0788123456"},  # international form only
        {"contact.whatsapp": "+250 788-123-456"},
        {"contact.whatsapp": "+0788123456"},
        {"contact.phone": "+250  788123456"},
        {"contact.email": "not-an-email"},
        {"contact.email": " info@example.rw"},
        {"store.name": " 3 Sixty"},
        {"store.name": "x" * 81},
        {"contact.address": "KN 5 Ave\nKigali"},  # one line
        {"contact.hours": None},
        {"announcement.enabled": "true"},
        {"announcement.text_rw": "x" * 121},
    ],
)
def test_contact_settings_are_validated(client, admin_auth, body):
    res = client.patch(STAFF_SETTINGS, json=body, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text


def test_only_administrators_change_the_contact(client, admin_auth, customer_auth):
    for auth in (customer_auth,):  # SC-05: the administrator is the only staff role
        res = client.patch(STAFF_SETTINGS, json=CONTACT, headers=auth["headers"])
        assert res.status_code == 403, res.text
    assert client.patch(STAFF_SETTINGS, json=CONTACT).status_code == 401
    assert client.get(PUBLIC_SETTINGS).json()["phone"] is None


# ---- social media links (owner, 2026-11-18) ----------------------------------------------------
SOCIAL = {
    "social.facebook": "https://www.facebook.com/3sixtytech",
    "social.instagram": "https://instagram.com/3sixtytech",
    "social.x": "https://x.com/3sixtytech",
    "social.youtube": "https://www.youtube.com/@3sixtytech",
    "social.tiktok": "https://www.tiktok.com/@3sixtytech",
    "social.linkedin": "https://www.linkedin.com/company/3sixtytech",
}


def test_social_links_are_public_and_can_be_removed(client, db, admin_auth):
    h = admin_auth["headers"]
    res = client.patch(STAFF_SETTINGS, json=SOCIAL, headers=h)
    assert res.status_code == 200, res.text
    assert client.get(PUBLIC_SETTINGS).json()["social"] == {
        key.removeprefix("social."): url for key, url in SOCIAL.items()
    }
    # An empty link takes it off the store again; the change is audited.
    removed = client.patch(STAFF_SETTINGS, json={"social.x": ""}, headers=h)
    assert removed.status_code == 200, removed.text
    assert client.get(PUBLIC_SETTINGS).json()["social"]["x"] is None
    record = audits(db, "settings.update")[-1]
    assert record.change_summary["changes"]["social.x"] == {"from": SOCIAL["social.x"], "to": ""}


@pytest.mark.parametrize(
    "body",
    [
        {"social.facebook": "http://facebook.com/3sixtytech"},  # https only
        {"social.facebook": "facebook.com/3sixtytech"},
        {"social.facebook": "https://facebook.com.evil.example/3sixtytech"},
        {"social.facebook": "https://notfacebook.com/3sixtytech"},
        {"social.instagram": "https://facebook.com/3sixtytech"},  # another network's site
        {"social.youtube": "javascript:alert(1)"},
        {"social.x": "https://user:pass@x.com/3sixtytech"},
        {"social.x": "https://x.com:8443/3sixtytech"},
        {"social.tiktok": "https://www.tiktok.com/@3sixty tech"},
        {"social.linkedin": "https://linkedin.com/" + "a" * 300},
        {"social.linkedin": None},
        {"social.myspace": "https://myspace.com/3sixtytech"},
    ],
)
def test_social_links_are_validated(client, admin_auth, body):
    res = client.patch(STAFF_SETTINGS, json=body, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text


def test_only_administrators_change_the_social_links(client, customer_auth):
    res = client.patch(STAFF_SETTINGS, json=SOCIAL, headers=customer_auth["headers"])
    assert res.status_code == 403, res.text
    assert client.patch(STAFF_SETTINGS, json=SOCIAL).status_code == 401
    assert client.get(PUBLIC_SETTINGS).json()["social"]["facebook"] is None


# ---- pages ----------------------------------------------------------------------------------
def test_the_slug_list_matches_the_schema():
    assert get_args(PageSlug) == PAGE_SLUGS


def test_a_missing_translation_is_404_not_another_language(client, admin_auth):
    h = admin_auth["headers"]
    res = client.put(f"{STAFF_PAGES}/delivery-information?lang=en", json=PAGE, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["rw"] is None
    en = client.get(f"{PAGES}/delivery-information?lang=en")
    assert en.status_code == 200
    assert en.headers["cache-control"] == "public, max-age=60"
    assert {k: en.json()[k] for k in ("slug", "locale", "title", "body")} == {
        "slug": "delivery-information",
        "locale": "en",
        "title": "Delivery information",
        "body": PAGE["body"],
    }
    assert client.get(f"{PAGES}/delivery-information").json()["locale"] == "en"  # default
    rw = client.get(f"{PAGES}/delivery-information?lang=rw")
    assert rw.status_code == 404
    assert rw.json()["error"]["code"] == "page_not_found"
    assert client.get(f"{PAGES}/delivery-information?lang=fr").status_code == 422
    assert client.get(f"{PAGES}/no-such-page?lang=en").status_code == 404


def test_unpublished_pages_are_staff_only(client, db, admin_auth):
    h = admin_auth["headers"]  # management also manages content
    draft = {**PAGE, "title": "Ubwishingizi", "is_published": False}
    res = client.put(f"{STAFF_PAGES}/warranty?lang=rw", json=draft, headers=h)
    assert res.status_code == 200, res.text
    assert client.get(f"{PAGES}/warranty?lang=rw").status_code == 404
    listing = client.get(STAFF_PAGES, headers=admin_auth["headers"]).json()["items"]
    assert [p["slug"] for p in listing] == list(PAGE_SLUGS)
    (warranty,) = [p for p in listing if p["slug"] == "warranty"]
    assert warranty["en"] is None
    assert warranty["rw"]["title"] == "Ubwishingizi"
    assert warranty["rw"]["is_published"] is False
    assert warranty["rw"]["updated_by_user_id"] == str(admin_auth["user"].id)

    published = {**draft, "is_published": True}
    assert client.put(f"{STAFF_PAGES}/warranty?lang=rw", json=published, headers=h).is_success
    assert client.get(f"{PAGES}/warranty?lang=rw").json()["title"] == "Ubwishingizi"
    unpublish = {**draft, "is_published": False}
    assert client.put(f"{STAFF_PAGES}/warranty?lang=rw", json=unpublish, headers=h).is_success
    assert client.get(f"{PAGES}/warranty?lang=rw").status_code == 404


def test_page_writes_are_audited_once_per_change(client, db, admin_auth):
    h = admin_auth["headers"]
    url = f"{STAFF_PAGES}/about-us?lang=en"
    assert client.put(url, json=PAGE, headers=h).is_success
    assert client.put(url, json=PAGE, headers=h).is_success  # unchanged: not audited
    assert client.put(url, json={**PAGE, "title": "About us"}, headers=h).is_success
    records = audits(db, "content.page_update")
    assert [r.entity_id for r in records] == ["about-us:en", "about-us:en"]
    assert records[0].change_summary["from"] is None
    assert records[1].change_summary["from"]["title"] == "Delivery information"
    assert records[1].change_summary["to"] == {
        "title": "About us",
        "is_published": True,
        "body_length": len(PAGE["body"]),
    }
    assert "We deliver" not in str(records[1].change_summary)  # the body is not copied


def test_page_text_is_cleaned_and_limited(client, admin_auth):
    h = admin_auth["headers"]
    url = f"{STAFF_PAGES}/privacy-policy?lang=en"
    body = "  # Privacy\r\n\r\nWe keep\x00 your data | safe |\n\t- item  "
    res = client.put(url, json={**PAGE, "title": " Privacy\x07 ", "body": body}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["en"]["title"] == "Privacy"
    assert res.json()["en"]["body"] == "# Privacy\n\nWe keep your data | safe |\n\t- item"
    for bad in (
        {**PAGE, "title": "  "},
        {**PAGE, "title": "x" * 121},
        {**PAGE, "body": " \n "},
        {**PAGE, "body": "x" * 50_001},
        {**PAGE, "is_published": "yes"},
        {**PAGE, "slug": "warranty"},
        {"title": "Only a title"},
    ):
        assert client.put(url, json=bad, headers=h).status_code == 422, bad
    assert client.put(f"{STAFF_PAGES}/careers?lang=en", json=PAGE, headers=h).status_code == 422
    assert client.put(f"{STAFF_PAGES}/warranty", json=PAGE, headers=h).status_code == 422  # lang


def test_page_permissions(client, admin_auth, customer_auth):
    url = f"{STAFF_PAGES}/warranty?lang=en"
    assert client.get(STAFF_PAGES, headers=admin_auth["headers"]).status_code == 200
    for auth in (customer_auth,):  # SC-05: the administrator is the only staff role
        assert client.put(url, json=PAGE, headers=auth["headers"]).status_code == 403
        assert client.get(STAFF_PAGES, headers=auth["headers"]).status_code == 403
    assert client.put(url, json=PAGE).status_code == 401
    assert client.get(STAFF_PAGES).status_code == 401


# ---- quote requests -------------------------------------------------------------------------
def test_a_quote_request_is_stored_cleaned(client, db):
    res = client.post(QUOTES, json=QUOTE)
    assert res.status_code == 201, res.text
    reference = res.json()["reference"]
    today = datetime.now(UTC).astimezone(KIGALI)
    assert re.fullmatch(rf"Q-{today:%y%m%d}-[2-9A-HJ-NP-Z]{{6}}", reference)
    db.expire_all()
    quote = db.scalar(select(QuoteRequest).where(QuoteRequest.reference == reference))
    assert quote is not None
    assert (quote.phone, quote.email, quote.status, quote.locale) == (
        "+250788123456",
        "procurement@example.rw",
        "new",
        "rw",
    )
    assert quote.lines == [{"product": "HP Pavilion 15 Laptop", "quantity": 25}]
    assert quote.message == "Invoices with our TIN.\n\nThanks"
    assert (quote.handled_at, quote.handled_by_user_id, quote.needed_by) == (None, None, None)

    minimal = {k: QUOTE[k] for k in ("company", "contact_name", "phone", "lines")}
    res = client.post(QUOTES, json={**minimal, "phone": "0788999000", "email": " "})
    assert res.status_code == 201, res.text


@pytest.mark.parametrize(
    "change",
    [
        {"company": " "},
        {"contact_name": "A"},
        {"phone": "+250 722"},
        {"phone": "+15551234567"},
        {"email": "not-an-email"},
        {"lines": []},
        {"lines": [{"product": "Laptop", "quantity": 1}] * 21},
        {"lines": [{"product": "Laptop", "quantity": 0}]},
        {"lines": [{"product": "Laptop", "quantity": 100_001}]},
        {"lines": [{"product": "Laptop", "quantity": "5"}]},
        {"lines": [{"product": " ", "quantity": 5}]},
        {"lines": [{"product": "Laptop", "quantity": 5, "price": 1}]},
        {"message": "x" * 2001},
        {"locale": "fr"},
        {"status": "closed"},
        {"needed_by": "2020-01-01"},
        {"needed_by": (datetime.now(UTC) + timedelta(days=400)).date().isoformat()},
    ],
)
def test_quote_requests_are_validated(client, db, change):
    res = client.post(QUOTES, json={**QUOTE, **change})
    assert res.status_code == 422, res.text
    assert db.scalar(select(QuoteRequest.id)) is None


def test_quote_requests_are_rate_limited_per_phone(client, db):
    for _ in range(3):
        assert client.post(QUOTES, json=QUOTE).status_code == 201
    limited = client.post(QUOTES, json=QUOTE)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    # Another number from the same network still gets through (the network limit is higher).
    assert client.post(QUOTES, json={**QUOTE, "phone": "0788555111"}).status_code == 201


def test_staff_follow_up_quote_requests(client, db, admin_auth):
    h = admin_auth["headers"]
    first = client.post(QUOTES, json=QUOTE).json()["reference"]
    second = client.post(QUOTES, json={**QUOTE, "phone": "0788555111"}).json()["reference"]
    page = client.get(STAFF_QUOTES, headers=h).json()
    assert page["total"] == 2
    assert [q["reference"] for q in page["items"]] == [second, first]  # newest first
    quote_id = page["items"][1]["id"]

    res = client.patch(f"{STAFF_QUOTES}/{quote_id}", json={"status": "contacted"}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["handled_by_user_id"] == str(admin_auth["user"].id)
    assert res.json()["handled_at"] is not None
    assert client.patch(
        f"{STAFF_QUOTES}/{quote_id}", json={"status": "contacted"}, headers=h
    ).is_success
    filtered = client.get(f"{STAFF_QUOTES}?status=new", headers=h).json()
    assert [q["reference"] for q in filtered["items"]] == [second]

    back = client.patch(f"{STAFF_QUOTES}/{quote_id}", json={"status": "new"}, headers=h)
    assert (back.json()["handled_at"], back.json()["handled_by_user_id"]) == (None, None)
    records = audits(db, "quote.status_change")
    assert [(r.change_summary["from"], r.change_summary["to"]) for r in records] == [
        ("new", "contacted"),
        ("contacted", "new"),
    ]
    missing = client.patch(f"{STAFF_QUOTES}/{uuid.uuid4()}", json={"status": "closed"}, headers=h)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "quote_request_not_found"
    bad = client.patch(f"{STAFF_QUOTES}/{quote_id}", json={"status": "won"}, headers=h)
    assert bad.status_code == 422


def test_quote_permissions(client, admin_auth, customer_auth):
    assert client.get(STAFF_QUOTES, headers=admin_auth["headers"]).status_code == 200
    for auth in (customer_auth,):  # SC-05: the administrator is the only staff role
        assert client.get(STAFF_QUOTES, headers=auth["headers"]).status_code == 403
        res = client.patch(
            f"{STAFF_QUOTES}/{uuid.uuid4()}", json={"status": "closed"}, headers=auth["headers"]
        )
        assert res.status_code == 403
    assert client.get(STAFF_QUOTES).status_code == 401
