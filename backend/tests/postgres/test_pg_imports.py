"""Module 8 catalogue import over real HTTP on the least-privilege runtime role.

Proves the module's grants (INSERT, UPDATE on import_jobs plus the catalogue and stock grants it
reuses) and that concurrent imports in two API processes are serialised: the same new SKU in
two files is created once and updated once, never duplicated or refused with an error.

SC-05 / ADR-014 phase 2: imports update existing products only (a seller creates them), so each
test's product is created by an approved seller first; new SKUs on it are still created.
"""

import csv
import io
import secrets

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, one
from tests.postgres.test_pg_inventory import together
from tests.postgres.test_pg_sellers import approved_seller_headers

HEADERS = ["sku", "product_slug", "product_name", "category_slug", "variant_name", "price"]


def csv_file(rows: list[list[str]], headers: list[str] = HEADERS) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode()


def upload(base: str, admin: dict, data: bytes):
    return HTTP.post(
        f"{base}/staff/imports", files={"file": ("pg.csv", data, "text/csv")}, headers=admin
    )


@pytest.fixture
def category(stack: Stack, admin: dict) -> dict:
    slug = f"pg-import-{secrets.token_hex(4)}"
    res = HTTP.post(
        f"{stack.servers[0]}/staff/categories", json={"name": slug, "slug": slug}, headers=admin
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def seller_product(stack: Stack, admin: dict, unique: str, phone_factory, category: dict):
    """A function creating a draft product in an approved seller's store."""
    seller = approved_seller_headers(stack, admin, unique, phone_factory())

    def make(slug: str, name: str) -> None:
        res = HTTP.post(
            f"{stack.servers[0]}/seller/products",
            json={"name": name, "slug": slug, "category_id": category["id"]},
            headers=seller,
        )
        assert res.status_code == 201, res.text

    return make


def test_runtime_role_imports_products_with_opening_stock(
    stack: Stack, admin: dict, category: dict, seller_product
):
    tag = secrets.token_hex(4)
    seller_product(f"pg-{tag}", "PG phone")
    seller_product(f"pg-{tag}-b", "PG phone B")
    data = csv_file(
        [
            [f"PG-{tag}-1", f"pg-{tag}", "PG phone", category["slug"], "Std", "1000", "5"],
            [f"PG-{tag}-2", f"pg-{tag}-b", "PG phone B", "missing-category", "Pro", "2000", ""],
        ],
        HEADERS + ["opening_stock"],
    )
    res = upload(stack.servers[0], admin, data)
    assert res.status_code == 201, res.text
    job = res.json()
    assert (job["status"], job["imported_rows"], job["error_rows"]) == ("completed", 1, 1)
    read = HTTP.get(f"{stack.servers[1]}/staff/imports/{job['id']}", headers=admin)
    assert read.status_code == 200 and read.json() == job
    with stack.owner() as conn:
        (on_hand,) = one(
            conn,
            "SELECT b.on_hand FROM inventory_balances b JOIN product_variants v "
            "ON v.id = b.variant_id WHERE v.sku = %s",
            f"PG-{tag}-1",
        )
        assert on_hand == 5
        assert one(conn, "SELECT status FROM import_jobs WHERE id = %s", job["id"]) == (
            "completed",
        )


def test_concurrent_imports_of_the_same_new_sku_create_it_once(
    stack: Stack, admin: dict, category: dict, seller_product
):
    tag = secrets.token_hex(4)
    sku = f"RACE-{tag}"
    seller_product(f"race-{tag}", "Race")

    def run(i: int):
        data = csv_file([[sku, f"race-{tag}", "Race", category["slug"], "Std", str(100 + i)]])
        return upload(stack.servers[i % 2], admin, data)

    results = together(4, run)
    assert [r.status_code for r in results] == [201] * 4, [r.text for r in results]
    assert all(r.json()["imported_rows"] == 1 for r in results)
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM product_variants WHERE sku = %s", sku) == (1,)
        assert one(conn, "SELECT count(*) FROM products WHERE slug = %s", f"race-{tag}") == (1,)


def test_template_downloads_on_the_live_server(stack: Stack, admin: dict):
    res = HTTP.get(f"{stack.servers[0]}/staff/imports/template?format=xlsx", headers=admin)
    assert res.status_code == 200 and res.content.startswith(b"PK\x03\x04")


def test_runtime_role_cannot_delete_import_jobs(stack: Stack):
    with stack.runtime() as conn:
        conn.execute("UPDATE import_jobs SET filename = filename WHERE false")  # granted
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM import_jobs WHERE false")
