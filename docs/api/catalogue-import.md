# Catalogue import (module 8)

Staff load and update the catalogue from a CSV or Excel (XLSX) file (PRD PR-10; QA TC-15). This page is the file and API contract for API clients and for the admin import screen.

All routes need a valid bearer session and the `catalog:manage` permission (administrator, sales). Other staff and customers get 403 `permission_denied`; requests without a token get 401.

| Route | Purpose |
| --- | --- |
| `GET /api/v1/staff/imports/template?format=csv\|xlsx` | Download the template |
| `POST /api/v1/staff/imports` | Upload a file (`multipart/form-data`, field `file`); processed within the request |
| `GET /api/v1/staff/imports/{job_id}` | Read an import job: status, counts, row errors |

## File

- **Formats:** `.csv` (UTF-8; a byte-order mark is fine; comma-separated) or `.xlsx`. The type is decided by the file name extension, then the content must match it. `.xls`, `.ods` and other formats are refused.
- **Limits:** 10 MB per file, 5,000 data rows, 100 columns. Only the first worksheet of a workbook is read.
- **Header row:** row 1. Header names are trimmed and case-insensitive, and columns may be in any order. Unknown headers, repeated headers, a blank header between columns and a missing required column fail the whole file.
- **Rows:** each data row is one SKU (variant) together with its product. Completely blank rows are skipped and not counted. Row numbers in errors are spreadsheet row numbers (the header is row 1).

### Columns

| Column | Required | Level | Rules |
| --- | --- | --- | --- |
| `sku` | yes | variant | Up to 80 characters, no spaces or `/`. Matches an existing variant, or creates one. |
| `product_slug` | yes | product | Lowercase letters and digits, words joined by single hyphens, up to 260 characters. Rows with the same slug are variants of one product; a new slug creates the product. |
| `product_name` | yes | product | 1–240 characters. |
| `category_slug` | yes | product | Slug of an existing category (inactive allowed; see below). |
| `brand_slug` | no | product | Slug of an existing brand. |
| `model` | no | product | 1–160 characters. |
| `description` | no | product | Text. |
| `warranty_text` | no | product | Text. |
| `product_status` | no | product | `draft`, `active`, `hidden` or `archived`. A new product without one is `draft`. |
| `variant_name` | yes | variant | 1–180 characters. |
| `price` | yes | variant | Whole RWF, VAT-inclusive: digits only, 0 to 999,999,999,999. |
| `compare_at_price` | no | variant | Same format as `price`; display only. |
| `low_stock_threshold` | no | variant | Whole number of 0 or more; 0 disables low-stock display. New variants: 0. |
| `variant_active` | no | variant | `true`/`false` (also `yes`/`no`, `1`/`0`). New variants: true. |
| `opening_stock` | no | variant | **New SKUs only.** Whole number of 0 or more, recorded as a `receipt` stock movement. Needs `inventory:adjust` (administrator and sales have it). |
| `attr:<key>` | no | variant | Variant attribute, e.g. `attr:colour`, `attr:storage`. Up to 500 characters. |
| `spec:<key>` | no | product | Product specification, e.g. `spec:display`. Up to 500 characters. |

`<key>` is 1–60 printable characters and is stored in lower case. The template includes `attr:colour`, `attr:storage` and `spec:display` as examples. Add or remove such columns as needed.

### Values

- **Numbers** (`price`, `compare_at_price`, `low_stock_threshold`, `opening_stock`):
  - In CSV, digits only: no separators, decimals, signs or currency (`1500` is valid; `1,500`, `1500.00` and `RWF 1500` are not).
  - In XLSX, a numeric cell must hold a whole number (`1500` or `1500.0`). Spreadsheet number formatting is ignored; only the stored value counts.
- **Text:** surrounding spaces are trimmed. A number typed into a text column is taken as text (`2024` → `"2024"`).
- **Formulas** (XLSX) are refused and never evaluated.
- **Text starting with `=`, `+`, `@` or `-`** is refused (spreadsheet formula injection). The one exception is `- ` (dash and space), so descriptions can contain list items.
- **Dates and TRUE/FALSE** are refused in text and number columns.
- **A blank cell** keeps the existing value on an update, or uses the default for something new. Import cannot clear a value; use the staff screens for that.
- **`attr:` and `spec:` values** are merged into the existing attributes or specifications. Keys not in the file are kept.

## How rows are applied

1. Every row is checked first: cell types and the field rules above (the same limits as the staff product API, module 6).
2. Two checks then look across the file. Neither depends on row order:
   - **A SKU repeated in the file** is refused on every row where it appears.
   - **Rows of one product (same `product_slug`) must not disagree** on product columns: `product_name`, `category_slug`, `brand_slug`, `model`, `description`, `warranty_text`, `product_status` or any `spec:` column. A blank cell does not count as disagreeing. When two rows give different values, every row of that product is refused.
3. Inside one database transaction:
   - **Database rules are checked:** the category and brand slugs exist; an existing SKU belongs to the product named in `product_slug` (a SKU cannot move to another product); `opening_stock` is only used for new SKUs.
   - **Every remaining valid row is applied:** new products and variants are created, and existing ones are updated.
   - **The job is finished**, and everything commits together.
4. Each change writes the same audit record as the staff API (`catalog.product_create`, `catalog.product_update`, `catalog.variant_create`, `catalog.variant_update` with old and new prices). Each import also writes one `catalog.import` record with the counts. A row whose values already match changes nothing and writes no record.

**Inactive categories and brands** are accepted, as in the staff API. The product stays hidden from the public catalogue until they are active.

**Concurrency:** imports and staff product changes take the same advisory lock, so two imports never interleave. If two files create the same new SKU, the first creates it and the second updates it.

## Job and errors

`POST` returns **201** with the job. `GET /imports/{job_id}` returns the same body later.

```json
{
  "id": "0b6f2a1e-8c4d-4f7a-9e3b-5d2c1a0f9e8d",
  "created_by_user_id": "4c3b2a19-0f8e-4d7c-8b6a-5f4e3d2c1b0a",
  "filename": "catalogue-october.xlsx",
  "file_format": "xlsx",
  "status": "completed",
  "total_rows": 3,
  "imported_rows": 2,
  "error_rows": 1,
  "errors": [{"row": 4, "field": "category_slug", "message": "No category has this slug."}],
  "errors_truncated": false,
  "created_at": "2026-10-24T09:00:00Z",
  "finished_at": "2026-10-24T09:00:02Z"
}
```

**`status` values:**

| Status | Meaning |
| --- | --- |
| `completed` | Valid rows were applied. Some rows may still have errors, and every row may be invalid (then nothing changed). |
| `failed` | Nothing changed. Either the file was unusable (encoding, headers, more than 5,000 rows, damaged workbook, no data rows), or the import stopped unexpectedly. |
| `processing` | Shown only while the request runs. |

**Counts and errors:**
- `total_rows` counts the data rows read.
- `imported_rows` counts the valid rows applied, including rows that already matched.
- `error_rows` counts every row with at least one error. A failed job has `error_rows` 0, and its errors explain the failure.
- `errors` holds `{row, field, message}` entries, ordered by row and then column, with **at most 1,000 entries**. `errors_truncated` is true when more were found; `error_rows` still counts them all.
- `row` is null for a file-level error. `field` is the column header, or null when no single column applies.
- Messages never repeat the submitted value.

**Request-level errors** (no job is created):
- 422 `validation_error`: missing file, empty file, or an extension other than `.csv` or `.xlsx`.
- 413 `file_too_large`: more than 10 MB. A request over 10 MB + 64 KB is refused while it is received, before authentication runs, as for image uploads (module 7, D-M2).
- 401 / 403: no token or no permission.

An unexpected server error during an import answers **500** `internal_error`. All catalogue changes from that import are rolled back, and the job is recorded as `failed` with the message "The import stopped because of an unexpected error…".

**Job access:** any user with `catalog:manage` may read any import job. Jobs hold only file names, counts and row/column errors, and catalogue staff share one catalogue. The uploaded file is not stored.

## Template

`GET /imports/template?format=csv` or `?format=xlsx` returns the header row (`attachment; filename="catalogue-import-template.<format>"`):
- The **CSV** template is UTF-8 with a byte-order mark, so Excel opens it correctly.
- The **XLSX** template has a `Products` sheet and an `Instructions` sheet. Only `Products` is imported.

The templates contain no data rows, so importing one unchanged creates nothing: it ends as a `failed` job with "The file has no data rows below the header."

## Limits and notes

- Files are processed within the request, with no background worker. Measured locally (2026-10-24): 5,000 new SKUs across 1,000 new products took about 32 seconds, and re-importing the same file about 2 seconds. The expected catalogue (100–200 products) takes a few seconds. A proxy in front of the API must allow requests of at least 60 seconds for the largest files.
- XLSX safety:
  - the unpacked size is limited to 100 MB;
  - formulas are not evaluated and external links are not loaded;
  - XML is parsed by the Python standard library (expat 2.7), which refuses entity-expansion attacks.
