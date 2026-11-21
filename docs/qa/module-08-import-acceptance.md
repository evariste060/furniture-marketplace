# Module 8 (catalogue import) — acceptance record

| Field | Value |
| --- | --- |
| Module | 8 — import (`docs/IMPLEMENTATION_PLAN.md` §5, "8 — import") |
| Requirements | PRD PR-10 ("bulk-import CSV/Excel with validation/error report"); Technical plan §6 (product schema), §7 risk "product catalogue incomplete" (import template on Day 1); UAT scenario 6 |
| Linked tests | TC-15 (admin imports valid CSV and invalid rows); TC-16 (staff roles) for the import routes |
| Branch | `feat/module-08-import` (from `dev` at `24f2ec5`, after PR #24) |
| Trello card | None recorded for module 8 in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-24 |
| Recommendation | **Not Done.** Code, tests and documentation are ready for review. Not yet committed, reviewed or run on staging, and the business UAT of TC-15 is open. |

## What existed before

Nothing for import: there was no `import_jobs` table, route, parser, template, test or `openpyxl` dependency. The product and variant rules lived in `ProductAdminService`, whose methods each commit their own transaction.

## Acceptance criteria

| # | Criterion (source) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `POST /staff/imports`, `GET /staff/imports/{id}`, `GET /staff/imports/template?format=csv\|xlsx`, all `catalog:manage` (plan §5) | Verified | `backend/app/api/v1/endpoints/catalog_import.py`; `test_sales_staff_import_and_read_any_import_job`, `test_other_roles_cannot_upload_read_jobs_or_download_templates`, `test_anonymous_requests_are_unauthorized`; live OpenAPI inventory in `tests/postgres/test_pg_http.py` |
| 2 | Table `import_jobs` with the planned columns (plan §5) | Verified | Migration `9d820b74f718` (revises `76768b844c03`); `tests/integration/test_import_jobs_migration.py` (upgrade → downgrade → upgrade, defaults, 8 rejected invalid states, RESTRICT on the user, `alembic check`) |
| 3 | Every row validated first; valid rows imported in one transaction; invalid rows reported by row and field (TC-15) | Verified | `test_valid_rows_are_imported_and_invalid_rows_reported_by_row_and_column`; `test_an_unexpected_failure_rolls_back_every_change_and_fails_the_job` |
| 4 | Match by SKU: create or update (§7 Q3) | Verified | `test_existing_skus_are_updated_and_new_skus_created_with_blank_cells_kept`; `test_reimporting_the_same_file_changes_nothing_and_counts_rows_as_imported`; `test_concurrent_imports_of_the_same_new_sku_create_it_once` |
| 5 | Category and brand by slug (plan §5) | Verified | Unknown category and brand in the TC-15 test; `test_inactive_categories_are_accepted_and_keep_the_product_hidden` |
| 6 | Optional `opening_stock` as a `receipt` movement for new SKUs only (§7 Q3) | Verified | `test_opening_stock_records_a_receipt_for_new_skus_only`; `test_opening_stock_needs_inventory_adjust`; `test_runtime_role_imports_products_with_opening_stock` |
| 7 | Up to 5,000 rows, processed within the request (plan §5) | Verified | `test_the_real_row_limit_is_5000`; `test_more_than_5000_rows_fails_the_job`; timing below |
| 8 | Errors capped at 1,000 | Verified | `test_more_than_1000_errors_are_capped_but_every_invalid_row_counted`; database check `errors_capped_array` |
| 9 | Duplicate SKUs in one file (plan tests) | Verified | `test_duplicate_skus_in_one_file_are_refused_on_every_row`; unit `test_a_sku_repeated_in_the_file_is_refused_on_every_row` |
| 10 | Formula and injection-like cells (plan tests) | Verified | `test_xlsx_uploads_use_native_numbers_and_refuse_formulas`; `test_injection_like_csv_text_is_refused_and_never_echoed`; unit `test_formulas_injection_like_text_and_wrong_types_are_refused` |
| 11 | Template round trip (plan tests) | Verified | `test_the_csv_template_round_trips`; `test_the_xlsx_template_round_trips`; `test_the_untouched_template_imports_nothing`; unit `test_both_templates_have_the_same_headers_and_no_data_rows` |
| 12 | Empty, malformed, unsupported and oversized files | Verified | `test_empty_or_unsupported_uploads_get_422_and_create_no_job`; `test_files_over_10_mb_get_413_and_create_no_job`; `test_unusable_files_end_as_failed_jobs_without_changes`; `tests/unit/test_import_files.py` |
| 13 | Forbidden roles (plan tests; TC-16) | Verified | See row 1 |
| 14 | Job status, timestamps and counts on success and failure | Verified | `test_the_job_is_audited_and_timestamps_are_ordered`; failed-job assertions in rows 3 and 12; database check `finished_when_final` |
| 15 | Runtime-role grants pinned in tests and ADR-006 (plan §2) | Verified | `scripts/provision_runtime_role.py`; `tests/unit/test_runtime_role_grants.py`; `test_runtime_role_cannot_delete_import_jobs`; ADR-006 |
| 16 | Existing catalogue behaviour unchanged (regression) | Verified | `tests/integration/test_product_admin_api.py` and the full suite pass after the product-service refactor |
| 17 | OpenAPI with examples (done checklist) | Verified | Response and error examples; `test_openapi_documents_the_import_routes` |
| 18 | Seed data (done checklist) | Decided | No seed: catalogue rows are business input (ADR-002; module 5 and module 7 D-M4). The import itself is how real data is loaded. |
| 19 | Pull request reviewed, CI green, deployed to staging | **Open** | Not committed (as instructed) |
| 20 | TC-15 recorded in the QA checklist | **Partial** | Automated part below; the business UAT run is open |

## TC-15 — Admin imports valid CSV and invalid rows

Expected result (QA/UAT checklist §2): "Valid rows import; errors identify row/field; no silent data corruption."

| Field | Value |
| --- | --- |
| Status | **Pass** (automated, API level). The UAT with the business catalogue spreadsheet (UAT scenario 6) is not run yet. |
| Tester / date | Backend engineering, 2026-10-24 |
| Environment | Local, Windows 11, Python 3.14.0, PostgreSQL 18 (disposable test database), branch `feat/module-08-import` |
| Evidence | `test_valid_rows_are_imported_and_invalid_rows_reported_by_row_and_column`: 5 rows, 2 imported, 3 reported at rows 4, 5 and 6 with columns `category_slug`, `price` and `brand_slug`; the invalid rows created nothing. `test_an_unexpected_failure_rolls_back_every_change_and_fails_the_job`: a failure on the second row leaves no product, variant or price change from the file, and the job is `failed`. |
| Defects | None |

Timing (local, 2026-10-24, measured once with a temporary test that was then deleted): a 5,000-row CSV of new SKUs across 1,000 new products took 31.8 s; re-importing the same file (no changes) took 1.7 s.

## Decisions made within the plan (for the reviewer)

| # | Decision | Why |
| --- | --- | --- |
| D-I1 | `product_slug` is a required column and identifies the product of each row. | The plan matches rows by SKU but does not say how a new SKU finds its product. A slug is unique, stable across re-imports and already the product's public key. |
| D-I2 | `attr:<key>` and `spec:<key>` columns carry variant attributes and product specifications, merged into existing values. | The product schema has both (Technical plan §6; UAT scenario 1 names RAM, storage and colour). Spreadsheet users cannot be expected to type JSON. |
| D-I3 | A blank cell keeps the existing value; import cannot clear values. | Re-importing a partial sheet must not wipe data. Clearing stays in the staff screens. |
| D-I4 | A SKU repeated in a file, and rows of one product that disagree on product columns, are refused on every affected row. | Row order must never decide which value wins. |
| D-I5 | File limit: 10 MB. Request-level problems (no file, empty, wrong extension, too large) are 422/413 with no job. Content problems create a `failed` job. | No size was specified; images use 5 MB, and 5,000 rows with descriptions can exceed that. Cheap checks run before any work; content problems are kept as a record the user can open. |
| D-I6 | Any `catalog:manage` user may read any import job. | Jobs contain no personal data and the catalogue is shared. ADR-006 has no per-owner rule for catalogue data. |
| D-I7 | Text starting with `=`, `+`, `@` or `-` is refused, except `- ` for list items. | Formula injection when the catalogue is exported later (reports, module 18). Allowing `- ` keeps bulleted descriptions possible. |
| D-I8 | `opening_stock` needs `inventory:adjust` in addition to `catalog:manage`, and is refused for existing SKUs. | Least privilege: it changes stock. Existing stock is changed by stock adjustments (module 10), which are idempotent and audited. |
| D-I9 | An `errors_truncated` column is added to the planned table. | The response must say when errors were cut, and the count of error entries is not otherwise kept. |
| D-I10 | An unexpected failure rolls back, marks the job `failed` in a new transaction and answers 500. | The client learns that something went wrong; the job does not stay `processing`. If the database itself is down, the job can stay `processing`, and that is the only case. |
| D-I11 | `ProductAdminService` was split into `apply_*` functions that run inside the caller's transaction; the routes wrap them unchanged. | One import must be one transaction with the same rules and audit records as the staff API, without copying the rules. |

## Open items before module 8 can be marked Done

1. Commit, pull request and human review (not committed, as instructed).
2. Business UAT of TC-15 and UAT scenario 6 with the real catalogue spreadsheet, recorded here.
3. Reviewer confirmation of decisions D-I1 to D-I11, in particular D-I1 (`product_slug` required), D-I5 (10 MB) and D-I7 (leading `-` refused).
4. Staging deployment. The proxy must allow at least 10 MB + 64 KB request bodies on `POST /api/v1/staff/imports` and about 60 seconds for the largest files.
5. The admin import screen (frontend) is not part of this backend module. `docs/api/catalogue-import.md` is its contract.
