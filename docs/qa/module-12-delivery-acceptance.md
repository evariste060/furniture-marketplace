# Module 12 (delivery) — acceptance record

| Field | Value |
| --- | --- |
| Module | 12 — delivery (`docs/IMPLEMENTATION_PLAN.md` §5, "12 — delivery"; §3 permission matrix) |
| Requirements | PRD PR-11 (delivery fees); RE-026 B1 (zones, flat fees, free-delivery threshold, COD, VAT-inclusive fees), B5 (table columns, approved with the plan on 2026-10-23), B6 (only administrators change; management views) |
| Linked tests | TC-17 (delivery fee by zone and the free-delivery threshold) |
| Branch | `feat/module-12-delivery` (checked out by the owner; not committed) |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-24 |
| Recommendation | **Not Done; ready for human review.** The backend is implemented and verified at API level. Still open: human review, approved launch values for the placeholder fees and threshold, the storefront TC-17 run, and staging. |

## Acceptance criteria

| # | Criterion (plan §5) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GET /delivery/zones`: active zones with fee, COD availability and the free-delivery threshold | PASS | `test_public_list_shows_active_zones_in_order_with_fee_cod_and_threshold`, `test_public_list_is_empty_and_threshold_null_until_configured` |
| 2 | Inactive zones (and zones without a current fee) are not offered | PASS | `test_public_list_excludes_inactive_zones_and_zones_without_a_current_fee`, `test_staff_list_includes_inactive_zones_with_history`, `test_cart_refuses_inactive_and_unknown_zones` |
| 3 | `GET /staff/delivery/zones` (`delivery:read`), `POST` and `PATCH /staff/delivery/zones/{id}` (`delivery:manage`) | PASS | `test_create_*`, `test_update_*`, `test_duplicate_code_or_district_is_409`, `test_update_of_an_unknown_or_malformed_zone_id` |
| 4 | `GET /staff/settings` (`settings:read`), `PATCH /staff/settings` (`settings:manage`, only `delivery.free_delivery_threshold`) | PASS | `test_settings_read_and_write_with_audit`, `test_settings_reject_unknown_keys_and_malformed_values`, `test_unregistered_stored_settings_are_never_exposed` |
| 5 | B6: management can view but not edit; others forbidden | PASS | `test_management_can_view_but_not_change_delivery_or_settings`, `test_other_roles_and_anonymous_callers_are_refused` (sales, operations, customer 403; anonymous 401), `test_management_can_view_but_not_change_over_http` (runtime role, real HTTP), `tests/unit/test_roles.py` |
| 6 | `delivery_zones` columns: code (unique), name, district (unique; three districts), cod_available (default true), sort_order, is_active, timestamps; `coverage` dropped | PASS | `test_head_has_the_approved_columns_indexes_and_settings_table`, `test_database_backstops_reject_bad_rows` |
| 7 | `delivery_fee_rules`: BIGINT RWF fee, currency, active flag, window, timestamps; at most one active rule per zone (partial unique index); `rule_data` dropped | PASS | Same tests; `uq_delivery_fee_rules_one_active_per_zone` rejects a second active rule |
| 8 | A fee change closes the old rule and adds a new one in one transaction; history kept | PASS | `test_fee_changes_close_the_old_rule_and_keep_the_history`, `test_a_failed_audit_rolls_back_the_whole_fee_change`, `test_a_failed_new_rule_rolls_back_the_closing_of_the_old_one`, `test_concurrent_fee_changes_keep_one_active_rule_and_full_history` (8 concurrent changes over two processes: 9 rules, 1 active; this run did not exercise the interleaving below). **Corrected 2026-10-25:** the pre-commit review found that a change whose transaction started before a competing change but took the zone lock after it ended the newer rule before it began (CHECK `valid_window` violation, answered 500). Fixed: one `clock_timestamp()` read after the locks ends the old rule and starts the new one; history is ordered by `starts_at`; a rule that cannot be closed validly is 409 `fee_change_conflict`. Deterministic regression tests: `test_a_fee_change_whose_transaction_started_first_but_locked_last_keeps_valid_history` (both changes succeed, valid and ordered history), `test_an_active_rule_that_has_not_started_yet_is_a_409_not_a_500`, `test_only_fee_rule_constraints_become_409_and_other_integrity_errors_propagate` |
| 9 | `settings` table: key (PK), JSONB value, updated_by_user_id, updated_at | PASS | `test_head_has_the_approved_columns_indexes_and_settings_table`; `test_concurrent_threshold_changes_are_all_audited_in_order` |
| 10 | The zone comes from the address district; other districts cannot be delivered to | PASS (service level) | `delivery_service.quote_for_district`; `test_quote_from_an_address_district`, `tests/unit/test_delivery_units.py`. No route calls it yet: checkout (module 14) will. The cart estimate takes a zone code (D-D1). |
| 11 | Free when the subtotal after discount ≥ threshold; boundary 199 999 / 200 000 | PASS | `test_threshold_boundary`, `test_cart_quote_at_the_threshold_boundary`, `test_free_at_or_above_the_threshold`. The cart has no discount until module 13 (D-D5). |
| 12 | Fees are VAT-inclusive | PASS (documented) | Fees are stored and returned as charged; no VAT is added (schemas and OpenAPI descriptions). VAT extraction is module 14/16 (ADR-007). |
| 13 | Cart `zone` returns the delivery fee and grand total from server data | PASS | `test_cart_quote_for_a_guest_ignores_client_amounts`, `test_cart_quote_uses_only_available_lines`, `test_cart_answers_503_while_delivery_is_not_configured`, `test_an_empty_cart_is_quoted_with_the_zone_fee`, `test_cart_quote_on_the_runtime_role` |
| 14 | Seeds: `scripts/seed_dev.py` adds the three placeholder zones and the 200 000 threshold; no production seed migration | PASS | `tests/integration/test_seed_dev.py` (idempotent, never overwrites; **since 2026-10-25** requires APP_ENV=development set explicitly in the environment or `.env`: unset, empty, staging, production and other values are refused before settings are loaded or a connection is made, and explicit development seeds the disposable test schema), `test_seed_runs_on_the_runtime_role_once_and_refuses_outside_development`; the migration seeds nothing (`test_head_has_the_approved_columns_indexes_and_settings_table`) |
| 15 | Migration upgrade, downgrade, upgrade; `alembic check` | PASS | `tests/integration/test_delivery_migration.py` (legacy rows kept; refusals change nothing) |
| 16 | Runtime role least privilege | PASS | `scripts/provision_runtime_role.py`; `test_delivery_and_settings_tables_have_exactly_the_privileges_module_12_uses`; `test_runtime_role_cannot_delete_delivery_rows_or_settings`; ADR-006 |
| 17 | Staff changes audited | PASS | `delivery.zone_create`, `delivery.zone_update`, `settings.update`, written in the change's transaction; no-ops not audited |
| 18 | Placeholder values replaced with approved launch values | BLOCKED | Needs the project owner (RE-026 B1). The seed refuses outside development, so the placeholders cannot reach production through it. |
| 19 | TC-17 on the storefront; PR reviewed, CI green, staging | BLOCKED | Not committed (by instruction); no storefront delivery page yet; staging not available from here (§7 Q27) |

## Decisions (for the reviewer)

| # | Decision | Why |
| --- | --- | --- |
| D-D1 | The cart estimate `GET /cart?zone=` takes a zone **code**, as the approved module 11 contract already did. Checkout (module 14) derives the zone from the address district with `quote_for_district`. | The plan §5 contract is `?zone=`; addresses are only known at checkout. |
| D-D2 | `code` and `district` cannot be changed after a zone is created (PATCH refuses them with 422). | One zone per district is the rule; moving a zone between districts would rewrite what past fee rules meant. |
| D-D3 | An unknown or inactive zone gets 422 `delivery_zone_unavailable`; an active zone without a current fee, or an unset (or corrupt) threshold, gets 503 `delivery_quote_unavailable`. | A client error versus a configuration gap; no fee or total is ever invented (RE-026 policy constraints). |
| D-D4 | A cart with no available lines is quoted with the zone fee (subtotal 0 is below any positive threshold). | The approved rule applied as written; no special case was approved. |
| D-D5 | Until promotions (module 13), the subtotal after discount is the merchandise subtotal of the available lines: carts have no discount field or code yet. Module 13 must pass the discounted subtotal to the delivery quote. | No discount mechanism exists; nothing is assumed beyond that. |
| D-D6 | The threshold is a whole RWF integer from 0 to the storable cap (0 = always free); strings, floats, booleans and null are refused. Only registered keys are read or written; other rows in `settings` are never exposed. | ADR-007 money rules; least exposure. |
| D-D7 | `GET /staff/delivery/zones` is not paginated. | At most one zone per district, so at most three. |
| D-D8 | A new fee starts at the instant read with `clock_timestamp()` after the zone lock is held, and the closed rule ends at that same instant; future-dated fees are not offered. (Corrected 2026-10-25: it was the transaction start time, see row 8.) | Only immediate fee changes were approved; a post-lock time keeps history ordered under concurrent requests. |
| D-D9 | The migration refuses (changing nothing) instead of guessing when a legacy zone's district cannot be read from its name or code, when `coverage` or `rule_data` holds data, or when a zone has two active rules. | Existing data is never invented or silently discarded. The dev and test databases had no delivery rows on 2026-10-24. |

## Verification

All database tests ran on `rwanda_ecommerce_test` only (per-test schemas, and the tests/postgres harness on its own runtime role). Run from `backend/` with uv.

Historical results (2026-10-24, before the pre-commit review; not rerun in full since):

| Command | Result |
| --- | --- |
| `pytest tests --ignore=tests/postgres` | 1023 passed |
| `pytest tests/postgres` | 81 passed |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass |
| `mypy .` (repository root) | 4 errors, all in files this module does not touch (`app/repositories/catalog.py:63`, migrations `c3a8e5f1d2b4`, `528e6436c34e`) |
| `alembic heads`, `alembic history`, `uv lock --check` | Single head `b6f1d3a9c8e4`; lockfile up to date |

Rerun after the review fixes (2026-10-25; focused, by design):

| Command | Result |
| --- | --- |
| `pytest tests/integration/test_seed_dev.py tests/integration/test_delivery_api.py` | 93 passed (15 seed, 78 delivery, including the new regression tests) |
| `pytest tests/integration/test_seed_dev.py tests/integration/test_delivery_api.py tests/postgres/test_pg_delivery.py` (after adding the current-fee read test) | 101 passed (15 seed, 79 delivery, 7 postgres delivery on the runtime role) |
| `pytest tests/integration/test_cart_api.py tests/integration/test_cart_security.py tests/integration/test_delivery_migration.py tests/unit` | 415 passed |
| `pytest tests/postgres/test_pg_delivery.py tests/postgres/test_pg_cart.py` | 13 passed |
| `ruff check`, `ruff format --check` (backend and scripts) | Pass |
| `mypy .` (repository root) | The same 4 errors as before, none in changed files |

Evidence for the concurrency fixes, by kind:

- **Repository tests (permanent, rerun on 2026-10-25):**
  - `test_a_fee_change_whose_transaction_started_first_but_locked_last_keeps_valid_history`: fee changes. Both succeed, the history is valid, and it is ordered by `starts_at`.
  - `test_a_read_whose_transaction_began_before_a_fee_change_sees_the_new_fee`: current-fee reads, `delivery_repository.current_fees` with `statement_timestamp()`. It also asserts that a `now()`-based window would return no current fee in the same transaction, which proves the interleaving occurred.
  - `test_an_active_rule_that_has_not_started_yet_is_a_409_not_a_500`.
  - `test_only_fee_rule_constraints_become_409_and_other_integrity_errors_propagate`.
- **Historical scratch probes (2026-10-25, not in the repository, kept only as history):**
  - Before the fix, the fee-change interleaving gave a `valid_window` CheckViolation (a 500).
  - With the post-lock instant replaced by the transaction-start time, the fee-change regression test was refused with 409 `fee_change_conflict`.
  - A reader probe showed `now()` returning no current fee and `statement_timestamp()` returning the new fee. The second repository test above now covers this permanently.

What these tests do not prove end to end: row 10 is service-level only (no route uses `quote_for_district` until checkout); row 12 is documentation, not a test. Most delivery tests run through the in-process test client on PostgreSQL; `tests/postgres/test_pg_delivery.py` covers the runtime role and real HTTP across two processes.

## Open items before module 12 can be marked Done

1. Human review of this change and of decisions D-D1 to D-D9.
2. The project owner's approved launch values for the three fees and the threshold (placeholders until then; RE-026 B1).
3. ~~Module 13 passes the discounted subtotal to the delivery quote (D-D5)~~: done in module 13 (2026-10-25, not committed). Module 14 uses `quote_for_district` at checkout and snapshots the fee.
4. TC-17 on the storefront; staging deployment.
