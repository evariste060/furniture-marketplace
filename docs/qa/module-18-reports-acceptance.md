# Module 18 (reports) — acceptance record

| Field | Value |
| --- | --- |
| Module | 18 — reports (`docs/IMPLEMENTATION_PLAN.md` §5, "18 — reports"; §3 final staff matrix; §7 Q14, Q19, Q25) |
| Requirements | PRD PR-13 ("Daily/weekly sales, top products and stock reports can be viewed/exported to Excel"); PRD roles: management "Monitor sales, stock and popular products. Read reports and export approved data."; UAT scenario 7 ("Management exports daily sales and stock report and confirms totals against sample orders") |
| Linked tests | No QA test case covers reports (TC-01 to TC-24 have none); UAT scenario 7. QA checklist status: Not run |
| Branch | `dev`, based on `96c6324` (PR #30); commit and push state: see the Git history. The plan names `feat/module-18-reports`; the owner set `dev` as the target |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-28 |
| Recommendation | **Not Done; ready for human review.** Implemented as specified where the rules are approved, and verified by the full test suite. Not Done because R-1 to R-4 (definitions) and R-7 (exported columns) await their owners' decisions, R-6 (auditing exports) is an open policy choice, and UAT scenario 7 has not been run on staging. |

## Rules and their sources

| Rule | Source | Implementation |
| --- | --- | --- |
| Sales count only paid orders and delivered cash-on-delivery orders | Plan §5 module 18 (from UAT scenario 7) | Orders with a `succeeded` payment attempt. A mobile-money attempt succeeds only through its verified webhook; a cash-on-delivery attempt only when the order is delivered (§7 Q14; `confirm-cod` covers the same case). A late success after the hold lapsed leaves the attempt `expired` and the order cancelled (ADR-002), so it is not a sale. Exactly these orders receive an invoice (§7 Q19) |
| Each order counted once | Integrity (no double counting) | No constraint stops two attempts of one order from succeeding (a duplicate payment is a reconciliation case), so the report has one row per order, dated by its first success, and sums `orders` columns, never attempt amounts |
| Africa/Kigali days; weeks start on Monday | §7 Q25 | Range bounds computed in Python from Kigali midnight (`app.core.kigali_time.KIGALI`); grouping in PostgreSQL with `timezone('Africa/Kigali', …)` and `date_trunc('day' \| 'week', …)` (ISO weeks start on Monday) |
| Whole RWF | Plan §5 module 18; money is BIGINT | `SUM` of BIGINT columns cast back to BIGINT; integers in JSON and XLSX |
| Stock figures | Module 10 / ADR-002 (`app.services.inventory.stock_figures`) | The same query as `GET /api/v1/inventory`: available = on hand − unavailable − reserved − committed, never below 0 |
| `reports:read`: administrator, management, finance | Plan §3 final matrix (approved 2026-10-26) | `require_permission(Permission.REPORTS_READ)` on all four routes. Finance thereby sees the stock report although it has no `inventory:read`: that follows from the approved matrix and plan §5 (the stock report is a module 18 report) |
| Exports reconcile with the JSON | Plan §5 module 18 ("export matches the JSON") | Each export calls the same service function with the same parameters as its JSON report |

## Blockers and unresolved decisions

No approval is recorded below unless the repository contains it. The repository (plan §7, ADRs, QA records, the three requirement documents) records no decision on any of R-1 to R-4 or R-7; each is implemented as a stated engineering default and can be changed without a migration.

**Decision request** (evidence needed: a recorded answer, e.g. a new plan §7 entry with the owner and date, as for Q1–Q27):
1. R-1 (Product owner / Finance): date a sale by its first payment success (implemented), or by the date the order was placed?
2. R-2 (Product owner / Management): top products per product, by units sold, then revenue, then name; 10 by default, at most 100 (implemented)? Or by revenue first, or per SKU, or other limits?
3. R-3 (Product owner): `from` and `to` required, inclusive Kigali dates, at most 366 days (implemented)? Or optional with a default (e.g. today, or the last 7 days), or another maximum?
4. R-4 (Product owner / Management): list every day or week with zeros and cut partial weeks at the range (implemented)? Or only periods with sales, or whole weeks? Stock report paginated in JSON, complete in the export (implemented)?
5. R-7 (Product owner, with Finance): are the exported columns listed in R-7 the approved data for export?
6. R-6 (Security owner): should report reads or exports write an audit record, although no source requires it?

| # | Item | Needed from | Status |
| --- | --- | --- | --- |
| R-1 | **Which date places a sale in a period.** No document says. Implemented: the first payment success (`payment_attempts.succeeded_at`), the moment the order becomes a sale under the rule above and its invoice is issued (§7 Q19), so the report reconciles with the invoices of the day. The alternative is the order date (when it was placed): a mobile-money order placed at 23:50 and paid at 00:05 would then count on the earlier day, and a cash-on-delivery order on the day it was ordered rather than delivered | Product owner / Finance | Engineering default, not approved |
| R-2 | **Top products: ranking, limit and level.** PR-13 says "top products"; the module plan "Bestsellers" (`docs/Backend Modules — Implementation Order.md`). Implemented: per product (not per SKU), ranked by units sold, then revenue (line totals after discounts), then name, then ID; `limit` 1–100, default 10; over the same `from`/`to` and the same sales rule | Product owner / Management | Engineering default, not approved |
| R-3 | **Range parameters.** Implemented: `from` and `to` required, inclusive Kigali dates (`YYYY-MM-DD`), at most 366 days apart; reversed or longer ranges are 422 | Product owner | Engineering default, not approved |
| R-4 | **Presentation.** Implemented: every day or week of the range is listed, with zeros; the first and last week are cut at the range (`period_start`/`period_end` show the covered days); the stock JSON is paginated (standard envelope) with totals over every SKU, and its export has every SKU | Product owner / Management | Engineering default, not approved |
| R-5 | Refunds and returns are not subtracted: no module records them yet (the bestselling rule makes the same note) | Later module | Recorded |
| R-6 | **Auditing of report reads and exports.** Sources: the technical plan requires "least privilege and audit important changes" (role-based access section); ADR-006 audits changes and security events (failed login, access denied, session events) in the same transaction as the change; the PRD and the QA/UAT checklist say nothing about auditing reads or exports. Reports and exports change nothing, so no source requires an audit record for them, and none is written (as for invoice and delivery-note downloads, which only audit issuance). This is a reading of the sources, not a security approval: whether exports should be audited anyway is a policy choice | Security owner | Not required by the sources; policy choice open, not approved |
| R-7 | **Which data may be exported.** The PRD gives management "Read reports and export approved data." No document lists the approved data. Exported today: sales per period (order count, subtotal, discounts, delivery fees, VAT included, total); top products (rank, product name, product ID, units, revenue, orders); stock per SKU (SKU, product, variant, sellable flag, on hand, unavailable, reserved, committed, available, low-stock threshold and flag); plus an About sheet (filters, time zone, counting rule, generation time). No customer, recipient, address, phone, email, payment reference or staff data is exported. R-6 does not answer this: auditing and approved content are separate decisions | Product owner (with Finance for the sales figures) | **Open: sign-off on the exported columns required** |

## Acceptance criteria

PASS means verified by automated tests on the isolated PostgreSQL test database (`rwanda_ecommerce_test`); it is not UAT, staging or business approval. Tests are in `backend/tests/integration/test_reports_api.py` unless a path is given.

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Sales totals reconcile exactly with known orders | PASS | `test_sales_count_paid_and_delivered_cod_orders_once_and_nothing_else` (totals equal the sum of the qualifying orders' own columns) |
| 2 | Paid and delivered cash-on-delivery orders included; created, pending, failed, late-success (expired), confirmed or dispatched cash-on-delivery and cancelled orders excluded | PASS | Same test |
| 3 | No double counting: an order with several lines, or with a second succeeded attempt, counts once | PASS | Same test (two lines; a duplicate succeeded attempt) |
| 4 | Kigali midnight: 21:59:59 and 22:00:00 UTC fall on different Kigali days; the range starts at 00:00 Kigali; the order date does not decide the period | PASS | `test_a_sale_is_dated_by_its_payment_in_kigali_days` |
| 5 | Weeks start on Monday in Kigali time, including a Monday 00:00 Kigali sale that is Sunday in UTC; weeks cut at the range | PASS | `test_weeks_start_on_monday_in_kigali_and_are_cut_at_the_range` |
| 6 | Empty results | PASS | `test_empty_ranges_list_every_period_with_zeros` |
| 7 | Invalid ranges, dates, `group_by`, `limit`, paging and export type are 422 `validation_error` | PASS | `test_invalid_parameters_are_422_validation_errors` (17 cases) |
| 8 | Top products: aggregation, ties, limit, exclusions, deleted products | PASS | `test_top_products_rank_by_units_then_revenue_then_name`, `test_a_deleted_products_sales_stay_under_the_name_it_was_sold_with` |
| 9 | Stock figures reconcile with the inventory list and the reservation model (active and committed holds) | PASS | `test_stock_report_is_the_inventory_list_with_totals` |
| 10 | Authorization: administrator, management, finance 200 on every route; sales, operations, customer 403; anonymous 401 | PASS | `test_reports_read_holders_can_use_every_report`, `test_everyone_else_gets_403_on_every_report`, `test_anonymous_callers_are_401` |
| 11 | XLSX valid, expected columns and values, equal to the JSON under the same filters; correct content type and filename | PASS | `test_the_sales_export_matches_the_json_report`, `test_the_top_products_export_matches_the_json_and_never_writes_formulas`, `test_the_stock_export_matches_the_json_report` |
| 12 | No formula injection through product names | PASS | `test_the_top_products_export_matches_the_json_and_never_writes_formulas` |
| 13 | Runtime role grants suffice; two API processes | PASS | `backend/tests/postgres/test_pg_reports.py` |
| 14 | OpenAPI inventory updated without weakening | PASS | `backend/tests/postgres/test_pg_http.py` (`EXPECTED_OPERATIONS` +4) |
| 15 | R-1 to R-4 and R-7 (exported columns) approved by their owners | **BLOCKED** | No recorded decision; see the decision request above. R-6 (audit) is a separate, open policy choice |
| 16 | Full CI test commands on this change | PASS | `uv run pytest -q --ignore=tests/postgres`: 1,768 passed (exit 0); `uv run pytest -q tests/postgres`: 102 passed (exit 0) on its second run; the first had one transient connection reset in a module 12 test (see Verification) |
| 17 | UAT scenario 7 on staging; PR review, CI | BLOCKED | No staging from here; UAT not run; PR review and CI on GitHub pending |

## Verification

All tests used `rwanda_ecommerce_test` (disposable per-test schemas; the PostgreSQL HTTP suite rebuilds that database's `public` schema). The development database `rwanda_ecommerce` was not migrated, seeded or read. Commands from `backend/`, 2026-10-28.

| Command | Result |
| --- | --- |
| `uv run pytest -q tests/integration/test_reports_api.py` | 34 passed (exit 0). An earlier run had 3 failures from a bug in the test's own cart helper (it dropped the cart token after the first line), fixed before this run; no product code changed |
| `uv run pytest -q tests/postgres/test_pg_reports.py tests/postgres/test_pg_http.py` | 26 passed (exit 0) |
| Regression: `tests/unit/test_roles.py`, `tests/integration/test_staff_authorization_api.py`, `test_inventory_api.py`, `test_inventory_list_api.py`, `test_payments_api.py`, `test_payment_hardening.py`, `test_checkout_api.py`, `test_order_fulfilment_api.py`, `test_invoices_api.py`, `test_notifications_api.py` | 371 passed (exit 0) |
| Code change after the runs above (2026-10-28 12:1x): `inventory_admin._stock_rows` renamed to the public `stock_list_query` (no behaviour change; 4 call sites). The focused, PostgreSQL and regression results above predate it | Rerun after the rename: see below (all passed) |
| `uv run ruff check . ../scripts` (after the rename and the document edits) | All checks passed (exit 0) |
| `uv run ruff format --check . ../scripts` | 298 files already formatted (exit 0) |
| `uv run mypy` | Success: no issues found in 261 source files (exit 0) |
| `git diff --check` (repository root) | Clean (exit 0); new files checked for trailing whitespace: none |
| Full suite, attempt 1 (2026-10-28 07:28) | **Not completed:** stopped by the Claude Code session for critically low memory at about 77% (1,390 passed, none failed); no exit code; the PostgreSQL command did not start |
| Full suite, attempt 2 (2026-10-28 12:13) | **Not completed:** the run ended with the session at about 32% (559 passed, none failed); no exit code |
| Full suite, attempt 3 (2026-10-28 15:06) | **Invalid; stopped:** Docker Desktop was not running after the machine resumed from standby (14:47–15:06), so the test database was unreachable: 26 passed (tests needing no database), 708 setup errors, 0 failures. Docker was not checked before launch. The run was stopped and counts for nothing |
| Post-rename rerun (2026-10-28 17:02) | **Not started:** prerequisites failed: Docker Desktop not running (no Docker processes) and the test database port 55432 closed; no test was run |
| Post-rename focused rerun (2026-10-28 17:08, Docker healthy, database reachable, no other test run): `uv run pytest -q tests/integration/test_reports_api.py tests/postgres/test_pg_reports.py tests/postgres/test_pg_http.py` | 60 passed (exit 0) |
| Post-rename regression: `tests/unit/test_roles.py`, `tests/integration/test_staff_authorization_api.py`, `test_inventory_api.py`, `test_inventory_list_api.py`, `test_inventory_reservations.py`, `test_payments_api.py`, `test_payment_hardening.py`, `test_checkout_api.py`, `test_order_fulfilment_api.py`, `test_invoices_api.py`, `test_notifications_api.py` | 410 passed (exit 0) |
| Full suite, attempt 4 (17:29) | Stopped by me within seconds: another project's test run (`D:\imibereho`) had started, and concurrent runs were to be avoided; restarted once the machine was quiet |
| **`uv run pytest -q --ignore=tests/postgres`** (2026-10-28 17:34–18:37, machine kept awake, database healthy throughout) | **1,768 passed (exit 0)**, 1 h 2 min |
| `uv run pytest -q tests/postgres`, run 1 (18:37) | 1 failed, 101 passed (exit 1): `test_pg_delivery.py::test_concurrent_fee_changes_keep_one_active_rule_and_full_history` (module 12) got `httpx.ReadError: [WinError 10054] An existing connection was forcibly closed by the remote host` on one of its concurrent PATCH requests; the eight that were answered returned 200. Module 18 changes no delivery code, and that test runs before the report test. Rerun alone three times: 7 passed each time. Treated as a transient transport reset, not a defect |
| **`uv run pytest -q tests/postgres`**, run 2 (18:41) | **102 passed (exit 0)** (101 earlier tests plus `test_pg_reports.py`) |
| Final static checks (after all code changes) | `uv run ruff check . ../scripts`: all checks passed (exit 0); `uv run ruff format --check . ../scripts`: 298 files already formatted (exit 0); `uv run mypy`: no issues in 261 source files (exit 0); `git diff --check`: clean (exit 0) |

No migration: reports only read existing tables, and the runtime role's existing SELECT grants suffice (`test_pg_reports.py` runs on that role). No dependency change: `openpyxl` and `tzdata` were already dependencies.
