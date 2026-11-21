"""Technical services (ADR-013, SC-02): public pages, requests (validation, honeypot, rate limit,
acknowledgement email) and staff management (permissions, reorder, items, images, delete rule,
lead follow-up, audit).

Disposable per-test PostgreSQL schema (tests/conftest.py).
"""

import io
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.kigali_time import KIGALI
from app.integrations.media import LocalMediaStorage, get_media_storage
from app.main import app
from app.models import AuditRecord, ServiceCategory, ServiceItem, ServiceRequest
from tests.conftest import make_staff
from tests.integration.test_transactional_emails import emails, rows  # noqa: F401

PUBLIC = "/api/v1/services"
STAFF = "/api/v1/staff/services"
LEADS = "/api/v1/staff/service-requests"
SERVICE = {
    "name_en": "CCTV Installation",
    "name_rw": "Gushyiraho kamera",
    "short_description_en": "Cameras for homes and businesses.",
    "intro_en": "We design and install CCTV systems.\n\nRemote viewing included.",
    "icon": "cctv",
}
REQUEST = {
    "full_name": " Aline Uwase ",
    "phone": "0788 123 456",
    "email": " Aline@Example.RW ",
    "location": "Kicukiro",
    "client_type": "business",
    "message": "Eight cameras.\n\nThanks",
    "locale": "rw",
}


def png(size=(300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 240)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def storage(tmp_path):
    media = LocalMediaStorage(tmp_path / "media", get_settings().image_public_base_url)
    app.dependency_overrides[get_media_storage] = lambda: media
    yield media
    app.dependency_overrides.pop(get_media_storage, None)


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def create(client, auth, **change) -> dict:
    res = client.post(STAFF, json={**SERVICE, **change}, headers=auth["headers"])
    assert res.status_code == 201, res.text
    return res.json()


def add_item(client, auth, service_id, title_en, title_rw=None) -> dict:
    res = client.post(
        f"{STAFF}/{service_id}/items",
        json={"title_en": title_en, "title_rw": title_rw},
        headers=auth["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


# ---- public ------------------------------------------------------------------------------------
def test_the_public_list_shows_active_services_in_order_and_language(client, admin_auth):
    cctv = create(client, admin_auth)
    add_item(client, admin_auth, cctv["id"], "DVR installation", "Gushyiraho DVR")
    add_item(client, admin_auth, cctv["id"], "Remote viewing")
    gate = create(client, admin_auth, name_en="Gate Automation", name_rw=None, icon="gate")
    create(client, admin_auth, name_en="Hidden service", is_active=False)
    assert cctv["slug"] == "cctv-installation" and cctv["sort_order"] < gate["sort_order"]

    english = client.get(PUBLIC).json()
    assert [s["slug"] for s in english] == ["cctv-installation", "gate-automation"]
    assert [i["title"] for i in english[0]["items"]] == ["DVR installation", "Remote viewing"]
    assert english[0]["image"] is None and "intro" not in english[0]

    kinyarwanda = client.get(PUBLIC, params={"locale": "rw"}).json()
    assert [s["name"] for s in kinyarwanda] == ["Gushyiraho kamera", "Gate Automation"]
    assert [i["title"] for i in kinyarwanda[0]["items"]] == ["Gushyiraho DVR", "Remote viewing"]

    detail = client.get(f"{PUBLIC}/cctv-installation").json()
    assert detail["intro"] == SERVICE["intro_en"] and len(detail["items"]) == 2
    hidden = client.get(f"{PUBLIC}/hidden-service")
    assert hidden.status_code == 404 and hidden.json()["error"]["code"] == "service_not_found"


# ---- requests ----------------------------------------------------------------------------------
def test_a_request_is_stored_cleaned(client, db, admin_auth):
    create(client, admin_auth)
    res = client.post(f"{PUBLIC}/cctv-installation/requests", json=REQUEST)
    assert res.status_code == 201, res.text
    reference = res.json()["reference"]
    today = datetime.now(UTC).astimezone(KIGALI)
    assert re.fullmatch(rf"SR-{today:%y%m%d}-[2-9A-HJ-NP-Z]{{6}}", reference)
    db.expire_all()
    row = db.scalar(select(ServiceRequest).where(ServiceRequest.reference == reference))
    assert row is not None
    assert (row.full_name, row.phone, row.email, row.locale, row.status) == (
        "Aline Uwase",
        "+250788123456",
        "aline@example.rw",
        "rw",
        "new",
    )
    assert row.message == "Eight cameras.\n\nThanks" and row.status_changed_at is None

    minimal = {"full_name": "Jean", "phone": "0722000111", "client_type": "home", "email": " "}
    assert client.post(f"{PUBLIC}/cctv-installation/requests", json=minimal).status_code == 201


@pytest.mark.parametrize(
    "change",
    [
        {"full_name": " "},
        {"phone": "0788 12"},
        {"phone": "+15551234567"},
        {"phone": "0252123456"},  # a landline: mobiles only
        {"email": "not-an-email"},
        {"client_type": "government"},
        {"location": "x" * 121},
        {"message": "x" * 2001},
        {"locale": "fr"},
        {"status": "completed"},
        {"preferred_date": "2020-01-01"},
        {"preferred_date": (datetime.now(UTC) + timedelta(days=400)).date().isoformat()},
    ],
)
def test_requests_are_validated(client, db, admin_auth, change):
    create(client, admin_auth)
    res = client.post(f"{PUBLIC}/cctv-installation/requests", json={**REQUEST, **change})
    assert res.status_code == 422, res.text
    assert db.scalar(select(ServiceRequest.id)) is None


def test_a_hidden_or_missing_service_takes_no_requests(client, db, admin_auth):
    create(client, admin_auth, is_active=False)
    for slug in ("cctv-installation", "nothing-here"):
        res = client.post(f"{PUBLIC}/{slug}/requests", json=REQUEST)
        assert res.status_code == 404
    assert db.scalar(select(ServiceRequest.id)) is None


def test_the_honeypot_looks_successful_but_stores_and_counts_nothing(client, db, admin_auth):
    create(client, admin_auth)
    for _ in range(5):  # more than the phone limit: bot attempts are not counted
        res = client.post(
            f"{PUBLIC}/cctv-installation/requests", json={**REQUEST, "website": "spam.example"}
        )
        assert res.status_code == 201 and res.json()["reference"].startswith("SR-")
    assert db.scalar(select(ServiceRequest.id)) is None
    assert client.post(f"{PUBLIC}/cctv-installation/requests", json=REQUEST).status_code == 201


def test_requests_are_rate_limited_per_phone(client, admin_auth):
    create(client, admin_auth)
    url = f"{PUBLIC}/cctv-installation/requests"
    for _ in range(3):
        assert client.post(url, json=REQUEST).status_code == 201
    limited = client.post(url, json=REQUEST)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    assert client.post(url, json={**REQUEST, "phone": "0788555111"}).status_code == 201


def test_a_request_with_an_email_is_acknowledged(client, db, admin_auth, emails):  # noqa: F811
    create(client, admin_auth)
    reference = client.post(f"{PUBLIC}/cctv-installation/requests", json=REQUEST).json()[
        "reference"
    ]
    [row] = rows(db, "service_received")
    assert (row.subject_type, row.recipient, row.status) == ("service", "aline@example.rw", "sent")
    [mail] = emails.messages
    assert reference in mail.subject and "CCTV Installation" in mail.text
    assert "/rw/services/cctv-installation" in mail.html

    no_email = {**REQUEST, "email": None, "phone": "0788555111"}
    assert client.post(f"{PUBLIC}/cctv-installation/requests", json=no_email).status_code == 201
    assert len(rows(db, "service_received")) == 1


# ---- staff: services ---------------------------------------------------------------------------
def test_service_permissions(client, admin_auth, customer_auth):
    # SC-05: the Marketplace Administrator holds every permission; customers hold none.
    assert client.get(STAFF, headers=admin_auth["headers"]).status_code == 200
    assert client.get(LEADS, headers=admin_auth["headers"]).status_code == 200
    assert client.get(STAFF, headers=customer_auth["headers"]).status_code == 403
    assert client.get(LEADS, headers=customer_auth["headers"]).status_code == 403
    assert client.post(STAFF, json=SERVICE, headers=customer_auth["headers"]).status_code == 403
    res = client.patch(
        f"{LEADS}/{uuid.uuid4()}", json={"status": "contacted"}, headers=customer_auth["headers"]
    )
    assert res.status_code == 403
    assert client.get(STAFF).status_code == 401
    assert client.post(STAFF, json=SERVICE, headers=admin_auth["headers"]).status_code == 201


@pytest.mark.parametrize(
    "change",
    [
        {"name_en": " "},
        {"icon": "rocket"},
        {"slug": "Not A Slug"},
        {"intro_en": "x" * 3001},
        {"price": 1000},
    ],
)
def test_service_fields_are_validated(client, admin_auth, change):
    res = client.post(STAFF, json={**SERVICE, **change}, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text


def test_editing_a_service_is_audited_once_per_change(client, db, admin_auth):
    h = admin_auth["headers"]
    service = create(client, admin_auth)
    taken = create(client, admin_auth, name_en="Repair")
    assert client.post(STAFF, json={**SERVICE, "slug": "repair"}, headers=h).status_code == 409
    clash = client.patch(f"{STAFF}/{service['id']}", json={"slug": taken["slug"]}, headers=h)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "slug_taken"
    assert (
        client.patch(f"{STAFF}/{service['id']}", json={"name_en": None}, headers=h).status_code
        == 422
    )

    res = client.patch(
        f"{STAFF}/{service['id']}", json={"is_active": False, "name_rw": " "}, headers=h
    )
    assert res.status_code == 200, res.text
    assert (res.json()["is_active"], res.json()["name_rw"]) == (False, None)
    assert client.patch(f"{STAFF}/{service['id']}", json={"is_active": False}, headers=h).is_success
    [record] = audits(db, "services.service_update")
    assert {"is_active", "name_rw"} <= set(record.change_summary)
    assert "name_en" not in record.change_summary
    assert len(audits(db, "services.service_create")) == 2


def test_services_and_items_are_reordered(client, db, admin_auth):
    h = admin_auth["headers"]
    a = create(client, admin_auth, name_en="Alpha")
    b = create(client, admin_auth, name_en="Beta")
    bad = client.put(f"{STAFF}/order", json={"service_ids": [a["id"]]}, headers=h)
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "service_order_mismatch"
    assert (
        client.put(
            f"{STAFF}/order", json={"service_ids": [b["id"], a["id"]]}, headers=h
        ).status_code
        == 204
    )
    assert [s["slug"] for s in client.get(PUBLIC).json()] == ["beta", "alpha"]
    assert len(audits(db, "services.service_reorder")) == 1

    one = add_item(client, admin_auth, a["id"], "One")
    two = add_item(client, admin_auth, a["id"], "Two")
    url = f"{STAFF}/{a['id']}/items"
    assert (
        client.put(f"{url}/order", json={"item_ids": [two["id"], one["id"]]}, headers=h).status_code
        == 204
    )
    assert [i["title"] for i in client.get(f"{PUBLIC}/alpha").json()["items"]] == ["Two", "One"]
    mismatch = client.put(f"{url}/order", json={"item_ids": [one["id"]]}, headers=h)
    assert mismatch.status_code == 409

    edited = client.patch(f"{url}/{one['id']}", json={"title_rw": "Rimwe"}, headers=h)
    assert edited.status_code == 200 and edited.json()["title_rw"] == "Rimwe"
    assert client.delete(f"{url}/{two['id']}", headers=h).status_code == 204
    other = client.delete(f"{STAFF}/{b['id']}/items/{one['id']}", headers=h)
    assert other.status_code == 404 and other.json()["error"]["code"] == "service_item_not_found"
    actions = (
        "services.item_create",
        "services.item_reorder",
        "services.item_update",
        "services.item_delete",
    )
    assert [len(audits(db, a)) for a in actions] == [2, 1, 1, 1]


def test_a_service_has_at_most_thirty_items(client, db, admin_auth):
    service = create(client, admin_auth)
    db.add_all(
        ServiceItem(
            service_category_id=uuid.UUID(service["id"]), title_en=f"Item {n}", sort_order=n
        )
        for n in range(30)
    )
    db.commit()
    res = client.post(
        f"{STAFF}/{service['id']}/items",
        json={"title_en": "One more"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 422


def test_a_service_with_requests_cannot_be_deleted(client, db, admin_auth):
    h = admin_auth["headers"]
    service = create(client, admin_auth)
    empty = create(client, admin_auth, name_en="Training")
    add_item(client, admin_auth, empty["id"], "Basics")
    client.post(f"{PUBLIC}/cctv-installation/requests", json=REQUEST)
    listed = {s["slug"]: s["request_count"] for s in client.get(STAFF, headers=h).json()}
    assert listed == {"cctv-installation": 1, "training": 0}

    refused = client.delete(f"{STAFF}/{service['id']}", headers=h)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "service_has_requests"
    assert client.delete(f"{STAFF}/{empty['id']}", headers=h).status_code == 204
    db.expire_all()
    assert db.scalar(select(ServiceItem.id)) is None
    assert db.get(ServiceCategory, uuid.UUID(service["id"])) is not None
    assert len(audits(db, "services.service_delete")) == 1


def test_a_service_image_is_uploaded_replaced_and_removed(client, db, admin_auth, storage):
    h = admin_auth["headers"]
    service = create(client, admin_auth)
    url = f"{STAFF}/{service['id']}/image"
    first = client.post(url, files={"file": ("a.png", png(), "image/png")}, headers=h)
    assert first.status_code == 200, first.text
    image = first.json()["image"]
    assert "/services/" in image["url"] and image["width"] == 300
    assert client.get(PUBLIC).json()[0]["image"]["url"] == image["url"]

    second = client.post(url, files={"file": ("b.png", png((400, 300)), "image/png")}, headers=h)
    assert second.json()["image"]["url"] != image["url"]
    assert (
        client.post(
            url, files={"file": ("x.png", b"not an image", "image/png")}, headers=h
        ).status_code
        == 422
    )

    removed = client.delete(url, headers=h)
    assert removed.status_code == 200 and removed.json()["image"] is None
    assert client.delete(url, headers=h).is_success  # nothing to remove: nothing changes
    assert [
        len(audits(db, a))
        for a in ("services.service_image_upload", "services.service_image_delete")
    ] == [2, 1]
    missing = client.post(
        f"{STAFF}/{uuid.uuid4()}/image", files={"file": ("a.png", png(), "image/png")}, headers=h
    )
    assert missing.status_code == 404


# ---- staff: requests ---------------------------------------------------------------------------
def test_staff_follow_up_requests(client, db, admin_auth, customer_auth):
    h = admin_auth["headers"]
    cctv = create(client, admin_auth)
    create(client, admin_auth, name_en="Repair", icon="wrench")
    first = client.post(f"{PUBLIC}/cctv-installation/requests", json=REQUEST).json()["reference"]
    second = client.post(
        f"{PUBLIC}/repair/requests", json={**REQUEST, "phone": "0788555111"}
    ).json()["reference"]

    page = client.get(LEADS, headers=h).json()
    assert page["total"] == 2 and [r["reference"] for r in page["items"]] == [second, first]
    by_service = client.get(LEADS, params={"service_id": cctv["id"]}, headers=h).json()
    assert [r["reference"] for r in by_service["items"]] == [first]
    today = datetime.now(UTC).astimezone(KIGALI).date()
    dated = client.get(
        LEADS, params={"from": today.isoformat(), "to": today.isoformat()}, headers=h
    )
    assert dated.json()["total"] == 2
    future = client.get(LEADS, params={"from": (today + timedelta(days=1)).isoformat()}, headers=h)
    assert future.json()["total"] == 0
    lead = page["items"][1]
    assert lead["service"]["slug"] == "cctv-installation" and lead["assigned_to"] is None

    names = {a["name"] for a in client.get(f"{LEADS}/assignees", headers=h).json()}
    assert names == {"Test administrator"}  # SC-05: the only staff role

    url = f"{LEADS}/{lead['id']}"
    res = client.patch(
        url,
        json={
            "status": "contacted",
            "assigned_to_user_id": str(admin_auth["user"].id),
            "internal_notes": "Called, visit on Friday.",
        },
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["status"], body["assigned_to"]["name"], body["internal_notes"]) == (
        "contacted",
        "Test administrator",
        "Called, visit on Friday.",
    )
    assert body["status_changed_at"] is not None
    assert client.get(LEADS, params={"status": "new"}, headers=h).json()["total"] == 1

    # Only an account holding services:manage can be assigned; a customer cannot (SC-05).
    customer_id = customer_auth["user"]["id"]
    refused = client.patch(url, json={"assigned_to_user_id": customer_id}, headers=h)
    assert refused.status_code == 422
    assert client.patch(url, json={"status": None}, headers=h).status_code == 422
    back = client.patch(url, json={"status": "new", "assigned_to_user_id": None}, headers=h).json()
    assert (back["status_changed_at"], back["assigned_to"]) == (None, None)
    assert client.patch(url, json={"status": "new"}, headers=h).is_success  # no change

    records = audits(db, "services.request_update")
    assert len(records) == 2
    assert records[0].change_summary["changes"]["internal_notes"] == {"changed": True}
    assert "Friday" not in str(records[0].change_summary)
    missing = client.get(f"{LEADS}/{uuid.uuid4()}", headers=h)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "service_request_not_found"
    assert client.get(url, headers=admin_auth["headers"]).status_code == 200


def test_an_inactive_staff_member_cannot_be_assigned(client, db, admin_auth):
    create(client, admin_auth)
    client.post(f"{PUBLIC}/cctv-installation/requests", json=REQUEST)
    lead = client.get(LEADS, headers=admin_auth["headers"]).json()["items"][0]
    other = make_staff(db, "administrator", "sales.two@example.com", "+250788000099")
    other["user"].is_active = False
    db.commit()
    res = client.patch(
        f"{LEADS}/{lead['id']}",
        json={"assigned_to_user_id": str(other["user"].id)},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 422
