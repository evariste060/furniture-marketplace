"""Bulk product image upload (approved 2026-10-26, checkpoint 1b topics 4–6): file names by
product slug, the job report, replace/add/unchanged per position, job ordering, limits, and the
audit trail. The worker's work is run in-process here (claim + process, as python -m app.worker).
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
from app.integrations.media import LocalMediaStorage, get_media_storage
from app.main import app
from app.models import AuditRecord, MediaObject, ProductImage
from app.services import bulk_images, jobs, media_cleanup
from app.services.bulk_images import Placement, parse_file_name
from app.services.image_processing import MAX_UPLOAD_BYTES

STAFF = "/api/v1/staff"
BULK = f"{STAFF}/products/bulk-images"


def jpeg(colour="red", size=(300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    media = LocalMediaStorage(tmp_path / "media", get_settings().image_public_base_url)
    app.dependency_overrides[get_media_storage] = lambda: media
    monkeypatch.setattr("app.services.catalog.get_media_storage", lambda: media)
    monkeypatch.setattr(bulk_images, "get_media_storage", lambda: media)
    yield media
    app.dependency_overrides.pop(get_media_storage, None)


@pytest.fixture
def products(client: TestClient, admin_auth: dict) -> dict[str, dict]:
    h = admin_auth["headers"]
    category = client.post(f"{STAFF}/categories", json={"name": "Phones"}, headers=h).json()
    made = {}
    for name in ("Samsung Galaxy A55", "Tecno Spark 20"):
        res = client.post(
            f"{STAFF}/products", json={"name": name, "category_id": category["id"]}, headers=h
        )
        assert res.status_code == 201, res.text
        made[res.json()["slug"]] = res.json()
    return made


def send(client, headers, files: list[tuple[str, bytes]]):
    return client.post(
        BULK,
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
        headers=headers,
    )


def run_worker(db: Session) -> list[str]:
    outcomes = []
    while (item_id := jobs.claim_next(db, datetime.now(UTC))) is not None:
        outcomes.append(jobs.process(db, item_id, datetime.now(UTC)))
    return outcomes


def product_images(db: Session, product_id: str) -> list[ProductImage]:
    db.expire_all()
    return list(
        db.scalars(
            select(ProductImage)
            .where(ProductImage.product_id == uuid.UUID(product_id))
            .order_by(ProductImage.sort_order)
        )
    )


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditRecord).where(AuditRecord.action == action).order_by(AuditRecord.created_at)
        )
    )


# ---- file names ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("samsung-galaxy-a55.jpg", Placement("samsung-galaxy-a55", 1)),
        ("Samsung-Galaxy-A55__2.PNG", Placement("samsung-galaxy-a55", 2)),
        ("tecno-spark-20__99.webp", Placement("tecno-spark-20", 99)),
        ("tecno-spark-20.JPEG", Placement("tecno-spark-20", 1)),
        ("photos/tecno-spark-20__3.jpg", Placement("tecno-spark-20", 3)),
        ("tecno-spark-20__0.jpg", Placement("tecno-spark-20__0", 1)),  # no position 0
        ("tecno-spark-20__100.jpg", Placement("tecno-spark-20__100", 1)),  # at most 99
        ("tecno-spark-20.gif", None),
        ("tecno-spark-20", None),
        (".jpg", None),
    ],
)
def test_file_names_give_the_slug_and_position(name, expected):
    assert parse_file_name(name) == expected


# ---- the job report ------------------------------------------------------------------------
def test_one_matched_one_unknown_and_a_duplicate_position(
    client, db, admin_auth, products, storage
):
    a55, spark = products["samsung-galaxy-a55"], products["tecno-spark-20"]
    res = send(
        client,
        admin_auth["headers"],
        [
            ("Samsung-Galaxy-A55.jpg", jpeg("red", (3000, 1500))),
            ("unknown-phone__2.jpg", jpeg()),
            ("tecno-spark-20__2.jpg", jpeg("blue")),
            ("Tecno-Spark-20__2.webp", jpeg("green")),
        ],
    )
    assert res.status_code == 202, res.text
    report = res.json()
    assert (report["type"], report["state"], report["total_items"]) == (
        "bulk_image_upload",
        "processing",
        4,
    )
    states = [(i["state"], (i["error"] or "").split(":")[0]) for i in report["items"]]
    assert states == [
        ("queued", ""),
        ("failed", "unknown_slug"),
        ("failed", "duplicate_position"),
        ("failed", "duplicate_position"),
    ]
    first = report["items"][0]["input"]
    assert first == {
        "filename": "Samsung-Galaxy-A55.jpg",
        "slug": "samsung-galaxy-a55",
        "product_name": "Samsung Galaxy A55",
        "position": 1,
        "bytes": first["bytes"],
    }
    assert report["items"][2]["input"]["product_name"] == "Tecno Spark 20"
    # Only the matched file was stored (incoming, private); nothing for the rejected ones.
    db.expire_all()
    incoming = db.scalars(select(MediaObject).where(MediaObject.kind == "incoming")).all()
    assert len(incoming) == 1 and incoming[0].state == "active"

    assert run_worker(db) == ["done"]
    job = client.get(f"{STAFF}/jobs/{report['id']}", headers=admin_auth["headers"]).json()
    assert (job["state"], job["succeeded_items"], job["failed_items"]) == ("finished", 1, 3)
    done = job["items"][0]
    assert done["result"]["outcome"] == "added" and done["result"]["slug"] == "samsung-galaxy-a55"
    assert done["result"]["url"].startswith(get_settings().image_public_base_url)
    (image,) = product_images(db, a55["id"])
    assert image.sort_order == 0 and (image.width, image.height) == (2400, 1200)
    assert product_images(db, spark["id"]) == []  # the duplicate pair was not applied

    (added,) = audits(db, "catalog.image_bulk_add")
    assert added.actor_user_id == admin_auth["user"].id
    assert added.request_id == f"job:{report['id']}"
    assert added.change_summary["job_id"] == report["id"]
    assert added.change_summary["position"] == 1 and added.change_summary["slug"] == (
        "samsung-galaxy-a55"
    )
    (complete,) = audits(db, "catalog.image_bulk_complete")
    assert complete.change_summary["added"] == 1 and complete.change_summary["failed"] == 3

    # The incoming file was retired; the cleanup worker deletes it.
    media_cleanup.delete_due(db, storage, datetime.now(UTC))
    assert list(storage.list("incoming/", visibility="private")) == []


def test_a_file_replaces_its_position_and_the_same_file_is_unchanged(
    client, db, admin_auth, products, storage
):
    h = admin_auth["headers"]
    a55 = products["samsung-galaxy-a55"]
    first, second = jpeg("red"), jpeg("blue")
    send(client, h, [("samsung-galaxy-a55.jpg", first), ("samsung-galaxy-a55__2.jpg", first)])
    run_worker(db)
    before = {i.sort_order: i for i in product_images(db, a55["id"])}
    old_original = before[0].original_media_id

    report = send(client, h, [("samsung-galaxy-a55.jpg", second)]).json()
    run_worker(db)
    after = {i.sort_order: i for i in product_images(db, a55["id"])}
    assert after[0].id == before[0].id  # the same image row, new files
    assert after[0].original_media.sha256 == hashlib.sha256(second).hexdigest()
    assert after[1].original_media_id == before[1].original_media_id  # position 2 untouched
    db.expire_all()
    assert db.get(MediaObject, old_original).state == "deleting"  # type: ignore[union-attr]
    (replaced,) = audits(db, "catalog.image_bulk_replace")
    assert replaced.change_summary["old_sha256"] == hashlib.sha256(first).hexdigest()
    assert replaced.change_summary["new_sha256"] == hashlib.sha256(second).hexdigest()
    assert replaced.change_summary["old_media_id"] == str(old_original)
    assert replaced.request_id == f"job:{report['id']}"

    same = send(client, h, [("samsung-galaxy-a55.jpg", second)]).json()
    run_worker(db)
    item = client.get(f"{STAFF}/jobs/{same['id']}", headers=h).json()["items"][0]
    assert item["state"] == "done" and item["result"]["outcome"] == "unchanged"
    assert len(audits(db, "catalog.image_bulk_replace")) == 1


def test_the_last_job_for_a_position_wins(client, db, admin_auth, products, storage):
    h = admin_auth["headers"]
    red, blue = jpeg("red"), jpeg("blue")
    send(client, h, [("tecno-spark-20.jpg", red)])
    send(client, h, [("tecno-spark-20.jpg", blue)])
    assert run_worker(db) == ["done", "done"]  # in job order, one position at a time
    (image,) = product_images(db, products["tecno-spark-20"]["id"])
    assert image.original_media.sha256 == hashlib.sha256(blue).hexdigest()


def test_an_invalid_image_fails_its_item_only_and_cannot_be_retried(
    client, db, admin_auth, products, storage
):
    h = admin_auth["headers"]
    report = send(
        client, h, [("tecno-spark-20.jpg", b"not an image"), ("samsung-galaxy-a55.jpg", jpeg())]
    ).json()
    assert run_worker(db) == ["failed", "done"]
    job = client.get(f"{STAFF}/jobs/{report['id']}", headers=h).json()
    assert job["items"][0]["error"].startswith("invalid_image:")
    assert job["items"][0]["result"]["final"] is True
    retry = client.post(f"{STAFF}/jobs/{report['id']}/retry-failed", headers=h)
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "nothing_to_retry"


# ---- limits ----------------------------------------------------------------------------------
def nothing_stored(db: Session, storage: LocalMediaStorage) -> bool:
    db.expire_all()
    no_rows = db.scalar(select(func.count(MediaObject.id))) == 0
    no_files = not storage.root.exists() or not any(p.is_file() for p in storage.root.rglob("*"))
    return no_rows and no_files


def test_more_than_20_files_is_refused_before_anything_is_stored(
    client, db, admin_auth, products, storage
):
    res = send(client, admin_auth["headers"], [(f"x{i}.jpg", b"x") for i in range(21)])
    assert res.status_code == 422
    assert "at most 20 files" in res.json()["error"]["details"][0]["msg"]
    assert nothing_stored(db, storage)


def test_a_file_over_5_mb_rejects_the_request_before_anything_is_stored(
    client, db, admin_auth, products, storage
):
    big = b"\xff" * (MAX_UPLOAD_BYTES + 1)
    res = send(client, admin_auth["headers"], [("tecno-spark-20.jpg", jpeg()), ("a.jpg", big)])
    assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"
    assert res.json()["error"]["details"] == {"files": ["a.jpg"]}
    assert nothing_stored(db, storage)


def test_a_full_upload_area_or_disk_gives_507(
    client, db, admin_auth, products, storage, monkeypatch
):
    monkeypatch.setattr(bulk_images, "MAX_INCOMING_BYTES", 10)
    res = send(client, admin_auth["headers"], [("tecno-spark-20.jpg", jpeg())])
    assert res.status_code == 507 and res.json()["error"]["code"] == "insufficient_storage"
    monkeypatch.undo()
    monkeypatch.setattr(LocalMediaStorage, "free_bytes", lambda self: 1024)
    res = send(client, admin_auth["headers"], [("tecno-spark-20.jpg", jpeg())])
    assert res.status_code == 507
    assert nothing_stored(db, storage)


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("sales_auth", 202),
        ("operations_auth", 403),
        ("management_auth", 403),
        ("finance_auth", 403),
        (None, 401),
    ],
)
def test_bulk_upload_needs_catalog_manage(client, db, products, storage, request, who, expected):
    headers = request.getfixturevalue(who)["headers"] if who else {}
    assert send(client, headers, [("tecno-spark-20.jpg", jpeg())]).status_code == expected
