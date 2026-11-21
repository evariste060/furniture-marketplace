"""Catalogue import from CSV or XLSX (module 8; 'catalog:manage'; TC-15).

One data row is one SKU (variant) plus the product it belongs to (product_slug). The column
schema is in app.schemas.catalog_import; file reading is in app.services.import_files.

Order of work for one upload:
1. The job row is created as 'processing' and committed on its own, so it exists whatever
   happens next.
2. The file is read. A file that cannot be used (encoding, headers, too many rows, damaged
   workbook) ends the job as 'failed' with that error; nothing else happens.
3. Every row is checked before any change: cell types, field rules (the module 6 schemas),
   duplicate SKUs in the file, and product columns that disagree between rows of one product.
4. In one transaction, under the product-change advisory lock: the database rules are checked
   (category and brand slugs exist, an existing SKU belongs to the named product, opening
   stock only for new SKUs), then every valid row is applied through the same functions the
   staff routes use (module 6), each change with its own audit record, and the job is finished
   as 'completed' with one 'catalog.import' audit record. All of it commits together.
5. If anything unexpected fails in step 3 or 4, the transaction is rolled back (no catalogue
   change survives) and the job is marked 'failed' in a new transaction before the error
   propagates (500). Only if the database itself is unreachable can the job stay 'processing'.

Rules:
- Matching is by SKU, ignoring case (2026-10-26): an existing SKU is updated (its stored
  spelling is kept), a new SKU is created on its existing product. A SKU cannot move to another
  product.
- Moderation only (SC-05, ADR-014 phase 2): the import updates existing products of any store
  and never creates one. A row whose product_slug matches no product is refused (product_slug):
  sellers add new products to their own store.
- A blank cell keeps the existing value (or the default for something new); values cannot be
  cleared by import. attr:<key> and spec:<key> values are merged into the existing attributes
  and specifications.
- Rows of one product may leave product columns blank but must not disagree; every row of a
  product with a disagreement is refused, so row order never decides a value.
- A SKU that appears more than once in a file is refused on every row where it appears.
- As in the staff API (category hierarchy, 2026-11-16), a row cannot put a product in a hidden
  category (inactive, or under an inactive main category) or give it an inactive brand. A row
  that keeps a product's current category and brand is accepted even if they were hidden later.
- opening_stock (new SKUs only) records a 'receipt' stock movement; it needs 'inventory:adjust'.
- Row errors are stored up to IMPORT_MAX_STORED_ERRORS (ordered by row and column); error_rows
  counts every invalid row; errors_truncated says when the list was cut.
- Error messages never echo submitted values.
"""

import logging
import math
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.request_context import RequestContext
from app.core.roles import Permission, has_permission
from app.db.transaction import atomic
from app.models import Brand, Category, ImportJob, Product, ProductVariant
from app.models.catalog import IMPORT_MAX_STORED_ERRORS
from app.models.identity import User
from app.repositories.category_tree import category_visible
from app.schemas.catalog_import import (
    ATTRIBUTE_PREFIX,
    COLUMNS_BY_NAME,
    IMPORT_COLUMNS,
    PRODUCT_FIELDS,
    SPECIFICATION_PREFIX,
    ImportFormat,
    ImportRow,
)
from app.schemas.product_admin import (
    ProductUpdateRequest,
    VariantCreateRequest,
    VariantUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.catalog_admin import _lock
from app.services.import_files import (
    FORMULA,
    DataRow,
    FileProblem,
    ParsedFile,
    is_date_value,
    read_csv,
    read_xlsx,
)
from app.services.inventory import adjust_stock
from app.services.product_admin import (
    BRAND_HIDDEN,
    CATEGORY_HIDDEN,
    PRODUCT_CHANGE_LOCK_KEY,
    apply_product_update,
    apply_variant_create,
    apply_variant_update,
    has_publishable_image,
)

logger = logging.getLogger("app.catalog_import")

IMPORT_JOB_NOT_FOUND = "Import job not found."
REQUIRED = "This column is required."
FORMULA_REFUSED = "Formulas are not accepted; enter the value itself."
DATE_REFUSED = "Dates are not accepted in this column."
INJECTION_REFUSED = "Text may not start with =, +, @ or - (a list item may start with '- ')."
WHOLE_NUMBER = "Enter a whole number of 0 or more, digits only (no separators or decimals)."
BOOLEAN = "Enter true or false (yes/no and 1/0 are also accepted)."
TEXT_EXPECTED = "Enter text here, not TRUE/FALSE."
EXTRA_VALUES = "This row has values to the right of the last column header."
UNEXPECTED_FAILURE = (
    "The import stopped because of an unexpected error. No catalogue changes were made; try "
    "again or contact an administrator."
)
FRIENDLY_MESSAGES = {  # pydantic error type per column -> message
    ("sku", "string_pattern_mismatch"): "A SKU may not contain spaces or '/'.",
    ("product_slug", "string_pattern_mismatch"): (
        "Use lowercase letters and digits, words joined by single hyphens."
    ),
    ("category_slug", "string_pattern_mismatch"): (
        "Use lowercase letters and digits, words joined by single hyphens."
    ),
    ("brand_slug", "string_pattern_mismatch"): (
        "Use lowercase letters and digits, words joined by single hyphens."
    ),
    ("product_status", "literal_error"): "Use draft, active, hidden or archived.",
}
TRUE_WORDS = frozenset({"true", "yes", "1"})
FALSE_WORDS = frozenset({"false", "no", "0"})
DIGITS = re.compile(r"\d{1,15}")
COLUMN_ORDER = {column.name: index for index, column in enumerate(IMPORT_COLUMNS)}


@dataclass(frozen=True)
class RowError:
    row: int | None
    field: str | None
    message: str

    def sort_key(self) -> tuple[int, int, str, str]:
        return (
            self.row or 0,
            COLUMN_ORDER.get(self.field or "", len(COLUMN_ORDER)),
            self.field or "",
            self.message,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "field": self.field, "message": self.message}


@dataclass
class CheckedRow:
    number: int
    values: ImportRow


# ---- cell cleaning ---------------------------------------------------------------------------
class CellError(Exception):
    pass


def _clean_text(value: Any) -> str | None:
    if value is FORMULA:
        raise CellError(FORMULA_REFUSED)
    if value is None:
        return None
    if isinstance(value, bool):
        raise CellError(TEXT_EXPECTED)
    if is_date_value(value):
        raise CellError(DATE_REFUSED)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CellError("Enter a finite value.")
        return str(int(value)) if value.is_integer() else repr(value)
    text = str(value).strip()
    if not text:
        return None
    if text[0] in "=+@" or (text[0] == "-" and not text.startswith("- ")):
        raise CellError(INJECTION_REFUSED)
    return text


def _clean_integer(value: Any) -> int | None:
    if value is FORMULA:
        raise CellError(FORMULA_REFUSED)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or is_date_value(value):
        raise CellError(WHOLE_NUMBER)
    if isinstance(value, int):
        if value < 0:
            raise CellError(WHOLE_NUMBER)
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer() or value < 0:
            raise CellError(WHOLE_NUMBER)
        return int(value)
    text = str(value).strip()
    if not DIGITS.fullmatch(text):
        raise CellError(WHOLE_NUMBER)
    return int(text)


def _clean_boolean(value: Any) -> bool | None:
    if value is FORMULA:
        raise CellError(FORMULA_REFUSED)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    word = str(value).strip().lower() if isinstance(value, str) else ""
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise CellError(BOOLEAN)


CLEANERS = {"text": _clean_text, "integer": _clean_integer, "boolean": _clean_boolean}


def _dynamic_key(header: str) -> tuple[str, str]:
    prefix, key = header.split(":", 1)
    return ("attributes" if prefix + ":" == ATTRIBUTE_PREFIX else "specifications"), key


def check_row(data: DataRow) -> tuple[ImportRow | None, list[RowError]]:
    """Clean and validate one row without the database."""
    errors: list[RowError] = []
    values: dict[str, Any] = {"attributes": {}, "specifications": {}}
    if data.extra_values:
        errors.append(RowError(data.number, None, EXTRA_VALUES))
    for header, raw in data.cells.items():
        column = COLUMNS_BY_NAME.get(header)
        cleaned: str | int | bool | None
        try:
            if column is None:  # attr:<key> or spec:<key>
                cleaned = _clean_text(raw)
                if cleaned is not None:
                    target, key = _dynamic_key(header)
                    values[target][key] = cleaned
                continue
            cleaned = CLEANERS[column.kind](raw)
        except CellError as exc:
            errors.append(RowError(data.number, header, str(exc)))
            continue
        if cleaned is None and column.required:
            errors.append(RowError(data.number, header, REQUIRED))
            continue
        if cleaned is not None:
            values[header] = cleaned
    if errors:
        return None, errors
    try:
        return ImportRow.model_validate(values), []
    except ValidationError as exc:
        for item in exc.errors(include_input=False):
            loc = item["loc"]
            field: str | None
            if loc and loc[0] in ("attributes", "specifications") and len(loc) > 1:
                prefix = ATTRIBUTE_PREFIX if loc[0] == "attributes" else SPECIFICATION_PREFIX
                field = f"{prefix}{loc[1]}"
            else:
                field = str(loc[0]) if loc else None
            message = FRIENDLY_MESSAGES.get((field or "", item["type"]), item["msg"])
            errors.append(RowError(data.number, field, message))
        return None, errors


def _rows_text(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:10])
    return shown + (f" and {len(numbers) - 10} more" if len(numbers) > 10 else "")


def check_file_rows(parsed: ParsedFile) -> tuple[list[CheckedRow], list[RowError]]:
    """Row checks that need no database: cells, field rules, duplicate SKUs, product groups."""
    errors: list[RowError] = []
    checked: list[CheckedRow] = []
    sku_rows: dict[str, list[int]] = defaultdict(list)
    for data in parsed.rows:
        try:
            sku = _clean_text(data.cells.get("sku"))
        except CellError:
            sku = None
        if sku is not None:
            sku_rows[sku.lower()].append(data.number)
        values, row_errors = check_row(data)
        errors.extend(row_errors)
        if values is not None:
            checked.append(CheckedRow(data.number, values))

    duplicated = {sku: rows for sku, rows in sku_rows.items() if len(rows) > 1}
    for rows in duplicated.values():
        for number in rows:
            errors.append(
                RowError(
                    number,
                    "sku",
                    f"This SKU appears in rows {_rows_text(rows)}; each SKU may appear once "
                    "(ignoring case).",
                )
            )
    checked = [row for row in checked if row.values.sku.lower() not in duplicated]

    refused: set[int] = set()
    for group in _groups(checked).values():
        rows = [row.number for row in group]
        for field in _product_columns(group):
            if len({_product_value(row.values, field) for row in group} - {None}) > 1:
                for number in rows:
                    errors.append(
                        RowError(
                            number,
                            field,
                            f"Rows {_rows_text(rows)} of this product disagree on this column; "
                            "give them the same value or leave it blank.",
                        )
                    )
                    refused.add(number)
    return [row for row in checked if row.number not in refused], errors


def _groups(rows: list[CheckedRow]) -> dict[str, list[CheckedRow]]:
    groups: dict[str, list[CheckedRow]] = {}
    for row in rows:
        groups.setdefault(row.values.product_slug, []).append(row)
    return groups


def _product_columns(group: list[CheckedRow]) -> list[str]:
    specs = sorted({key for row in group for key in row.values.specifications})
    return [f for f in PRODUCT_FIELDS if f != "product_slug"] + [
        f"{SPECIFICATION_PREFIX}{key}" for key in specs
    ]


def _product_value(values: ImportRow, field: str) -> Any:
    if field.startswith(SPECIFICATION_PREFIX):
        return values.specifications.get(field[len(SPECIFICATION_PREFIX) :])
    return getattr(values, field)


def _group_value(group: list[CheckedRow], field: str) -> Any:
    for row in group:
        value = _product_value(row.values, field)
        if value is not None:
            return value
    return None


# ---- database checks and changes -------------------------------------------------------------
@dataclass
class Lookups:
    categories: dict[str, uuid.UUID]
    brands: dict[str, uuid.UUID]
    hidden_categories: set[str]  # slugs of named categories that are hidden
    hidden_brands: set[str]  # slugs of named brands that are inactive
    variants: dict[str, ProductVariant]  # existing variants by lowercased SKU, locked
    products: dict[str, Product]  # existing products by slug, locked
    sku_owners: dict[str, str]  # existing lowercased SKU -> slug of its product


def _lookups(db: Session, rows: list[CheckedRow]) -> Lookups:
    category_slugs = {r.values.category_slug for r in rows}
    brand_slugs = {r.values.brand_slug for r in rows if r.values.brand_slug}
    skus = [r.values.sku.lower() for r in rows]
    variants = (
        db.scalars(
            select(ProductVariant).where(func.lower(ProductVariant.sku).in_(skus)).with_for_update()
        ).all()
        if skus
        else []
    )
    product_slugs = {r.values.product_slug for r in rows}
    products = (
        db.scalars(select(Product).where(Product.slug.in_(product_slugs)).with_for_update()).all()
        if product_slugs
        else []
    )
    product_slug_by_id = {p.id: p.slug for p in products}
    missing_ids = {v.product_id for v in variants} - set(product_slug_by_id)
    if missing_ids:
        owners = select(Product.id, Product.slug).where(Product.id.in_(missing_ids))
        product_slug_by_id.update({pid: slug for pid, slug in db.execute(owners)})
    categories: dict[str, uuid.UUID] = {}
    hidden_categories: set[str] = set()
    if category_slugs:
        found = select(
            Category.slug, Category.id, category_visible(Category.id).label("visible")
        ).where(Category.slug.in_(category_slugs))
        for row in db.execute(found):
            categories[row.slug] = row.id
            if not row.visible:
                hidden_categories.add(row.slug)
    brands: dict[str, uuid.UUID] = {}
    hidden_brands: set[str] = set()
    if brand_slugs:
        named = select(Brand.slug, Brand.id, Brand.is_active).where(Brand.slug.in_(brand_slugs))
        for slug, bid, active in db.execute(named):
            brands[slug] = bid
            if not active:
                hidden_brands.add(slug)
    lookups = Lookups(
        categories=categories,
        brands=brands,
        hidden_categories=hidden_categories,
        hidden_brands=hidden_brands,
        variants={v.sku.lower(): v for v in variants},
        products={p.slug: p for p in products},
        sku_owners={v.sku.lower(): product_slug_by_id[v.product_id] for v in variants},
    )
    return lookups


def check_database_rows(
    db: Session, actor: User, rows: list[CheckedRow]
) -> tuple[list[CheckedRow], list[RowError], Lookups]:
    lookups = _lookups(db, rows)
    may_adjust_stock = has_permission(actor, Permission.INVENTORY_ADJUST.value)
    errors: list[RowError] = []
    valid: list[CheckedRow] = []
    for row in rows:
        v = row.values
        row_errors: list[RowError] = []
        if v.category_slug not in lookups.categories:
            row_errors.append(RowError(row.number, "category_slug", "No category has this slug."))
        if v.brand_slug is not None and v.brand_slug not in lookups.brands:
            row_errors.append(RowError(row.number, "brand_slug", "No brand has this slug."))
        # A new assignment to a hidden category or brand is refused; keeping one is not.
        current = lookups.products.get(v.product_slug)
        if v.category_slug in lookups.hidden_categories and (
            current is None or current.category_id != lookups.categories[v.category_slug]
        ):
            row_errors.append(RowError(row.number, "category_slug", CATEGORY_HIDDEN))
        if v.brand_slug in lookups.hidden_brands and (
            current is None or current.brand_id != lookups.brands[v.brand_slug]
        ):
            row_errors.append(RowError(row.number, "brand_slug", BRAND_HIDDEN))
        if current is None:
            row_errors.append(RowError(row.number, "product_slug", NEW_PRODUCT_REFUSED))
        existing_owner = lookups.sku_owners.get(v.sku.lower())
        if existing_owner is not None and existing_owner != v.product_slug:
            row_errors.append(
                RowError(
                    row.number,
                    "product_slug",
                    f"This SKU belongs to product '{existing_owner}'; a SKU cannot move to "
                    "another product.",
                )
            )
        if v.opening_stock is not None:
            if existing_owner is not None:
                row_errors.append(
                    RowError(
                        row.number,
                        "opening_stock",
                        "Only for new SKUs; change the stock of an existing SKU with a stock "
                        "adjustment.",
                    )
                )
            elif not may_adjust_stock:
                row_errors.append(
                    RowError(
                        row.number,
                        "opening_stock",
                        "Recording opening stock requires the 'inventory:adjust' permission.",
                    )
                )
        errors.extend(row_errors)
        if not row_errors:
            valid.append(row)
    return valid, errors, lookups


NEW_PRODUCT_REFUSED = (
    "No product has this slug. Imports update existing products only: administrators do not "
    "create products, sellers add them to their own store."
)
NO_IMAGES_WARNING = (
    "The product has no images, so it was saved as {kept} instead of active. Upload images "
    "(bulk upload), then activate it."
)


def _apply_product(
    db: Session,
    actor: User,
    slug: str,
    group: list[CheckedRow],
    lookups: Lookups,
    ctx: RequestContext,
    warnings: list[RowError],
) -> Product:
    brand_slug = _group_value(group, "brand_slug")
    specifications = {
        key: value for row in group for key, value in row.values.specifications.items()
    }
    fields: dict[str, Any] = {
        "name": _group_value(group, "product_name"),
        "category_id": lookups.categories[_group_value(group, "category_slug")],
    }
    if brand_slug is not None:
        fields["brand_id"] = lookups.brands[brand_slug]
    for source, target in (
        ("model", "model"),
        ("description", "description"),
        ("warranty_text", "warranty_text"),
        ("product_status", "status"),
    ):
        value = _group_value(group, source)
        if value is not None:
            fields[target] = value
    product = lookups.products[slug]  # check_database_rows refused rows of unknown products
    # Publication guard (2026-10-26): a row asking for 'active' cannot activate a product without
    # images; it is applied with the status kept and a warning.
    if (
        fields.get("status") == "active"
        and product.status != "active"
        and not has_publishable_image(db, product.id)
    ):
        del fields["status"]
        warnings.append(
            RowError(
                group[0].number, "product_status", NO_IMAGES_WARNING.format(kept=product.status)
            )
        )
    if specifications:
        fields["specifications"] = {**product.specifications, **specifications}
    apply_product_update(db, actor, product, ProductUpdateRequest.model_validate(fields), ctx)
    return product


def _apply_variant(
    db: Session,
    actor: User,
    product: Product,
    row: CheckedRow,
    lookups: Lookups,
    job_id: uuid.UUID,
    ctx: RequestContext,
) -> None:
    v = row.values
    fields: dict[str, Any] = {"name": v.variant_name, "price": v.price}
    for source, target in (
        ("compare_at_price", "compare_at_price"),
        ("low_stock_threshold", "low_stock_threshold"),
        ("variant_active", "is_active"),
    ):
        value = getattr(v, source)
        if value is not None:
            fields[target] = value
    variant = lookups.variants.get(v.sku.lower())
    if variant is not None:
        if v.attributes:
            fields["attributes"] = {**variant.attributes, **v.attributes}
        apply_variant_update(db, actor, variant, VariantUpdateRequest.model_validate(fields), ctx)
        return
    variant = apply_variant_create(
        db,
        actor,
        product,
        VariantCreateRequest.model_validate({**fields, "sku": v.sku, "attributes": v.attributes}),
        ctx,
    )
    lookups.variants[v.sku.lower()] = variant
    if v.opening_stock:
        adjust_stock(
            db,
            variant_id=variant.id,
            quantity_delta=v.opening_stock,
            reason="receipt",
            idempotency_key=f"import:{job_id}:{v.sku}",
            actor=actor,
            ctx=ctx,
            note="Opening stock from catalogue import",
        )


# ---- the job ---------------------------------------------------------------------------------
def _finish(
    db: Session,
    job: ImportJob,
    status: str,
    total_rows: int,
    imported_rows: int,
    errors: list[RowError],
    warnings: list[RowError] | None = None,
) -> None:
    ordered = sorted(errors, key=RowError.sort_key)
    job.status = status
    job.total_rows = total_rows
    job.imported_rows = imported_rows
    # A failed job changed nothing, so no row counts as an error row; its errors say why.
    job.error_rows = 0 if status == "failed" else len({e.row for e in errors if e.row})
    job.errors = [e.as_dict() for e in ordered[:IMPORT_MAX_STORED_ERRORS]]
    job.errors_truncated = len(ordered) > IMPORT_MAX_STORED_ERRORS
    noted = sorted(warnings or [], key=RowError.sort_key)
    job.warnings = [w.as_dict() for w in noted[:IMPORT_MAX_STORED_ERRORS]]
    job.finished_at = db.scalar(select(func.clock_timestamp()))
    db.flush()


AUDIT_STATUS = {"completed": "success", "failed": "failure"}


def _audit_job(db: Session, job: ImportJob, actor: User, ctx: RequestContext) -> None:
    AuditService.log_event(
        db=db,
        action="catalog.import",
        status=AUDIT_STATUS[job.status],
        actor=actor,
        entity_type="import_job",
        entity_id=job.id,
        context=ctx,
        details={
            "file_format": job.file_format,
            "total_rows": job.total_rows,
            "imported_rows": job.imported_rows,
            "error_rows": job.error_rows,
        },
    )


def _read(file_format: ImportFormat, data: bytes) -> ParsedFile:
    return read_csv(data) if file_format == "csv" else read_xlsx(data)


# An import runs inside its request (kept synchronous on 2026-10-26: a crash rolls back every
# catalogue change). A job still 'processing' after this long belongs to a process that stopped
# mid-request; the worker marks it failed (python -m app.worker).
STALE_IMPORT_AFTER = timedelta(minutes=10)
STALE_IMPORT_FAILURE = (
    "The import stopped unexpectedly (the server restarted). No catalogue changes were made; "
    "upload the file again."
)


def fail_stale_imports(db: Session, now: datetime) -> int:
    """Mark imports still 'processing' after STALE_IMPORT_AFTER as failed, each audited."""
    with atomic(db):
        stale = list(
            db.scalars(
                select(ImportJob)
                .where(
                    ImportJob.status == "processing",
                    ImportJob.created_at < now - STALE_IMPORT_AFTER,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for job in stale:
            _finish(
                db, job, "failed", job.total_rows, 0, [RowError(None, None, STALE_IMPORT_FAILURE)]
            )
            AuditService.log_event(
                db=db,
                action="catalog.import",
                status="failure",
                actor=db.get(User, job.created_by_user_id),
                entity_type="import_job",
                entity_id=job.id,
                details={"file_format": job.file_format, "reason": "stale"},
                request_id="worker:stale_import",
            )
    if stale:
        logger.warning("Marked %d stale catalogue import(s) failed", len(stale))
    return len(stale)


class CatalogImportService:
    @staticmethod
    def run(
        db: Session,
        actor: User,
        filename: str,
        file_format: ImportFormat,
        data: bytes,
        ctx: RequestContext,
    ) -> ImportJob:
        with atomic(db):
            job = ImportJob(created_by_user_id=actor.id, filename=filename, file_format=file_format)
            db.add(job)
            db.flush()
        job_id = job.id
        total_rows = 0
        try:
            try:
                parsed = _read(file_format, data)
            except FileProblem as problem:
                with atomic(db):
                    _finish(
                        db,
                        job,
                        "failed",
                        0,
                        0,
                        [RowError(problem.row, problem.field, problem.message)],
                    )
                    _audit_job(db, job, actor, ctx)
                return job
            total_rows = len(parsed.rows)
            if total_rows == 0:
                with atomic(db):
                    _finish(
                        db,
                        job,
                        "failed",
                        0,
                        0,
                        [RowError(None, None, "The file has no data rows below the header.")],
                    )
                    _audit_job(db, job, actor, ctx)
                return job
            checked, errors = check_file_rows(parsed)
            with atomic(db):
                _lock(db, PRODUCT_CHANGE_LOCK_KEY)
                valid, db_errors, lookups = check_database_rows(db, actor, checked)
                errors.extend(db_errors)
                warnings: list[RowError] = []
                for slug, group in _groups(valid).items():
                    product = _apply_product(db, actor, slug, group, lookups, ctx, warnings)
                    for row in group:
                        _apply_variant(db, actor, product, row, lookups, job_id, ctx)
                _finish(db, job, "completed", total_rows, len(valid), errors, warnings)
                _audit_job(db, job, actor, ctx)
        except Exception:
            logger.warning("Catalogue import %s stopped unexpectedly; marking it failed", job_id)
            CatalogImportService._mark_failed(db, job_id, total_rows, actor, ctx)
            raise
        logger.info(
            "Catalogue import %s completed: %d rows, %d imported, %d with errors",
            job_id,
            job.total_rows,
            job.imported_rows,
            job.error_rows,
        )
        return job

    @staticmethod
    def _mark_failed(
        db: Session, job_id: uuid.UUID, total_rows: int, actor: User, ctx: RequestContext
    ) -> None:
        """After a rollback: record the failure on the job in a new transaction."""
        try:
            db.rollback()
            with atomic(db):
                job = db.get(ImportJob, job_id, with_for_update=True)
                if job is None or job.status != "processing":
                    return
                _finish(
                    db, job, "failed", total_rows, 0, [RowError(None, None, UNEXPECTED_FAILURE)]
                )
                _audit_job(db, job, actor, ctx)
        except Exception:
            logger.error("Catalogue import %s could not be marked failed", job_id)

    @staticmethod
    def get(db: Session, job_id: uuid.UUID) -> ImportJob:
        job = db.get(ImportJob, job_id)
        if job is None:
            raise NotFound(IMPORT_JOB_NOT_FOUND, code="import_job_not_found")
        return job
