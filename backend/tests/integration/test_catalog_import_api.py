"""Module 8 — catalogue import over the API (TC-15; TC-16 staff roles).

Runs on the disposable per-test PostgreSQL schema (tests/conftest.py). Uploads need
'catalog:manage' (administrator, sales).
"""

import csv
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models import ImportJob, InventoryBalance, Product, ProductVariant, StockMovement
from app.models.operations import AuditRecord
from app.services import catalog_import
from app.services.catalog_import import UNEXPECTED_FAILURE
from app.services.import_files import XLSX_CONTENT_TYPE, template_headers
from tests.support.catalog import force_status
from tests.support.sellers import post_product

STAFF = "/api/v1/staff"
IMPORTS = f"{STAFF}/imports"
HEADERS = [
    "sku",
    "product_slug",
    "product_name",
    "category_slug",
    "brand_slug",
    "variant_name",
    "price",
    "compare_at_price",
    "description",
    "attr:colour",
]


def code(res) -> str:
    return res.json()["error"]["code"]


def csv_file(rows: list[list[object]], headers: list[str] = HEADERS) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def xlsx_file(rows: list[list[object]], headers: list[str] = HEADERS) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(headers)
    for values in rows:
        sheet.append(values)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def post(client: TestClient, headers: dict, data: bytes, name: str = "catalogue.csv"):
    return client.post(
        IMPORTS, files={"file": (name, data, "application/octet-stream")}, headers=headers
    )


def by_row(job: dict) -> dict[int, set[str]]:
    rows: dict[int, set[str]] = {}
    for error in job["errors"]:
        rows.setdefault(error["row"], set()).add(error["field"])
    return rows


def variant(db: Session, sku: str) -> ProductVariant | None:
    db.expire_all()
    return db.scalar(select(ProductVariant).where(ProductVariant.sku == sku))


def product(db: Session, slug: str) -> Product | None:
    db.expire_all()
    return db.scalar(select(Product).where(Product.slug == slug))


def count(db: Session, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def catalog(client: TestClient, admin_auth: dict) -> dict:
    h = admin_auth["headers"]
    phones = client.post(
        f"{STAFF}/categories", json={"name": "Phones", "slug": "phones"}, headers=h
    )
    hidden = client.post(
        f"{STAFF}/categories",
        json={"name": "Old stock", "slug": "old-stock", "is_active": False},
        headers=h,
    )
    samsung = client.post(
        f"{STAFF}/brands",
        json={"name": "Samsung", "slug": "samsung", "category_ids": [phones.json()["id"]]},
        headers=h,
    )
    assert {phones.status_code, hidden.status_code, samsung.status_code} == {201}
    existing = post_product(
        client,
        json={
            "name": "Galaxy S24",
            "slug": "galaxy-s24",
            "category_id": phones.json()["id"],
            "description": "Original description",
        },
        headers=h,
    ).json()
    force_status(existing["id"])  # active without images (the guard has its own tests)
    created = client.post(
        f"{STAFF}/products/{existing['id']}/variants",
        json={
            "sku": "GS24-128",
            "name": "128 GB",
            "price": 1000,
            "compare_at_price": 1200,
            "attributes": {"colour": "Black", "storage": "128 GB"},
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    other = post_product(
        client,
        json={"name": "Pixel 9", "slug": "pixel-9", "category_id": phones.json()["id"]},
        headers=h,
    ).json()
    client.post(
        f"{STAFF}/products/{other['id']}/variants",
        json={"sku": "PX9-128", "name": "128 GB", "price": 900},
        headers=h,
    )
    # SC-05: imports update existing products only, so the products the tests import into
    # exist first, added by a seller (drafts without variants).
    for slug, name in (
        ("galaxy-a54", "Galaxy A54"),
        ("dup", "Dup"),
        ("stocked", "Stocked"),
        ("xlsx-phone", "XLSX phone"),
        ("round-trip", "Round trip"),
        ("errors", "Errors"),
        ("audited", "Audited"),
        ("np", "NP"),
        ("tx-one", "Tx one"),
        ("tx-two", "Tx two"),
    ):
        made = post_product(
            client,
            json={"name": name, "slug": slug, "category_id": phones.json()["id"]},
            headers=h,
        )
        assert made.status_code == 201, made.text
    return {
        "headers": h,
        "product_id": existing["id"],
        "phones_id": phones.json()["id"],
        "hidden_id": hidden.json()["id"],
    }


# ---- TC-15: valid and invalid rows -----------------------------------------------------------
def test_valid_rows_are_imported_and_invalid_rows_reported_by_row_and_column(client, db, catalog):
    data = csv_file(
        [
            [
                "A54-128",
                "galaxy-a54",
                "Galaxy A54",
                "phones",
                "samsung",
                "128 GB",
                "450000",
                "",
                "",
                "Blue",
            ],
            ["A54-256", "galaxy-a54", "Galaxy A54", "phones", "", "256 GB", "520000", "", "", ""],
            ["BAD-CAT", "nokia-1", "Nokia 1", "no-such-category", "", "Std", "50000", "", "", ""],
            ["BAD-PRICE", "nokia-2", "Nokia 2", "phones", "", "Std", "50,000", "", "", ""],
            ["BAD-BRAND", "nokia-3", "Nokia 3", "phones", "nokia", "Std", "50000", "", "", ""],
        ]
    )
    res = post(client, catalog["headers"], data)
    assert res.status_code == 201, res.text
    job = res.json()
    assert (job["status"], job["total_rows"], job["imported_rows"], job["error_rows"]) == (
        "completed",
        5,
        2,
        3,
    )
    # Rows 4 and 6 also name products that do not exist (SC-05); row 5 fails its cells first.
    assert by_row(job) == {
        4: {"category_slug", "product_slug"},
        5: {"price"},
        6: {"brand_slug", "product_slug"},
    }
    assert job["errors_truncated"] is False and job["file_format"] == "csv"
    assert job["filename"] == "catalogue.csv" and job["finished_at"] is not None

    created = product(db, "galaxy-a54")
    assert created is not None and created.status == "draft" and created.brand_id is not None
    assert sorted(v.sku for v in created.variants) == ["A54-128", "A54-256"]
    assert variant(db, "A54-128").attributes == {"colour": "Blue"}
    assert product(db, "nokia-1") is None and product(db, "nokia-2") is None
    assert client.get(f"{IMPORTS}/{job['id']}", headers=catalog["headers"]).json() == job


def test_existing_skus_are_updated_and_new_skus_created_with_blank_cells_kept(client, db, catalog):
    data = csv_file(
        [
            [
                "GS24-128",
                "galaxy-s24",
                "Galaxy S24",
                "phones",
                "samsung",
                "128 GB",
                "990",
                "",
                "New text",
                "Blue",
            ],
            ["GS24-256", "galaxy-s24", "Galaxy S24", "phones", "", "256 GB", "1300", "", "", ""],
        ]
    )
    job = post(client, catalog["headers"], data).json()
    assert (job["status"], job["imported_rows"], job["error_rows"]) == ("completed", 2, 0)

    updated = variant(db, "GS24-128")
    assert updated is not None
    assert (updated.price, updated.compare_at_price) == (990, 1200)  # blank keeps 1200
    assert updated.attributes == {"colour": "Blue", "storage": "128 GB"}  # merged
    s24 = product(db, "galaxy-s24")
    assert s24 is not None and s24.description == "New text" and s24.status == "active"
    assert sorted(v.sku for v in s24.variants) == ["GS24-128", "GS24-256"]
    price_audit = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.variant_update",
            AuditRecord.entity_id == str(updated.id),
        )
    ).one()
    assert price_audit.change_summary["changes"]["price"] == {"from": 1000, "to": 990}


def test_reimporting_the_same_file_changes_nothing_and_counts_rows_as_imported(client, db, catalog):
    data = csv_file(
        [["GS24-128", "galaxy-s24", "Galaxy S24", "phones", "", "128 GB", "1000", "", "", ""]]
    )
    first = post(client, catalog["headers"], data).json()
    audits_before = count(db, AuditRecord)
    second = post(client, catalog["headers"], data).json()
    assert first["imported_rows"] == second["imported_rows"] == 1
    assert count(db, AuditRecord) == audits_before + 1  # only the catalog.import record


def test_a_sku_cannot_move_to_another_product(client, db, catalog):
    data = csv_file(
        [["PX9-128", "galaxy-s24", "Galaxy S24", "phones", "", "128 GB", "1", "", "", ""]]
    )
    job = post(client, catalog["headers"], data).json()
    assert job["imported_rows"] == 0 and by_row(job) == {2: {"product_slug"}}
    assert "pixel-9" in job["errors"][0]["message"]
    assert variant(db, "PX9-128").price == 900


def test_duplicate_skus_in_one_file_are_refused_on_every_row(client, db, catalog):
    data = csv_file(
        [
            ["DUP-1", "dup", "Dup", "phones", "", "A", "1", "", "", ""],
            ["OK-1", "dup", "Dup", "phones", "", "B", "2", "", "", ""],
            ["DUP-1", "dup", "Dup", "phones", "", "C", "3", "", "", ""],
        ]
    )
    job = post(client, catalog["headers"], data).json()
    assert by_row(job) == {2: {"sku"}, 4: {"sku"}}
    assert job["imported_rows"] == 1 and variant(db, "DUP-1") is None
    assert variant(db, "OK-1") is not None


def test_conflicting_product_rows_are_all_refused(client, db, catalog):
    data = csv_file(
        [
            ["C-1", "conflict", "Name one", "phones", "", "A", "1", "", "", ""],
            ["C-2", "conflict", "Name two", "phones", "", "B", "2", "", "", ""],
        ]
    )
    job = post(client, catalog["headers"], data).json()
    assert by_row(job) == {2: {"product_name"}, 3: {"product_name"}}
    assert product(db, "conflict") is None


def test_hidden_categories_and_brands_are_refused_for_new_assignments(client, db, catalog):
    # Category hierarchy (2026-11-16): no new product, and no product moved, into a hidden
    # category (inactive, or under an inactive main category) or an inactive brand.
    h = catalog["headers"]
    retired = client.post(
        f"{STAFF}/brands",
        json={
            "name": "Retired",
            "slug": "retired",
            "is_active": False,
            "category_ids": [catalog["hidden_id"]],
        },
        headers=h,
    )
    under_hidden = client.post(
        f"{STAFF}/categories",
        json={"name": "Clearance", "slug": "clearance", "parent_id": catalog["hidden_id"]},
        headers=h,
    )
    assert {retired.status_code, under_hidden.status_code} == {201}
    data = csv_file(
        [
            ["OLD-1", "old-phone", "Old phone", "old-stock", "", "Std", "10", "", "", ""],
            ["CLR-1", "clearance-phone", "Clearance phone", "clearance", "", "Std", "10"]
            + ["", "", ""],
            ["RET-1", "retired-phone", "Retired phone", "phones", "retired", "Std", "10"]
            + ["", "", ""],
            # Moving an existing product into a hidden category is a new assignment too.
            ["GS24-128", "galaxy-s24", "Galaxy S24", "old-stock", "", "128 GB", "1000"]
            + ["", "", ""],
        ]
    )
    job = post(client, h, data).json()
    assert job["imported_rows"] == 0
    assert by_row(job) == {
        2: {"category_slug", "product_slug"},
        3: {"category_slug", "product_slug"},
        4: {"brand_slug", "product_slug"},
        5: {"category_slug"},
    }
    assert product(db, "old-phone") is None and product(db, "retired-phone") is None
    assert product(db, "galaxy-s24").category_id == uuid.UUID(catalog["phones_id"])


def test_a_product_keeps_a_category_hidden_after_it_was_assigned(client, db, catalog):
    h = catalog["headers"]
    path = f"{STAFF}/categories/{catalog['phones_id']}"
    res = client.patch(path, json={"is_active": False}, headers=h)
    assert res.status_code == 200
    row = ["GS24-128", "galaxy-s24", "Galaxy S24", "phones", "", "128 GB", "900", "", "New", ""]
    job = post(client, h, csv_file([row])).json()
    assert job["imported_rows"] == 1 and job["errors"] == []
    assert product(db, "galaxy-s24").description == "New"


def test_opening_stock_records_a_receipt_for_new_skus_only(client, db, catalog):
    headers = HEADERS + ["opening_stock"]
    data = csv_file(
        [
            ["NEW-STOCK", "stocked", "Stocked", "phones", "", "Std", "10", "", "", "", "7"],
            [
                "GS24-128",
                "galaxy-s24",
                "Galaxy S24",
                "phones",
                "",
                "128 GB",
                "1000",
                "",
                "",
                "",
                "3",
            ],
        ],
        headers,
    )
    job = post(client, catalog["headers"], data).json()
    assert job["imported_rows"] == 1 and by_row(job) == {3: {"opening_stock"}}
    created = variant(db, "NEW-STOCK")
    assert created is not None
    balance = db.scalar(select(InventoryBalance).where(InventoryBalance.variant_id == created.id))
    assert balance is not None and balance.on_hand == 7
    movement = db.scalars(select(StockMovement).where(StockMovement.variant_id == created.id)).one()
    assert (movement.reason, movement.quantity_delta) == ("receipt", 7)
    assert movement.source_key.endswith(f"import:{job['id']}:NEW-STOCK")


def test_rows_for_unknown_products_are_refused_and_create_nothing(client, db, catalog):
    # SC-05 (moderation only): administrators never create products, not even by import. A row
    # naming no existing product is refused on product_slug; the other rows still apply.
    data = csv_file(
        [
            ["NEW-1", "brand-new-sofa", "Brand new sofa", "phones", "", "Std", "10", "", "", ""],
            ["GS24-512", "galaxy-s24", "Galaxy S24", "phones", "", "512 GB", "1500", "", "", ""],
        ]
    )
    job = post(client, catalog["headers"], data).json()
    assert (job["status"], job["imported_rows"]) == ("completed", 1)
    assert by_row(job) == {2: {"product_slug"}}
    assert "sellers add them to their own store" in job["errors"][0]["message"]
    assert product(db, "brand-new-sofa") is None and variant(db, "NEW-1") is None
    added = variant(db, "GS24-512")  # a new SKU on an existing product is an update
    assert added is not None and str(added.product_id) == catalog["product_id"]


# ---- XLSX, formulas, injection ---------------------------------------------------------------
def test_xlsx_uploads_use_native_numbers_and_refuse_formulas(client, db, catalog):
    data = xlsx_file(
        [
            ["X-1", "xlsx-phone", "XLSX phone", "phones", None, "Std", 15000, None, None, "Red"],
            [
                "X-2",
                "xlsx-phone",
                "XLSX phone",
                "phones",
                None,
                "Pro",
                "=SUM(1,2)",
                None,
                None,
                None,
            ],
            ["X-3", "xlsx-phone", '=HYPERLINK("x")', "phones", None, "Max", 1, None, None, None],
            ["X-4", "xlsx-phone", "XLSX phone", "phones", None, "Lite", 99.5, None, None, None],
        ]
    )
    res = post(client, catalog["headers"], data, name="Catalogue.XLSX")
    job = res.json()
    assert res.status_code == 201 and job["file_format"] == "xlsx"
    assert by_row(job) == {3: {"price"}, 4: {"product_name"}, 5: {"price"}}
    assert job["imported_rows"] == 1 and variant(db, "X-1").price == 15000
    assert "Formulas" in next(e for e in job["errors"] if e["row"] == 3)["message"]


def test_injection_like_csv_text_is_refused_and_never_echoed(client, db, catalog):
    payload = "=cmd|' /C calc'!A0"
    data = csv_file([["INJ-1", "inj", payload, "phones", "", "Std", "1", "", "", ""]])
    res = post(client, catalog["headers"], data)
    assert by_row(res.json()) == {2: {"product_name"}}
    assert "calc" not in res.text and product(db, "inj") is None


# ---- templates -------------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_templates_download_with_safe_headers(client, catalog, fmt):
    res = client.get(f"{IMPORTS}/template", params={"format": fmt}, headers=catalog["headers"])
    assert res.status_code == 200
    expected_type = "text/csv; charset=utf-8" if fmt == "csv" else XLSX_CONTENT_TYPE
    assert res.headers["content-type"] == expected_type
    assert res.headers["content-disposition"] == (
        f'attachment; filename="catalogue-import-template.{fmt}"'
    )
    assert res.headers["x-content-type-options"] == "nosniff"


def test_an_unknown_template_format_is_refused(client, catalog):
    res = client.get(f"{IMPORTS}/template", params={"format": "xls"}, headers=catalog["headers"])
    assert res.status_code == 422
    assert client.get(f"{IMPORTS}/template", headers=catalog["headers"]).status_code == 422


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_the_untouched_template_imports_nothing(client, db, catalog, fmt):
    template = client.get(f"{IMPORTS}/template", params={"format": fmt}, headers=catalog["headers"])
    before = count(db, ProductVariant)
    job = post(client, catalog["headers"], template.content, name=f"template.{fmt}").json()
    assert job["status"] == "failed" and job["total_rows"] == 0
    assert job["errors"] == [
        {"row": None, "field": None, "message": "The file has no data rows below the header."}
    ]
    assert count(db, ProductVariant) == before


def _filled_row() -> dict[str, object]:
    return {
        "sku": "RT-1",
        "product_slug": "round-trip",
        "product_name": "Round trip",
        "category_slug": "phones",
        "variant_name": "Std",
        "price": 1234,
        "attr:colour": "Green",
        "spec:display": "6.1 inch",
    }


def test_the_csv_template_round_trips(client, db, catalog):
    template = client.get(
        f"{IMPORTS}/template", params={"format": "csv"}, headers=catalog["headers"]
    )
    text = template.content.decode("utf-8-sig")
    headers = next(csv.reader(io.StringIO(text)))
    assert headers == template_headers()
    filled = _filled_row()
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerow([filled.get(h, "") for h in headers])
    job = post(client, catalog["headers"], (text + buffer.getvalue()).encode("utf-8")).json()
    assert (job["status"], job["imported_rows"], job["error_rows"]) == ("completed", 1, 0)
    assert variant(db, "RT-1").attributes == {"colour": "Green"}
    assert product(db, "round-trip").specifications == {"display": "6.1 inch"}


def test_the_xlsx_template_round_trips(client, db, catalog):
    template = client.get(
        f"{IMPORTS}/template", params={"format": "xlsx"}, headers=catalog["headers"]
    )
    workbook = load_workbook(io.BytesIO(template.content))
    sheet = workbook.worksheets[0]
    headers = [cell.value for cell in sheet[1]]
    filled = _filled_row()
    sheet.append([filled.get(h) for h in headers])
    buffer = io.BytesIO()
    workbook.save(buffer)
    job = post(client, catalog["headers"], buffer.getvalue(), name="filled.xlsx").json()
    assert (job["status"], job["imported_rows"], job["error_rows"]) == ("completed", 1, 0)
    assert variant(db, "RT-1").price == 1234


# ---- unusable files --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("catalogue.csv", b"", "The file is empty."),
        ("catalogue.txt", b"sku\nA", "Upload a .csv or .xlsx file."),
        ("catalogue", b"sku\nA", "Upload a .csv or .xlsx file."),
        ("catalogue.xls", b"\xd0\xcf\x11\xe0", "Upload a .csv or .xlsx file."),
    ],
)
def test_empty_or_unsupported_uploads_get_422_and_create_no_job(
    client, db, catalog, name, data, message
):
    res = post(client, catalog["headers"], data, name=name)
    assert res.status_code == 422 and code(res) == "validation_error"
    assert res.json()["error"]["details"][0] == {
        "type": "value_error",
        "loc": ["body", "file"],
        "msg": message,
    }
    assert count(db, ImportJob) == 0


def test_a_missing_file_is_a_validation_error(client, db, catalog):
    res = client.post(IMPORTS, headers=catalog["headers"])
    assert res.status_code == 422 and res.json()["error"]["details"][0]["loc"] == ["body", "file"]
    assert count(db, ImportJob) == 0


def test_files_over_10_mb_get_413_and_create_no_job(client, db, catalog):
    big = b"sku\n" + b"A" * (10 * 1024 * 1024)
    res = post(client, catalog["headers"], big)
    assert res.status_code == 413 and code(res) == "file_too_large"
    far = post(client, catalog["headers"], b"x" * (11 * 1024 * 1024))
    assert far.status_code == 413
    assert count(db, ImportJob) == 0


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("bad.csv", "sku,naïve\n".encode("latin-1"), "not valid UTF-8"),
        ("bad.csv", b"sku,colour\nA,B\n", "Unknown column header."),
        ("bad.xlsx", b"PK\x03\x04garbage", "not a valid .xlsx"),
        ("bad.xlsx", b"sku,price\n1,2\n", "not a valid .xlsx"),
        ("bad.csv", b"PK\x03\x04garbage", "not a CSV"),
    ],
    ids=["latin-1", "unknown-header", "damaged-xlsx", "csv-named-xlsx", "zip-named-csv"],
)
def test_unusable_files_end_as_failed_jobs_without_changes(
    client, db, catalog, name, data, message
):
    before = count(db, ProductVariant)
    res = post(client, catalog["headers"], data, name=name)
    job = res.json()
    assert res.status_code == 201 and job["status"] == "failed"
    assert (job["total_rows"], job["imported_rows"], job["error_rows"]) == (0, 0, 0)
    assert len(job["errors"]) == 1 and message in job["errors"][0]["message"]
    assert job["finished_at"] is not None
    assert count(db, ProductVariant) == before


def test_more_than_5000_rows_fails_the_job(client, db, catalog):
    rows = [[f"R-{i}", "many", "Many", "phones", "", "Std", "1", "", "", ""] for i in range(5001)]
    job = post(client, catalog["headers"], csv_file(rows)).json()
    assert job["status"] == "failed"
    assert job["errors"][0]["message"] == "The file has more than 5000 data rows."
    assert product(db, "many") is None


def test_more_than_1000_errors_are_capped_but_every_invalid_row_counted(client, db, catalog):
    rows = [
        [f"E-{i}", "errors", "Errors", "phones", "", "Std", "bad", "", "", ""] for i in range(1100)
    ]
    rows.append(["E-OK", "errors", "Errors", "phones", "", "Std", "5", "", "", ""])
    job = post(client, catalog["headers"], csv_file(rows)).json()
    assert (job["total_rows"], job["imported_rows"], job["error_rows"]) == (1101, 1, 1100)
    assert len(job["errors"]) == 1000 and job["errors_truncated"] is True
    assert [e["row"] for e in job["errors"]] == list(range(2, 1002))  # ordered by row
    assert variant(db, "E-OK") is not None


def test_a_file_where_every_row_is_invalid_completes_with_no_changes(client, db, catalog):
    before = (count(db, Product), count(db, ProductVariant))
    data = csv_file([["N-1", "none", "None", "nope", "", "Std", "1", "", "", ""]])
    job = post(client, catalog["headers"], data).json()
    assert (job["status"], job["imported_rows"], job["error_rows"]) == ("completed", 0, 1)
    assert (count(db, Product), count(db, ProductVariant)) == before


# ---- transactions ----------------------------------------------------------------------------
def test_an_unexpected_failure_rolls_back_every_change_and_fails_the_job(
    client, db, catalog, monkeypatch
):
    real = catalog_import.apply_variant_create
    calls = {"n": 0}

    def fail_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated database failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(catalog_import, "apply_variant_create", fail_second)
    before = (count(db, Product), count(db, ProductVariant), count(db, AuditRecord))
    data = csv_file(
        [
            ["T-1", "tx-one", "Tx one", "phones", "", "Std", "1", "", "", ""],
            ["T-2", "tx-two", "Tx two", "phones", "", "Std", "2", "", "", ""],
            ["GS24-128", "galaxy-s24", "Galaxy S24", "phones", "", "128 GB", "1", "", "", ""],
        ]
    )
    with pytest.raises(RuntimeError):
        post(client, catalog["headers"], data)
    db.expire_all()
    assert variant(db, "T-1") is None  # the first row's new SKU was rolled back too
    assert variant(db, "GS24-128").price == 1000
    job = db.scalars(select(ImportJob)).one()
    assert job.status == "failed" and job.finished_at is not None
    assert (job.total_rows, job.imported_rows, job.error_rows) == (3, 0, 0)
    assert job.errors == [{"row": None, "field": None, "message": UNEXPECTED_FAILURE}]
    after = (count(db, Product), count(db, ProductVariant), count(db, AuditRecord))
    assert after == (before[0], before[1], before[2] + 1)  # only the failed-import audit


def test_an_unexpected_failure_answers_500_without_internal_detail(catalog, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(catalog_import, "apply_variant_create", boom)
    data = csv_file([["T-9", "galaxy-s24", "Galaxy S24", "phones", "", "Std", "1", "", "", ""]])
    with TestClient(app, raise_server_exceptions=False) as plain:
        res = post(plain, catalog["headers"], data)
    assert res.status_code == 500 and code(res) == "internal_error"
    assert "secret" not in res.text


def test_the_job_is_audited_and_timestamps_are_ordered(client, db, catalog, admin_auth):
    data = csv_file([["AU-1", "audited", "Audited", "phones", "", "Std", "1", "", "", ""]])
    job = post(client, catalog["headers"], data).json()
    stored = db.get(ImportJob, uuid.UUID(job["id"]))
    assert stored is not None and stored.finished_at >= stored.created_at
    assert stored.created_by_user_id == admin_auth["user"].id
    record = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.import", AuditRecord.entity_id == job["id"]
        )
    ).one()
    assert (
        record.change_summary["imported_rows"] == 1 and record.change_summary["status"] == "success"
    )
    assert "audited" not in str(record.change_summary)  # no file contents in the audit


# ---- authorization and job access -----------------------------------------------------------


@pytest.mark.parametrize("who", ["customer_auth"])
def test_other_roles_cannot_upload_read_jobs_or_download_templates(
    client, db, catalog, who, request
):
    job = post(
        client,
        catalog["headers"],
        csv_file([["F-1", "f", "F", "phones", "", "S", "1", "", "", ""]]),
    ).json()
    h = request.getfixturevalue(who)["headers"]
    attempts = [
        post(client, h, csv_file([["F-2", "f2", "F", "phones", "", "S", "1", "", "", ""]])),
        client.get(f"{IMPORTS}/{job['id']}", headers=h),
        client.get(f"{IMPORTS}/template", params={"format": "csv"}, headers=h),
    ]
    assert [r.status_code for r in attempts] == [403] * 3
    assert {code(r) for r in attempts} == {"permission_denied"}
    assert count(db, ImportJob) == 1 and variant(db, "F-2") is None


def test_anonymous_requests_are_unauthorized(client, db):
    attempts = [
        client.post(IMPORTS, files={"file": ("a.csv", b"sku\nA", "text/csv")}),
        client.get(f"{IMPORTS}/{uuid.uuid4()}"),
        client.get(f"{IMPORTS}/template", params={"format": "csv"}),
    ]
    assert [r.status_code for r in attempts] == [401] * 3
    assert count(db, ImportJob) == 0


def test_unknown_or_malformed_job_ids(client, catalog):
    unknown = client.get(f"{IMPORTS}/{uuid.uuid4()}", headers=catalog["headers"])
    assert unknown.status_code == 404 and code(unknown) == "import_job_not_found"
    malformed = client.get(f"{IMPORTS}/not-a-uuid", headers=catalog["headers"])
    assert malformed.status_code == 422


def test_opening_stock_needs_inventory_adjust(client, db, catalog, monkeypatch):
    monkeypatch.setattr(catalog_import, "has_permission", lambda user, permission: False)
    headers = HEADERS + ["opening_stock"]
    data = csv_file([["NP-1", "np", "NP", "phones", "", "Std", "1", "", "", "", "4"]], headers)
    job = post(client, catalog["headers"], data).json()
    assert by_row(job) == {2: {"opening_stock"}}
    assert "inventory:adjust" in job["errors"][0]["message"]


# ---- OpenAPI ---------------------------------------------------------------------------------
def test_openapi_documents_the_import_routes():
    app.openapi_schema = None
    spec = app.openapi()
    upload = spec["paths"]["/api/v1/staff/imports"]["post"]
    assert {"201", "401", "403", "413", "422"} <= set(upload["responses"])
    assert "multipart/form-data" in upload["requestBody"]["content"]
    job = spec["paths"]["/api/v1/staff/imports/{job_id}"]["get"]
    assert {"200", "401", "403", "404", "422"} <= set(job["responses"])
    template = spec["paths"]["/api/v1/staff/imports/template"]["get"]
    assert {p["name"] for p in template["parameters"]} == {"format"}
    example = spec["components"]["schemas"]["ImportJobResponse"]["examples"][0]
    assert set(example) == set(spec["components"]["schemas"]["ImportJobResponse"]["properties"])
