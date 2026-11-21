"""Module 7 — product images (PR-03, PR-10; TC-04 product images, TC-16 staff roles), with the
ADR-009 pipeline: the exact original kept privately, one sanitised public source in the original
format, no resized variants, every file tracked in the media registry and deleted only by the
cleanup worker.

Uploads need 'catalog:manage' (administrator, sales). Files go to a temporary MEDIA_ROOT here.
"""

import hashlib
import io
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.media import (
    KEY_PATTERN,
    LocalMediaStorage,
    StorageError,
    get_media_storage,
    new_key,
)
from app.main import app
from app.models import MediaObject, ProductImage
from app.models.operations import AuditRecord
from app.repositories.audit_repository import AuditRepository
from app.schemas.errors import ErrorResponse
from app.schemas.image_admin import SORT_ORDER_MAX, ImageResponse, ImageUpdateRequest
from app.schemas.images import PublicImage
from app.services import media_cleanup
from app.services.image_processing import MAX_UPLOAD_BYTES
from tests.support.catalog import force_status

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


def error_code(res) -> str:
    return res.json()["error"]["code"]


def image_bytes(size=(2400, 1200), image_format="JPEG", colour="orange") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, image_format)
    return buffer.getvalue()


def audits(db: Session, action: str, entity_id) -> list[AuditRecord]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditRecord).where(
                AuditRecord.action == action, AuditRecord.entity_id == str(entity_id)
            )
        )
    )


@pytest.fixture
def storage(tmp_path, monkeypatch):
    media = LocalMediaStorage(tmp_path / "media", get_settings().image_public_base_url)
    app.dependency_overrides[get_media_storage] = lambda: media
    # The public catalogue builds URLs outside FastAPI's dependency injection.
    monkeypatch.setattr("app.services.catalog.get_media_storage", lambda: media)
    yield media
    app.dependency_overrides.pop(get_media_storage, None)


def media_rows(db: Session) -> list[tuple[str, str, str]]:
    """(visibility, kind, state) of every media registry row."""
    db.expire_all()
    rows = db.execute(
        select(MediaObject.visibility, MediaObject.kind, MediaObject.state).order_by(
            MediaObject.visibility
        )
    )
    return [tuple(row) for row in rows]  # type: ignore[misc]


def run_cleanup(db: Session, storage) -> media_cleanup.CleanupResult:
    """What the worker does (python -m app.worker): delete every retired file, then its row."""
    return media_cleanup.delete_due(db, storage, datetime.now(UTC))


def stored_files(storage: LocalMediaStorage) -> list[str]:
    """Every stored file, as "<folder>/<key>" (folders: public, private)."""
    if not storage.root.exists():
        return []
    return sorted(
        path.relative_to(storage.root).as_posix()
        for path in storage.root.rglob("*")
        if path.is_file()
    )


@pytest.fixture
def product(client: TestClient, admin_auth: dict) -> dict:
    h = admin_auth["headers"]
    category = client.post(f"{STAFF}/categories", json={"name": "Phones"}, headers=h).json()
    created = client.post(
        f"{STAFF}/products",
        json={"name": "Galaxy S24", "category_id": category["id"]},
        headers=h,
    ).json()  # a draft: deleting its images is not restricted by the publication guard
    variant = client.post(
        f"{STAFF}/products/{created['id']}/variants",
        json={"sku": "GS24-BLK", "name": "Black", "price": 1000},
        headers=h,
    ).json()
    other = client.post(
        f"{STAFF}/products", json={"name": "Other", "category_id": category["id"]}, headers=h
    ).json()
    other_variant = client.post(
        f"{STAFF}/products/{other['id']}/variants",
        json={"sku": "OTHER-1", "name": "Std", "price": 5},
        headers=h,
    ).json()
    return {
        "headers": h,
        "id": created["id"],
        "variant_id": variant["id"],
        "other_id": other["id"],
        "other_variant_id": other_variant["id"],
    }


def upload(client, product, data=None, name="photo.jpg", content_type="image/jpeg", **form):
    return client.post(
        f"{STAFF}/products/{product['id']}/images",
        files={"file": (name, image_bytes() if data is None else data, content_type)},
        data={k: v for k, v in form.items() if v is not None},
        headers=product["headers"],
    )


# ---- upload ----------------------------------------------------------------------------------
def test_upload_stores_the_original_and_one_public_source_and_audits(
    client, product, storage, db, admin_auth
):
    raw = image_bytes(size=(2400, 1200))
    res = upload(client, product, data=raw, alt_text="  Front view  ")
    assert res.status_code == 201, res.text
    image = res.json()
    key = image["image_ref"]
    assert KEY_PATTERN.fullmatch(key) and key.endswith(".jpg")
    assert key.startswith(f"products/{product['id']}/")
    assert (image["width"], image["height"], image["sort_order"]) == (2400, 1200, 0)
    assert image["alt_text"] == "Front view" and image["variant_id"] is None
    assert image["url"] == f"{get_settings().image_public_base_url}/{key}"
    assert image["thumbnail_url"] == image["url"]  # no stored thumbnails any more

    assert stored_files(storage) == [f"private/{key}", f"public/{key}"]
    assert (storage.private_root / key).read_bytes() == raw  # the exact upload
    public = Image.open(storage.public_root / key)
    assert public.format == "JPEG" and public.size == (2400, 1200)  # same format, not resized

    db.expire_all()
    row = db.get(ProductImage, uuid.UUID(image["id"]))
    assert row is not None
    assert row.public_media.storage_key == row.original_media.storage_key == key
    assert (row.public_media.visibility, row.original_media.visibility) == ("public", "private")
    assert row.original_media.sha256 == hashlib.sha256(raw).hexdigest()
    assert row.original_media.bytes == len(raw)
    assert media_rows(db) == [
        ("private", "original", "active"),
        ("public", "public_source", "active"),
    ]

    (record,) = audits(db, "catalog.image_upload", image["id"])
    assert record.actor_user_id == admin_auth["user"].id
    assert record.change_summary["width"] == 2400
    assert record.change_summary["content_type"] == "image/jpeg"
    assert str(storage.root) not in str(record.change_summary)


@pytest.mark.parametrize(
    ("image_format", "extension"), [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")]
)
def test_each_format_stays_in_its_format_and_only_the_longest_side_is_capped(
    client, product, storage, image_format, extension
):
    res = upload(client, product, data=image_bytes(size=(1500, 3000), image_format=image_format))
    image = res.json()
    assert res.status_code == 201 and image["image_ref"].endswith(f".{extension}")
    assert (image["width"], image["height"]) == (1200, 2400)
    public = Image.open(storage.public_root / image["image_ref"])
    assert public.format == image_format and public.size == (1200, 2400)
    original = Image.open(storage.private_root / image["image_ref"])
    assert original.size == (1500, 3000)  # the original is never changed


def test_uploading_the_same_file_twice_gives_two_keys(client, product, storage):
    raw = image_bytes(size=(64, 64))
    first, second = (upload(client, product, data=raw).json() for _ in range(2))
    assert first["image_ref"] != second["image_ref"]
    assert len(stored_files(storage)) == 4


def test_the_declared_name_and_content_type_are_ignored(client, product, storage):
    png = image_bytes(size=(50, 50), image_format="PNG")
    res = upload(client, product, data=png, name="photo.jpg", content_type="image/jpeg")
    assert res.status_code == 201 and res.json()["image_ref"].endswith(".png")


@pytest.mark.parametrize(
    ("data", "name", "content_type"),
    [
        (b"hello, I am text", "photo.jpg", "image/jpeg"),
        (b"%PDF-1.7 not an image", "catalogue.pdf", "application/pdf"),
        (image_bytes(size=(20, 20), image_format="GIF"), "anim.gif", "image/gif"),
        (image_bytes(size=(20, 20), image_format="BMP"), "photo.bmp", "image/png"),
        (image_bytes()[:500], "cut.jpg", "image/jpeg"),
    ],
    ids=["text", "pdf", "gif", "bmp-declared-png", "corrupt-jpeg"],
)
def test_unsupported_or_invalid_files_are_rejected_and_nothing_is_stored(
    client, product, storage, db, data, name, content_type
):
    res = upload(client, product, data=data, name=name, content_type=content_type)
    assert res.status_code == 422 and error_code(res) == "validation_error"
    assert res.json()["error"]["details"][0]["loc"] == ["body", "file"]
    assert stored_files(storage) == []
    assert db.scalar(select(func.count(ProductImage.id))) == 0


def test_files_over_5_mb_get_413_and_nothing_is_stored(client, product, storage, db):
    just_over = upload(client, product, data=b"\x00" * (MAX_UPLOAD_BYTES + 1))
    assert just_over.status_code == 413 and error_code(just_over) == "file_too_large"
    far_over = upload(client, product, data=b"\x00" * (MAX_UPLOAD_BYTES + 200_000))
    assert far_over.status_code == 413 and error_code(far_over) == "file_too_large"
    exactly = upload(client, product, data=b"\x00" * MAX_UPLOAD_BYTES)
    assert exactly.status_code == 422  # within the size limit, but not an image
    assert stored_files(storage) == []
    assert db.scalar(select(func.count(ProductImage.id))) == 0


def test_a_missing_file_or_unknown_product_is_rejected(client, product, storage):
    no_file = client.post(
        f"{STAFF}/products/{product['id']}/images",
        data={"alt_text": "x"},
        headers=product["headers"],
    )
    assert no_file.status_code == 422
    unknown = client.post(
        f"{STAFF}/products/{uuid.uuid4()}/images",
        files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
        headers=product["headers"],
    )
    assert unknown.status_code == 404 and error_code(unknown) == "product_not_found"
    assert stored_files(storage) == []


def test_variant_must_belong_to_the_product(client, product, storage, db):
    mismatch = upload(client, product, variant_id=product["other_variant_id"])
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["details"][0]["loc"] == ["body", "variant_id"]
    unknown = upload(client, product, variant_id=str(uuid.uuid4()))
    assert unknown.status_code == 422
    assert stored_files(storage) == []

    own = upload(client, product, variant_id=product["variant_id"])
    assert own.status_code == 201 and own.json()["variant_id"] == product["variant_id"]


def test_inactive_variants_are_allowed(client, product, storage):
    client.delete(
        f"{STAFF}/products/{product['id']}/variants/{product['variant_id']}",
        headers=product["headers"],
    )
    assert upload(client, product, variant_id=product["variant_id"]).status_code == 201


def test_a_failed_audit_rolls_back_and_removes_the_written_files(
    client, product, storage, db, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    with pytest.raises(RuntimeError):
        upload(client, product)
    assert stored_files(storage) == []  # discarded right away
    db.expire_all()
    assert db.scalar(select(func.count(ProductImage.id))) == 0
    assert media_rows(db) == []


# ---- ordering and updates ----------------------------------------------------------------
def test_new_images_are_appended_and_public_order_follows_sort_order(client, product, storage):
    force_status(product["id"])  # visible in the public catalogue
    uploaded = [upload(client, product).json() for _ in range(3)]
    ids = [i["id"] for i in uploaded]
    url_of = {i["id"]: i["url"] for i in uploaded}
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    assert [i["url"] for i in detail["images"]] == [url_of[i] for i in ids]
    assert [i["position"] for i in detail["images"]] == [0, 1, 2]

    taken = client.patch(
        f"{STAFF}/images/{ids[2]}", json={"sort_order": 0}, headers=product["headers"]
    )
    assert taken.status_code == 409 and error_code(taken) == "sort_order_taken"
    moved = client.patch(
        f"{STAFF}/images/{ids[0]}", json={"sort_order": 5}, headers=product["headers"]
    )
    assert moved.status_code == 200 and moved.json()["sort_order"] == 5
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    assert [i["url"] for i in detail["images"]] == [url_of[i] for i in (ids[1], ids[2], ids[0])]
    assert upload(client, product).json()["sort_order"] == 6  # after the highest existing


def test_public_images_are_exactly_url_width_height_alt_position(client, product, storage):
    force_status(product["id"])
    uploaded = upload(client, product, alt_text="Front view").json()
    plain = upload(client, product).json()
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    listed = client.get(f"{PUBLIC}/products").json()["items"][0]
    for public in (detail, listed):
        first, second = public["images"]
        assert first == {
            "url": uploaded["url"],
            "width": 2400,
            "height": 1200,
            "alt": "Front view",
            "position": 0,
        }
        # Without alt text, the product name is the alt.
        assert second["url"] == plain["url"] and second["alt"] == "Galaxy S24"


def test_variant_images_appear_under_their_variant_and_can_become_product_level(
    client, product, storage
):
    force_status(product["id"])
    image = upload(client, product, variant_id=product["variant_id"]).json()
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    assert detail["images"] == [] and len(detail["variants"][0]["images"]) == 1
    assert detail["variants"][0]["images"][0]["url"] == image["url"]

    res = client.patch(
        f"{STAFF}/images/{image['id']}", json={"variant_id": None}, headers=product["headers"]
    )
    assert res.status_code == 200 and res.json()["variant_id"] is None
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    assert [i["url"] for i in detail["images"]] == [image["url"]]


def test_image_updates_are_validated_and_audited(client, product, storage, db):
    h = product["headers"]
    image = upload(client, product).json()
    path = f"{STAFF}/images/{image['id']}"
    for body in (
        {},
        {"sort_order": -1},
        {"sort_order": None},
        {"sort_order": 2**31},
        {"alt_text": "x" * 301},
        {"storage_key": "products/evil.jpg"},
        {"width": 5},
    ):
        res = client.patch(path, json=body, headers=h)
        assert res.status_code == 422, body
    wrong = client.patch(path, json={"variant_id": product["other_variant_id"]}, headers=h)
    assert wrong.status_code == 422
    assert wrong.json()["error"]["details"][0]["loc"] == ["body", "variant_id"]
    missing = client.patch(f"{STAFF}/images/{uuid.uuid4()}", json={"sort_order": 1}, headers=h)
    assert missing.status_code == 404 and error_code(missing) == "image_not_found"

    client.patch(path, json={"sort_order": 0}, headers=h)  # unchanged: no audit
    assert audits(db, "catalog.image_update", image["id"]) == []
    client.patch(path, json={"alt_text": "Back", "sort_order": 4}, headers=h)
    (record,) = audits(db, "catalog.image_update", image["id"])
    assert record.change_summary["changes"] == {
        "alt_text": {"from": None, "to": "Back"},
        "sort_order": {"from": 0, "to": 4},
    }
    cleared = client.patch(path, json={"alt_text": None}, headers=h)
    assert cleared.json()["alt_text"] is None


# ---- delete --------------------------------------------------------------------------------
def test_delete_removes_the_row_and_the_worker_then_deletes_both_files(
    client, product, storage, db
):
    image = upload(client, product).json()
    assert len(stored_files(storage)) == 2
    res = client.delete(f"{STAFF}/images/{image['id']}", headers=product["headers"])
    assert res.status_code == 204 and res.content == b""
    db.expire_all()
    assert db.get(ProductImage, uuid.UUID(image["id"])) is None
    (record,) = audits(db, "catalog.image_delete", image["id"])
    assert record.change_summary["image_ref"] == image["image_ref"]
    # Retired in the same transaction; the files stay until the cleanup worker runs.
    assert media_rows(db) == [
        ("private", "original", "deleting"),
        ("public", "public_source", "deleting"),
    ]
    assert len(stored_files(storage)) == 2
    assert run_cleanup(db, storage).deleted == 2
    assert stored_files(storage) == [] and media_rows(db) == []
    again = client.delete(f"{STAFF}/images/{image['id']}", headers=product["headers"])
    assert again.status_code == 404 and error_code(again) == "image_not_found"


def test_a_file_the_worker_cannot_delete_is_retried_and_shown_to_staff(
    client, product, storage, db, monkeypatch
):
    image = upload(client, product).json()
    client.delete(f"{STAFF}/images/{image['id']}", headers=product["headers"])

    def locked(self, key, *, visibility):
        raise StorageError("Cannot delete the file (PermissionError).")

    monkeypatch.setattr(LocalMediaStorage, "delete", locked)
    result = run_cleanup(db, storage)
    assert (result.deleted, result.failed) == (0, 2)
    assert len(stored_files(storage)) == 2  # honestly left behind, not claimed as removed
    db.expire_all()
    stuck = db.scalars(select(MediaObject)).all()
    assert {(m.state, m.attempts) for m in stuck} == {("deleting", 1)}
    assert all("PermissionError" in (m.last_error or "") for m in stuck)
    assert all(m.delete_after and m.delete_after > datetime.now(UTC) for m in stuck)  # backoff

    listed = client.get(f"{STAFF}/media/cleanup-problems", headers=product["headers"])
    assert listed.status_code == 200 and listed.json()["total"] == 2
    assert {p["storage_key"] for p in listed.json()["items"]} == {image["image_ref"]}
    assert run_cleanup(db, storage).failed == 0  # not due again until the backoff passes

    monkeypatch.undo()
    for media in stuck:
        media.delete_after = datetime.now(UTC)
    db.commit()
    assert run_cleanup(db, storage).deleted == 2
    assert stored_files(storage) == [] and media_rows(db) == []


def test_a_failed_delete_audit_keeps_the_row_the_files_and_their_registry_state(
    client, product, storage, db, monkeypatch
):
    image = upload(client, product).json()

    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    with pytest.raises(RuntimeError):
        client.delete(f"{STAFF}/images/{image['id']}", headers=product["headers"])
    db.expire_all()
    assert db.get(ProductImage, uuid.UUID(image["id"])) is not None
    assert {state for _, _, state in media_rows(db)} == {"active"}
    assert run_cleanup(db, storage).deleted == 0
    assert len(stored_files(storage)) == 2


# ---- authorization -----------------------------------------------------------------------
def test_sales_staff_manage_images(client, product, storage, sales_auth):
    res = client.post(
        f"{STAFF}/products/{product['id']}/images",
        files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
        headers=sales_auth["headers"],
    )
    assert res.status_code == 201
    h = sales_auth["headers"]
    edited = client.patch(f"{STAFF}/images/{res.json()['id']}", json={"sort_order": 3}, headers=h)
    assert edited.status_code == 200 and edited.json()["sort_order"] == 3
    assert client.delete(f"{STAFF}/images/{res.json()['id']}", headers=h).status_code == 204


@pytest.mark.parametrize("who", ["operations_auth", "management_auth", "customer_auth"])
def test_other_roles_are_forbidden_and_nothing_is_stored(
    client, product, storage, db, who, request
):
    image = upload(client, product).json()
    before = stored_files(storage)
    h = request.getfixturevalue(who)["headers"]
    attempts = [
        client.post(
            f"{STAFF}/products/{product['id']}/images",
            files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
            headers=h,
        ),
        client.patch(f"{STAFF}/images/{image['id']}", json={"sort_order": 5}, headers=h),
        client.delete(f"{STAFF}/images/{image['id']}", headers=h),
    ]
    assert [r.status_code for r in attempts] == [403] * 3
    assert {error_code(r) for r in attempts} == {"permission_denied"}
    assert stored_files(storage) == before
    db.expire_all()
    stored = db.get(ProductImage, uuid.UUID(image["id"]))
    assert stored is not None and stored.sort_order == 0


def test_anonymous_requests_are_unauthorized(client, storage):
    res = client.post(
        f"{STAFF}/products/{uuid.uuid4()}/images",
        files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
    )
    assert res.status_code == 401 and error_code(res) == "token_missing"
    assert client.delete(f"{STAFF}/images/{uuid.uuid4()}").status_code == 401
    assert stored_files(storage) == []


# ---- development file serving --------------------------------------------------------------
def test_development_serves_public_sources_and_never_private_originals(client):
    assert get_settings().app_env == "development"
    settings = get_settings()
    served = LocalMediaStorage(settings.media_root, settings.image_public_base_url)
    key = new_key("products", uuid.uuid4(), "png", b"test")
    served.put(key, b"\x89PNG-public", visibility="public", content_type="image/png")
    private_only = new_key("products", uuid.uuid4(), "png", b"secret")
    served.put(private_only, b"\x89PNG-original", visibility="private", content_type="image/png")
    try:
        res = client.get(f"/media/{key}")
        assert res.status_code == 200 and res.content == b"\x89PNG-public"
        for path in (f"/media/{private_only}", f"/media/private/{private_only}"):
            res = client.get(path)
            assert res.status_code == 404 and b"original" not in res.content, path
        assert client.get("/media/../.env").status_code == 404
    finally:
        served.delete(key, visibility="public")
        served.delete(private_only, visibility="private")


def test_a_real_upload_is_served_publicly_but_its_original_is_not(client, product, db):
    """End to end on the app's own storage and /media mount (no storage override)."""
    raw = image_bytes(size=(80, 40))
    image = upload(client, product, data=raw).json()
    settings = get_settings()
    served = LocalMediaStorage(settings.media_root, settings.image_public_base_url)
    key = image["image_ref"]
    try:
        public = client.get(image["url"].replace(settings.image_public_base_url, "/media"))
        assert public.status_code == 200 and Image.open(io.BytesIO(public.content)).size == (80, 40)
        assert (served.private_root / key).read_bytes() == raw
        for path in (f"/media/private/{key}", f"/media/../private/{key}"):
            res = client.get(path)
            assert res.status_code == 404 and res.content != raw, path
    finally:
        client.delete(f"{STAFF}/images/{image['id']}", headers=product["headers"])
        run_cleanup(db, served)
    assert not (served.public_root / key).exists() and not (served.private_root / key).exists()


# ---- negative cases and failures -----------------------------------------------------------
def test_malformed_ids_are_rejected_before_anything_is_stored(client, product, storage):
    h = product["headers"]
    attempts = [
        client.post(
            f"{STAFF}/products/not-a-uuid/images",
            files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
            headers=h,
        ),
        upload(client, product, variant_id="not-a-uuid"),
        client.patch(f"{STAFF}/images/not-a-uuid", json={"sort_order": 1}, headers=h),
        client.delete(f"{STAFF}/images/not-a-uuid", headers=h),
    ]
    assert [r.status_code for r in attempts] == [422] * 4
    assert {error_code(r) for r in attempts} == {"validation_error"}
    assert stored_files(storage) == []


def test_a_failed_file_write_stores_no_row_and_leaves_no_file(
    client, product, storage, db, monkeypatch
):
    real_put = LocalMediaStorage.put
    written: list[str] = []

    def fail_on_public_copy(self, key, data, *, visibility, content_type, cache_control=None):
        written.append(visibility)
        if visibility == "public":
            raise StorageError("Cannot write the file (OSError).")
        real_put(self, key, data, visibility=visibility, content_type=content_type)

    monkeypatch.setattr(LocalMediaStorage, "put", fail_on_public_copy)
    with pytest.raises(StorageError):
        upload(client, product)
    assert written == ["private", "public"]  # the original was written, then the copy failed
    assert stored_files(storage) == []  # and the original was removed again
    db.expire_all()
    assert db.scalar(select(func.count(ProductImage.id))) == 0
    assert media_rows(db) == []  # the pending registry rows too
    assert (
        db.scalar(
            select(func.count(AuditRecord.id)).where(AuditRecord.action == "catalog.image_upload")
        )
        == 0
    )


def test_a_failed_file_write_returns_a_generic_500(product, storage, monkeypatch):
    def fail(self, key, data, *, visibility, content_type, cache_control=None):
        raise StorageError("simulated disk full")

    monkeypatch.setattr(LocalMediaStorage, "put", fail)
    with TestClient(app, raise_server_exceptions=False) as plain:
        res = upload(plain, product)
    assert res.status_code == 500 and error_code(res) == "internal_error"
    assert "disk" not in res.text
    assert stored_files(storage) == []


def test_no_higher_sort_order_gives_409_and_stores_nothing(client, product, storage, db):
    image = upload(client, product).json()
    top = client.patch(
        f"{STAFF}/images/{image['id']}",
        json={"sort_order": SORT_ORDER_MAX},
        headers=product["headers"],
    )
    assert top.status_code == 200
    res = upload(client, product)
    assert res.status_code == 409 and error_code(res) == "sort_order_full"
    assert len(stored_files(storage)) == 2  # only the first image's files; the new ones discarded
    db.expire_all()
    assert db.scalar(select(func.count(ProductImage.id))) == 1


def test_an_oversized_anonymous_upload_gets_413_and_a_small_one_401(client, storage, db):
    """The size limit runs before authentication (documented); neither stores anything."""
    path = f"{STAFF}/products/{uuid.uuid4()}/images"
    big = client.post(path, files={"file": ("a.jpg", b"\x00" * (MAX_UPLOAD_BYTES + 200_000))})
    assert big.status_code == 413 and error_code(big) == "file_too_large"
    small = client.post(path, files={"file": ("a.jpg", image_bytes(), "image/jpeg")})
    assert small.status_code == 401 and error_code(small) == "token_missing"
    assert stored_files(storage) == []
    assert db.scalar(select(func.count(ProductImage.id))) == 0


# ---- OpenAPI contract ----------------------------------------------------------------------
UPLOAD_PATH = "/api/v1/staff/products/{product_id}/images"
IMAGE_PATH = "/api/v1/staff/images/{image_id}"
IMAGE_OPERATIONS = {
    ("post", UPLOAD_PATH): {"201", "401", "403", "404", "409", "413", "422"},
    ("patch", IMAGE_PATH): {"200", "401", "403", "404", "422"},
    ("delete", IMAGE_PATH): {"204", "401", "403", "404", "422"},
}


def openapi_spec() -> dict:
    app.openapi_schema = None
    return app.openapi()


def documented_errors(spec: dict, method: str, path: str, status: str) -> list[dict]:
    """FastAPI drops null values from the document, so a missing `details` means null."""
    content = spec["paths"][path][method]["responses"][status]["content"]["application/json"]
    return [
        {"details": None, **example["value"]["error"]}
        for example in content.get("examples", {}).values()
    ]


def test_openapi_documents_every_image_response_with_valid_examples():
    spec = openapi_spec()
    for (method, path), codes in IMAGE_OPERATIONS.items():
        operation = spec["paths"][path][method]
        assert set(operation["responses"]) == codes, (method, path)
        assert operation["security"] == [{"BearerAuth": []}]
        for status in codes - {"200", "201", "204"}:
            examples = documented_errors(spec, method, path, status)
            assert examples, (method, path, status)
            for example in examples:
                ErrorResponse.model_validate({"error": example})

    schemas = spec["components"]["schemas"]
    for name in ("ImageResponse", "PublicImage"):
        (example,) = schemas[name]["examples"]
        assert set(example) == set(schemas[name]["properties"]), name
    ImageResponse.model_validate(schemas["ImageResponse"]["examples"][0])
    PublicImage.model_validate(schemas["PublicImage"]["examples"][0])

    patch_body = spec["paths"][IMAGE_PATH]["patch"]["requestBody"]["content"]
    examples = patch_body["application/json"]["examples"]
    assert set(examples) == {"reorder", "describe", "everything"}
    for example in examples.values():
        ImageUpdateRequest.model_validate(example["value"])
    assert "multipart/form-data" in spec["paths"][UPLOAD_PATH]["post"]["requestBody"]["content"]


def test_documented_error_examples_match_real_responses(client, product, storage, operations_auth):
    """Every error the API really returns here is one of the documented examples, verbatim."""
    spec = openapi_spec()
    h = product["headers"]
    image = upload(client, product).json()
    other_variant = product["other_variant_id"]
    image_url = f"{STAFF}/images/{image['id']}"
    unknown_url = f"{STAFF}/images/{uuid.uuid4()}"
    anonymous = client.post(
        f"{STAFF}/products/{product['id']}/images",
        files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
    )
    forbidden = client.post(
        f"{STAFF}/products/{product['id']}/images",
        files={"file": ("a.jpg", image_bytes(), "image/jpeg")},
        headers=operations_auth["headers"],
    )
    real = {
        ("post", UPLOAD_PATH, "401"): [anonymous],
        ("post", UPLOAD_PATH, "403"): [forbidden],
        ("post", UPLOAD_PATH, "404"): [upload(client, {**product, "id": str(uuid.uuid4())})],
        ("post", UPLOAD_PATH, "413"): [
            upload(client, product, data=b"\x00" * (MAX_UPLOAD_BYTES + 200_000)),
            upload(client, product, data=b"\x00" * (MAX_UPLOAD_BYTES + 1)),
        ],
        ("post", UPLOAD_PATH, "422"): [
            upload(client, product, data=b"not an image"),
            upload(client, product, variant_id=other_variant),
        ],
        ("patch", IMAGE_PATH, "404"): [
            client.patch(unknown_url, json={"sort_order": 1}, headers=h)
        ],
        ("patch", IMAGE_PATH, "422"): [
            client.patch(image_url, json={}, headers=h),
            client.patch(image_url, json={"variant_id": other_variant}, headers=h),
        ],
        ("delete", IMAGE_PATH, "404"): [client.delete(unknown_url, headers=h)],
        ("delete", IMAGE_PATH, "422"): [client.delete(f"{STAFF}/images/not-a-uuid", headers=h)],
    }
    for (method, path, status), responses in real.items():
        documented = documented_errors(spec, method, path, status)
        for res in responses:
            assert str(res.status_code) == status, (method, path, res.text)
            assert res.json()["error"] in documented, (method, path, status, res.json())


# ---- reorder (frontend phase 6) --------------------------------------------------------------
def order_url(product) -> str:
    return f"{STAFF}/products/{product['id']}/images/order"


def test_reorder_sets_positions_in_one_go_and_audits(client, product, storage, db):
    ids = [upload(client, product).json()["id"] for _ in range(3)]
    variant_image = upload(client, product, variant_id=product["variant_id"]).json()

    res = client.put(order_url(product), json={"image_ids": ids[::-1]}, headers=product["headers"])

    assert res.status_code == 200, res.text
    assert [(i["id"], i["sort_order"]) for i in res.json()] == [
        (ids[2], 0),
        (ids[1], 1),
        (ids[0], 2),
    ]
    detail = client.get(f"{STAFF}/products/{product['id']}", headers=product["headers"]).json()
    names = {n["image_id"]: n["file_name"] for n in detail["photo_file_names"]}
    assert names[ids[2]] == "galaxy-s24.jpg" and names[ids[0]] == "galaxy-s24__3.jpg"
    variant_row = db.get(ProductImage, uuid.UUID(variant_image["id"]))
    assert variant_row is not None and variant_row.sort_order == variant_image["sort_order"]
    [record] = audits(db, "catalog.image_reorder", product["id"])
    assert record.change_summary["from"] == ids
    assert record.change_summary["to"] == ids[::-1]


def test_reorder_with_the_current_order_changes_nothing(client, product, storage, db):
    ids = [upload(client, product).json()["id"] for _ in range(2)]
    res = client.put(order_url(product), json={"image_ids": ids}, headers=product["headers"])
    assert res.status_code == 200
    assert audits(db, "catalog.image_reorder", product["id"]) == []


@pytest.mark.parametrize("case", ["missing", "variant_image", "foreign", "duplicate", "empty"])
def test_reorder_must_list_every_product_image_once(client, product, storage, case):
    ids = [upload(client, product).json()["id"] for _ in range(2)]
    variant_image = upload(client, product, variant_id=product["variant_id"]).json()["id"]
    body = {
        "missing": ids[:1],
        "variant_image": [*ids, variant_image],
        "foreign": [ids[0], str(uuid.uuid4())],
        "duplicate": [ids[0], ids[0], ids[1]],
        "empty": [],
    }[case]
    res = client.put(order_url(product), json={"image_ids": body}, headers=product["headers"])
    assert res.status_code == 422 and error_code(res) == "validation_error"


def test_reorder_unknown_product_and_roles(client, product, storage, operations_auth, sales_auth):
    ids = [upload(client, product).json()["id"]]
    unknown = client.put(
        f"{STAFF}/products/{uuid.uuid4()}/images/order",
        json={"image_ids": ids},
        headers=product["headers"],
    )
    assert unknown.status_code == 404 and error_code(unknown) == "product_not_found"
    forbidden = client.put(
        order_url(product), json={"image_ids": ids}, headers=operations_auth["headers"]
    )
    assert forbidden.status_code == 403
    allowed = client.put(order_url(product), json={"image_ids": ids}, headers=sales_auth["headers"])
    assert allowed.status_code == 200
