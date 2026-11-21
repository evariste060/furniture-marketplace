# Module 10 (inventory) — acceptance record

| Field | Value |
| --- | --- |
| Module | 10 — inventory (`docs/IMPLEMENTATION_PLAN.md` §5, "10 — inventory"; §7 Q9) |
| Requirements | PRD PR-09 (stock levels, low-stock visibility); Technical plan §6 (inventory safe under concurrent checkout); ADR-002 stock lifecycle |
| Linked tests | TC-13 (stock at zero and concurrent orders), TC-14 (cancel and release stock), TC-16 (staff roles) |
| Branch | `feat/module-10-inventory`, stacked on module 9 (`d2adf95`) and module 8 (`d8c9cc1`), neither yet in `dev` |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-24 |
| Recommendation | **Not Done.** The backend is complete and tested. Review, staging and scheduling of the expiry job are open. |

## Acceptance criteria

| # | Criterion (plan §5) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GET /inventory?low_stock=&q=&page=&size=` with `inventory:read` | Verified | `backend/app/api/v1/endpoints/inventory.py:list_inventory` (effective path `/api/v1/inventory`); `test_the_list_follows_the_inventory_read_matrix` (administrator, sales and operations 200; management and customer 403; anonymous 401) |
| 2 | One row per SKU with on-hand, unavailable, reserved, committed, available and threshold | Verified | `test_each_sku_is_one_row_with_every_stock_figure` (two holds on one SKU, still one row; exact figures 10/1/2/3/4), `test_a_sku_without_an_inventory_record_has_zeros`, `test_inactive_variants_are_listed_as_not_sellable` |
| 3 | `GET /inventory/{sku}` and `POST /inventory/{sku}/adjustments` kept | Verified | `tests/integration/test_inventory_api.py` (19) and `tests/integration/test_inventory_reservations.py` (39) pass unchanged; `test_adjustments_show_in_the_list` |
| 4 | Low stock = available ≤ threshold with threshold > 0 | Verified | `test_low_stock_is_available_at_or_below_a_positive_threshold` (at, above, threshold 0, empty, lowered by active and by committed holds) |
| 5 | Low-stock alert = this filtered list (§7 Q9) | Verified | `low_stock=true`; same test and `test_the_stock_list_reports_holds_and_low_stock_on_the_runtime_role` |
| 6 | Reservation lifecycle, triggers, expiry job, idempotent adjustments (already built) | Verified (existing tests) | Reservation and adjustment suites above; `test_figures_follow_reservation_release_commit_and_dispatch`, `test_an_overdue_hold_counts_until_the_expiry_job_releases_it` |
| 7 | Tests: list and filter under reservations | Verified | Rows 2, 4 and 6 |
| 8 | Tests: pagination | Verified | `test_rows_are_ordered_by_sku_and_pages_are_stable`, `test_an_empty_list_is_an_empty_page`, `test_invalid_parameters_are_422` |
| 9 | Tests: permission matrix | Verified | Row 1 |
| 10 | List and single-SKU figures cannot disagree | Verified | One SELECT (`stock_figures`) behind both; `test_the_list_and_the_single_sku_read_always_agree` (list row = `GET /inventory/{sku}` = `availability()` for 5 SKUs in different states); runtime role on two processes |
| 11 | No N+1 queries | Verified | `test_the_list_runs_a_fixed_number_of_queries_whatever_the_page_size` (2 stock queries for pages of 2 and of 30) |
| 12 | PR reviewed, CI green, staging | **Open** | Not pushed (by instruction) |
| 13 | Expiry job scheduled in each environment | **Open (operations)** | The script exists and is tested; nothing in the repository schedules it (ADR-002 / ADR-004) |

## Decisions (for the reviewer)

| # | Decision | Checked against | Why |
| --- | --- | --- | --- |
| D-V1 | `q` is a case-insensitive literal substring of the SKU, variant name or product name (`%`, `_` and `!` are literal). | Plan §5 module 10 names `q` without defining it; the module order document lists only `low_stock` for this route; §7 Q5 (full-text search) applies to `GET /catalog/products`, not to staff inventory. No approved decision is overridden. | Staff look up SKU codes and fragments ("GS24", "-BLK"). Full-text search splits codes at punctuation and matches only word prefixes. A substring search over a few hundred SKUs is cheap. |
| D-V2 | `low_stock=false` returns the SKUs that are not low; omitting it returns all. | The existing `in_stock` filter of the catalogue (true and false both filter). | Consistent filter convention. |
| D-V3 | The list includes inactive variants and products in every status, with `is_sellable`, ordered by SKU. | The plan says "one row per SKU" without restriction; `GET /inventory/{sku}` already serves inactive SKUs. | Stock of hidden or discontinued items still has to be counted and adjusted. |
| D-V4 | An active hold past its expiry keeps counting as reserved until the expiry job marks it expired. | ADR-002 lifecycle; `availability()` and the reservation service already behave this way. | One rule everywhere. The fix for stale holds is scheduling the job, not a second formula. |

## Open items before module 10 can be marked Done

1. Merge modules 8 and 9 first (this branch contains them), then review this pull request.
2. Schedule `scripts/expire_reservations.py` in each environment (operations, ADR-004).
3. Staging deployment.
4. The admin stock screen (frontend) uses this route; it is not part of this backend module.
