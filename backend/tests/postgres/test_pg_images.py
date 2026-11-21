"""Module 7 product images over real HTTP on the least-privilege runtime role.

Proves the module's grants (INSERT, UPDATE and DELETE on product_images and media_objects), that
two API processes append concurrent uploads in a single, gap-free order, and that files land in
MEDIA_ROOT (the exact original in private/, the public source in public/; ADR-009), the public
source is served at /media while the original is not, and both are removed by the cleanup
worker (python -m app.worker, same runtime role) after the delete.
"""

import io
import secrets

import psycopg
import pytest
from PIL import Image

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one
from tests.postgres.test_pg_inventory import together
from tests.postgres.test_pg_sellers import approved_seller_headers


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1800, 900), "teal").save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.fixture
def product_id(stack: Stack, admin: dict, unique: str, phone_factory) -> str:
    base = stack.servers[0]
    seller = approved_seller_headers(stack, admin, unique, phone_factory())
    category = HTTP.post(
        f"{base}/staff/categories", json={"name": f"PG Img {secrets.token_hex(4)}"}, headers=admin
    ).json()
    product = HTTP.post(  # sellers create products; staff moderate them (SC-05)
        f"{base}/seller/products",
        json={"name": f"PG Img {secrets.token_hex(4)}", "category_id": category["id"]},
        headers=seller,
    )
    assert product.status_code == 201, product.text
    return product.json()["id"]


def add_photo(base: str, admin: dict, product_id: str) -> None:
    """Upload one product image over HTTP (the publication guard needs one to activate)."""
    res = HTTP.post(
        f"{base}/staff/products/{product_id}/images",
        files={"file": ("photo.jpg", jpeg(), "image/jpeg")},
        headers=admin,
    )
    assert res.status_code == 201, res.text


def upload(stack: Stack, i: int, admin: dict, product_id: str):
    return HTTP.post(
        f"{stack.servers[i % 2]}/staff/products/{product_id}/images",
        files={"file": (f"{i}.jpg", jpeg(), "image/jpeg")},
        headers=admin,
    )


def test_runtime_role_uploads_edits_and_deletes_images(stack: Stack, admin: dict, product_id):
    assert stack.media_root is not None
    created = upload(stack, 0, admin, product_id)
    assert created.status_code == 201, created.text
    image = created.json()
    key = image["image_ref"]
    assert (image["width"], image["height"]) == (1800, 900)  # under 2400 px: not resized
    assert (stack.media_root / "private" / key).read_bytes() == jpeg()
    assert (stack.media_root / "public" / key).is_file()
    served = HTTP.get(f"{stack.servers[1].removesuffix('/api/v1')}/media/{key}")
    assert served.status_code == 200 and Image.open(io.BytesIO(served.content)).size == (1800, 900)
    hidden = HTTP.get(f"{stack.servers[1].removesuffix('/api/v1')}/media/private/{key}")
    assert hidden.status_code == 404

    edited = HTTP.patch(
        f"{stack.servers[1]}/staff/images/{image['id']}",
        json={"alt_text": "Side view"},
        headers=admin,
    )
    assert edited.status_code == 200 and edited.json()["alt_text"] == "Side view"

    gone = HTTP.delete(f"{stack.servers[1]}/staff/images/{image['id']}", headers=admin)
    assert gone.status_code == 204
    assert (stack.media_root / "public" / key).exists()  # retired; the worker deletes it
    with stack.owner() as conn:
        states = conn.execute(
            "SELECT state FROM media_objects WHERE storage_key=%s", (key,)
        ).fetchall()
    assert sorted(s for (s,) in states) == ["deleting", "deleting"]
    stack.run_worker_once()
    assert not (stack.media_root / "public" / key).exists()
    assert not (stack.media_root / "private" / key).exists()
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM product_images WHERE id=%s", image["id"]) == (0,)
        assert one(conn, "SELECT count(*) FROM media_objects WHERE storage_key=%s", key) == (0,)
        actions = conn.execute(
            "SELECT action FROM audit_records WHERE entity_id=%s ORDER BY created_at",
            (image["id"],),
        ).fetchall()
    assert [a for (a,) in actions] == [
        "catalog.image_upload",
        "catalog.image_update",
        "catalog.image_delete",
    ]


def test_concurrent_uploads_across_processes_get_distinct_sort_orders(
    stack: Stack, admin: dict, product_id
):
    results = together(6, lambda i: upload(stack, i, admin, product_id))
    assert [r.status_code for r in results] == [201] * 6, [r.text for r in results]
    assert sorted(r.json()["sort_order"] for r in results) == [0, 1, 2, 3, 4, 5]
    assert len({r.json()["image_ref"] for r in results}) == 6


def test_oversized_upload_is_refused_on_the_live_server(stack: Stack, admin: dict, product_id):
    res = HTTP.post(
        f"{stack.servers[0]}/staff/products/{product_id}/images",
        files={"file": ("big.jpg", b"\x00" * (6 * 1024 * 1024), "image/jpeg")},
        headers=admin,
    )
    assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM product_images WHERE product_id=%s", product_id) == (
            0,
        )


def test_runtime_role_can_delete_images_but_not_other_catalogue_rows(stack: Stack):
    with stack.runtime() as conn:
        conn.execute("DELETE FROM product_images WHERE false")  # granted (module 7)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM products WHERE false")
