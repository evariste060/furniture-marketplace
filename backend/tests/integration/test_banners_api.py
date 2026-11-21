"""Homepage banners (approved 2026-10-26, checkpoint 1b topic 9): the public list and its window,
the staff routes ('content:manage'), CTA URL and text validation, the image rule, and the audit
trail with before and after values."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.media import LocalMediaStorage, get_media_storage
from app.main import app
from app.models import AuditRecord
from app.models.content import Banner

PUBLIC = "/api/v1/banners"
STAFF = "/api/v1/staff/banners"
BODY = {
    "title_en": "Original phones, laptops & electronics",
    "title_rw": "Telefoni, mudasobwa n'ibikoresho by'umwimerere",
    "subtitle_en": "Genuine products, delivered in Kigali",
    "cta_label_en": "Shop Phones",
    "cta_label_rw": "Gura telefoni",
    "cta_url": "/category/phones",
}


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1600, 1200), "navy").save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def storage(tmp_path):
    media = LocalMediaStorage(tmp_path / "media", get_settings().image_public_base_url)
    app.dependency_overrides[get_media_storage] = lambda: media
    yield media
    app.dependency_overrides.pop(get_media_storage, None)


def create(client, headers, **extra) -> dict:
    res = client.post(STAFF, json={**BODY, **extra}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def live(client, headers, **extra) -> dict:
    banner = create(client, headers, **extra)
    image = client.post(
        f"{STAFF}/{banner['id']}/image",
        files={"file": ("hero.jpg", jpeg(), "image/jpeg")},
        headers=headers,
    )
    assert image.status_code == 200, image.text
    res = client.patch(f"{STAFF}/{banner['id']}", json={"is_active": True}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def test_the_public_list_has_the_shown_banners_in_order_and_is_cached(
    client, db, admin_auth, storage
):
    h = admin_auth["headers"]
    second = live(client, h, position=2)
    first = live(client, h, position=1)
    create(client, h, position=0)  # inactive: never public
    res = client.get(PUBLIC)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=60"
    body = res.json()
    assert (body["total"], [b["id"] for b in body["items"]]) == (2, [first["id"], second["id"]])
    hero = body["items"][0]
    assert hero["title"] == {"en": BODY["title_en"], "rw": BODY["title_rw"]}
    assert hero["subtitle"] == {"en": BODY["subtitle_en"], "rw": None}
    assert hero["overline"] is None  # optional; none sent
    assert hero["cta_label"] == {"en": "Shop Phones", "rw": "Gura telefoni"}
    assert hero["cta_url"] == "/category/phones"
    assert set(hero["image"]) == {"url", "width", "height", "alt", "position"}
    assert (hero["image"]["width"], hero["image"]["height"], hero["image"]["position"]) == (
        1600,
        1200,
        0,
    )
    assert (hero["starts_at"], hero["ends_at"]) == (None, None)


def test_the_overline_is_optional_limited_cleaned_public_and_clearable(
    client, db, admin_auth, storage
):
    """Owner decision 2026-10-27: an optional overline {en, rw}, at most 40 characters."""
    h = admin_auth["headers"]
    banner = live(
        client,
        h,
        overline_en=" Latest electronics, better everyday life ",
        overline_rw="Ikoranabuhanga rigezweho",
    )
    assert banner["overline_en"] == "Latest electronics, better everyday life"  # 40, trimmed
    assert banner["overline_rw"] == "Ikoranabuhanga rigezweho"
    hero = client.get(PUBLIC).json()["items"][0]
    assert hero["overline"] == {
        "en": "Latest electronics, better everyday life",
        "rw": "Ikoranabuhanga rigezweho",
    }

    for field, value in (("overline_en", "x" * 41), ("overline_rw", "  "), ("overline_en", 5)):
        assert client.post(STAFF, json={**BODY, field: value}, headers=h).status_code == 422
        res = client.patch(f"{STAFF}/{banner['id']}", json={field: value}, headers=h)
        assert res.status_code == 422, (field, value)

    res = client.patch(
        f"{STAFF}/{banner['id']}", json={"overline_en": None, "overline_rw": None}, headers=h
    )
    assert res.status_code == 200 and res.json()["overline_en"] is None
    assert client.get(PUBLIC).json()["items"][0]["overline"] is None
    (change,) = [
        r.change_summary["changes"]
        for r in audits(db, "content.banner_update")
        if "overline_en" in r.change_summary.get("changes", {})
    ]
    assert change["overline_en"] == {
        "from": "Latest electronics, better everyday life",
        "to": None,
    }


def test_the_window_is_evaluated_now(client, db, admin_auth, storage):
    h = admin_auth["headers"]
    banner = live(client, h)
    now = datetime.now(UTC)
    for starts, ends, shown in (
        (now + timedelta(hours=1), None, False),  # not started
        (None, now - timedelta(seconds=1), False),  # ended
        (now - timedelta(hours=1), now + timedelta(hours=1), True),
    ):
        db.execute(
            update(Banner).where(Banner.id == banner["id"]).values(starts_at=starts, ends_at=ends)
        )
        db.commit()
        assert client.get(PUBLIC).json()["total"] == (1 if shown else 0)
    staff = client.get(STAFF, headers=h).json()["items"][0]
    assert staff["shown_now"] is True


def test_local_kigali_times_are_stored_in_utc_and_the_window_must_be_ordered(
    client, admin_auth, storage
):
    h = admin_auth["headers"]
    banner = create(client, h, starts_at="2026-11-01T00:00:00", ends_at="2026-12-01T00:00:00+02:00")
    assert banner["starts_at"] == "2026-11-01T00:00:00+02:00"
    bad = client.post(
        STAFF,
        json={**BODY, "starts_at": "2026-12-01T00:00:00", "ends_at": "2026-11-01T00:00:00"},
        headers=h,
    )
    assert bad.status_code == 422
    flipped = client.patch(
        f"{STAFF}/{banner['id']}", json={"ends_at": "2026-10-01T00:00:00"}, headers=h
    )
    assert flipped.status_code == 409 and flipped.json()["error"]["code"] == "banner_invalid"


@pytest.mark.parametrize(
    "url",
    [
        "//evil.example",
        "/\\evil.example",
        "/%2F%2Fevil.example",
        "/%2f%5cevil",
        "javascript:alert(1)",
        "https://evil.example/",
        "/path with space",
        "/tab\there",
        "/new\nline",
        "/%0aheader",
        "category/phones",
        "/" + "a" * 200,
        "/café",
        "/a\\b",
        "/brand/samsung%20galaxy",  # decodes to a space
    ],
)
def test_unsafe_cta_urls_are_refused(client, admin_auth, url):
    res = client.post(STAFF, json={**BODY, "cta_url": url}, headers=admin_auth["headers"])
    assert res.status_code == 422, url


@pytest.mark.parametrize(
    "url", ["/", "/category/phones", "/search?q=a55&sort=price#top", "/search?q=galaxy%2Da55"]
)
def test_on_site_paths_are_accepted(client, admin_auth, url):
    res = client.post(STAFF, json={**BODY, "cta_url": url}, headers=admin_auth["headers"])
    assert res.status_code == 201, url


def test_text_is_plain_and_bounded(client, admin_auth):
    h = admin_auth["headers"]
    clean = create(client, h, title_en="  Big\x00 sale​  ", subtitle_rw="Igabanuka\x07")
    assert clean["title_en"] == "Big sale" and clean["subtitle_rw"] == "Igabanuka"
    for body in (
        {**BODY, "title_en": "x" * 81},
        {**BODY, "subtitle_en": "x" * 161},
        {**BODY, "cta_label_rw": "x" * 31},
        {**BODY, "title_rw": "\x00\x01"},  # nothing left after cleaning
        {**BODY, "cta_label_en": None},  # a CTA URL needs both labels
        {k: v for k, v in BODY.items() if k != "title_rw"},
        {**BODY, "is_active": True},  # created inactive; unknown field refused
    ):
        assert client.post(STAFF, json=body, headers=h).status_code == 422, body


def test_activation_needs_an_image_and_an_active_banner_keeps_it(client, db, admin_auth, storage):
    h = admin_auth["headers"]
    banner = create(client, h)
    path = f"{STAFF}/{banner['id']}"
    refused = client.patch(path, json={"is_active": True}, headers=h)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "banner_needs_image"
    banner = live(client, h)
    path = f"{STAFF}/{banner['id']}"
    kept = client.delete(f"{path}/image", headers=h)
    assert kept.status_code == 409 and kept.json()["error"]["code"] == "banner_needs_image"
    client.patch(path, json={"is_active": False}, headers=h)
    removed = client.delete(f"{path}/image", headers=h)
    assert removed.status_code == 200 and removed.json()["image"] is None


def test_changes_are_audited_with_before_and_after_values(client, db, admin_auth, storage):
    h = admin_auth["headers"]
    banner = create(client, h)
    (created,) = audits(db, "content.banner_create")
    assert created.change_summary["after"]["title_en"] == BODY["title_en"]
    client.patch(f"{STAFF}/{banner['id']}", json={"position": 3, "cta_url": "/deals"}, headers=h)
    client.patch(f"{STAFF}/{banner['id']}", json={"position": 3}, headers=h)  # no change
    (changed,) = audits(db, "content.banner_update")
    assert changed.change_summary["changes"] == {
        "position": {"from": 0, "to": 3},
        "cta_url": {"from": "/category/phones", "to": "/deals"},
    }
    assert client.delete(f"{STAFF}/{banner['id']}", headers=h).status_code == 204
    (deleted,) = audits(db, "content.banner_delete")
    assert deleted.change_summary["before"]["cta_url"] == "/deals"
    missing = client.patch(f"{STAFF}/{banner['id']}", json={"position": 1}, headers=h)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "banner_not_found"


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("admin_auth", 200),
        ("customer_auth", 403),
        (None, 401),
    ],
)
def test_staff_banner_routes_need_content_manage(client, request, who, expected):
    headers = request.getfixturevalue(who)["headers"] if who else {}
    assert client.get(STAFF, headers=headers).status_code == expected
    assert client.get(PUBLIC).status_code == 200  # the public list needs nothing
