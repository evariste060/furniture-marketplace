# Module 13 (promotions and discounts) — acceptance record

| Field | Value |
| --- | --- |
| Module | 13 — promotions (`docs/IMPLEMENTATION_PLAN.md` §5, "13 — promotions"; §3 permission matrix; §7 Q20, Q25, Q26) |
| Requirements | PRD PR-12 (discounts); RE-026 B3 (promotion rules), B5 (table columns, approved with the plan on 2026-10-23), B6 (only administrators change; management views); ADR-007 (money and rounding) |
| Linked tests | TC-06 (discount code applied to the cart) |
| Branch | `feat/module-12-delivery` (current branch; the plan names `feat/module-13-promotions`, but branches are created only on the owner's instruction). Not committed. |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-25 |
| Recommendation | **Not Done; ready for human review.** The backend is implemented and verified at API and PostgreSQL level. Checkout (module 14) does not exist yet, so redemptions are recorded by a tested service function that checkout must call; see "Dependencies". |

## Acceptance criteria

| # | Criterion (plan §5) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `POST /cart/apply-code`, `DELETE /cart/code` | PASS | `test_apply_replace_remove_and_repeat`, `test_codes_that_cannot_be_used_are_refused`, `test_a_code_needs_a_cart`, `test_staff_accounts_cannot_apply_codes`, `test_guest_carts_take_codes_and_merge_carries_them`; real HTTP: `test_customers_apply_and_remove_codes_over_http` |
| 2 | Staff `GET /staff/promotions`, `GET /staff/promotions/{id}` (`promotions:read`), `POST`, `PATCH` (`promotions:manage`) | PASS | `test_create_*`, `test_list_get_and_status_filter`, `test_update_status_kind_and_targets_with_audit` |
| 3 | B6: management views only; others forbidden | PASS | `test_management_can_view_promotions_but_not_change_them`, `test_other_roles_and_anonymous_callers_are_refused` (sales, operations, customer 403; anonymous 401), `test_management_can_view_but_not_change_promotions` (real HTTP), `tests/unit/test_roles.py` |
| 4 | `discounts` columns; `value` and `rules` dropped; code required, upper-case, unique ignoring case | PASS | `test_head_schema_has_the_approved_columns_and_constraints`, `test_database_constraints_refuse_bad_rows`, `test_codes_are_unique_ignoring_case`, `test_codes_are_trimmed_and_upper_cased` |
| 5 | `discount_targets`: exactly one of category, brand, product; `variant_id` dropped | PASS | Same migration tests; `test_targets_name_exactly_one_thing_and_are_not_repeated` |
| 6 | `discount_redemptions`: canonical phone, status, release fields; unique (discount, order) | PASS | Same migration tests; `test_guest_limits_count_by_canonical_phone` |
| 7 | `carts.discount_id` | PASS | Same migration tests; cart tests above |
| 8 | Migration safe for legacy data; upgrade, downgrade, re-upgrade; `alembic check` | PASS | `tests/integration/test_promotions_migration.py` (mappable rows carried over and back; every refusal changes nothing) |
| 9 | One code per order | PASS (cart) | A new code replaces the old one (`test_apply_replace_remove_and_repeat`); unique (discount, order) on redemptions. One code per **order** is enforced at checkout (module 14), which takes the cart's single code. |
| 10 | Eligible merchandise only, never delivery | PASS | `test_targets_product_brand_and_category_with_subcategories`, `test_delivery_is_never_discounted_and_uses_the_discounted_threshold_basis` |
| 11 | Category targets include subcategories | PASS | `test_targets_product_brand_and_category_with_subcategories` (recursive query) |
| 12 | ADR-007 rounding: 10% off 1 005 pays 904 | PASS | `test_adr_007_example_10_percent_off_1005_pays_904` (unit), `test_adr_007_example_through_the_cart` (API), `test_round_half_down` |
| 13 | `max_discount` caps; a total never goes negative | PASS | `test_discount_amount`, `test_max_discount_and_fixed_amount_never_make_a_total_negative` |
| 14 | Proportional split; remainder on the largest line; sums exact; ineligible lines get 0 | PASS | `test_allocation_*` (unit), `test_allocation_across_lines_sums_to_the_discount`, targeting test (ineligible line 0) |
| 15 | Minimum subtotal, status, Kigali-time window | PASS (minimum on the whole merchandise subtotal, D-P2; formal RE-026 amendment pending) | `test_the_minimum_compares_the_whole_merchandise_subtotal_for_all_codes`, `test_a_targeted_code_meets_its_minimum_on_the_whole_cart`, `test_the_minimum_ignores_delivery_and_unpriced_lines`, `test_codes_that_cannot_be_used_are_refused`, `test_the_window_starts_inclusive_and_ends_exclusive`, `test_the_window_boundary_uses_database_time`, `test_kigali_local_time_is_stored_in_utc`, `test_create_normalises_the_code_stores_kigali_dates_in_utc_and_audits` |
| 16 | Ambiguous or missing local times refused, not guessed | PASS | `test_ambiguous_and_missing_local_times_are_refused_not_guessed` (Kigali has none; proven on a daylight-saving zone) |
| 17 | `tzdata` dependency (Windows) | PASS | `backend/pyproject.toml`, `uv.lock`; the unit tests resolve `Africa/Kigali` on Windows |
| 18 | Usage counts active redemptions only | PASS | `test_the_total_limit_counts_active_redemptions_only` |
| 19 | Total limit under a row lock; concurrent last use | PASS (service level) | `test_two_checkouts_cannot_take_the_same_last_use` (deterministic: B waits on A's lock, then is refused), `test_many_concurrent_checkouts_take_each_use_once`, `test_concurrent_redemptions_on_the_runtime_role_take_each_use_once`. Real PostgreSQL locks; no checkout route exists yet (module 14). |
| 20 | Per-customer limit by account or phone (registered), by phone (guests), §7 Q26 | PASS | `test_the_per_customer_limit_counts_by_account_or_phone`, `test_guest_limits_count_by_canonical_phone` |
| 21 | Cancellation before dispatch releases the redemption | PASS | `test_cancellation_before_dispatch_releases_the_redemption_once` (through the staff status route), `test_a_failed_cancellation_keeps_the_redemption` |
| 22 | Reservation expiry releases the redemption | PASS | `test_reservation_expiry_releases_the_redemption`, `test_the_expiry_job_releases_redemptions_as_the_runtime_role` (the real job, runtime role) |
| 23 | Release idempotent; reasons `cancelled`/`expired` | PASS | Same tests; `test_release_reason_and_amount_are_validated` |
| 24 | Applying a code reserves nothing | PASS | `test_apply_replace_remove_and_repeat` (no redemption rows) |
| 25 | Discounted subtotal feeds the free-delivery threshold; delivery not discounted | PASS | `test_delivery_is_never_discounted_and_uses_the_discounted_threshold_basis` (200 500 − 1 000 = 199 500 is below 200 000, so the fee is charged in full) |
| 26 | Server prices only | PASS | `test_a_code_needs_a_cart` (an `amount` field is refused); totals come from the pricing service |
| 27 | Runtime role least privilege | PASS | `scripts/provision_runtime_role.py`; `test_promotion_tables_have_exactly_the_privileges_module_13_uses`; `test_runtime_role_privileges_on_promotion_tables`; ADR-006 |
| 28 | Redemption at checkout | BLOCKED (module 14) | `promotion_service.redeem()` exists and is tested; no checkout route exists to call it |
| 28a | Abuse limit on `POST /cart/apply-code` (code guessing) | PASS (ADR-008 S5, approved 2026-10-25) | `test_refused_codes_are_limited_with_retry_after_and_the_window_expires`, `test_not_applicable_codes_count_too`, `test_successful_applies_and_removal_never_use_the_budget`, `test_the_limit_follows_the_cart_owner_across_networks`, `test_the_network_limit_covers_guests_and_customers_alike`, `test_the_code_limit_is_skipped_with_a_warning_when_redis_is_down` |
| 29 | TC-06 on the storefront; PR, CI, staging | BLOCKED | Not committed; no storefront promotion UI; staging not available from here (§7 Q27) |

## Decisions (for the reviewer)

| # | Decision | Why / status |
| --- | --- | --- |
| D-P1 | Built on the current branch `feat/module-12-delivery`, not `feat/module-13-promotions`. | Branches are created only on the owner's instruction. |
| D-P2 | **Decided by the project owner on 2026-10-25 (implementation decision) and implemented:** `min_subtotal` is compared with the **whole merchandise subtotal before discount, without delivery**, whatever the promotion's targets: every priced line counts, eligible or not; unavailable or unpriced lines and the delivery fee do not. The discount itself still applies to eligible lines only. | RE-026 B3 ("minimum order amount") did not say which amount; this decision is the reading recommended on 2026-10-25. It was given as an implementation instruction; **a formal amendment of the RE-026 B3 record by the Product Owner is not yet recorded** and should confirm it. Evidence: `test_the_minimum_compares_the_whole_merchandise_subtotal_for_all_codes` (9 999 refused, 10 000 accepted), `test_a_targeted_code_meets_its_minimum_on_the_whole_cart` (eligible 1 000 below a 10 000 minimum, whole cart 10 000: applies, discount on the eligible line only), `test_the_minimum_ignores_delivery_and_unpriced_lines`. |
| D-P3 | A code applies from `starts_at` (inclusive) to `ends_at` (exclusive), against database time. A date-time without an offset is Kigali local time; one with an offset is taken as given. Responses show Kigali time (+02:00). | B3 says the dates are in Kigali time but not how the bounds work; this is the convention used elsewhere (delivery fee windows). |
| D-P4 | When the largest line cannot absorb the whole rounding remainder (only possible with line amounts of a few RWF), the rest goes to the next largest line, so no line is discounted beyond its own amount. Ties go to the earliest line in cart order. | Extends the approved "remainder on the largest line" rule only where it would break the per-line invariant. |
| D-P5 | Unknown, draft and disabled codes get the same 422 `promotion_unavailable`; an active code that does not apply gets 422 `promotion_not_applicable` with its reason. A code that stops applying after it was applied stays on the cart with `applied: false` and discounts nothing. | Draft and disabled codes are not revealed; totals are always recomputed, never stale. |
| D-P6 | On merge, the customer's own code wins; otherwise the guest cart's code is carried over (still re-checked). | Keeps the customer's choice; nothing is lost on sign-in. |
| D-P7 | Status: draft → active or disabled; active ↔ disabled; never back to draft (409). | B6 approves create, edit, activate, deactivate; "draft" means never activated. |
| D-P8 | Per-customer limit for a registered customer counts the account and both the order's phone and the account's phone. | §7 Q26: "the same person cannot reuse a code by checking out as a guest". |
| D-P9 | A payment failure does not release a redemption; only cancellation before dispatch and reservation expiry do. | Only those two releases are approved (B3). |
| D-P10 | **Approved by the project owner on 2026-10-25 as ADR-008 S5 and implemented:** 20 refused codes per 15 minutes per client network and per cart owner; beyond it 429 `rate_limited` with `Retry-After`; fail open on a Redis outage, as S3; successful applies are not counted; `DELETE /cart/code` is never limited. | Reuses `CartRateLimiter` and the S1/S3 network and owner keys; the network key is shared by guests and customers on it, so switching identity does not reset it. Evidence: the six S5 tests listed in ADR-008 S5. |
| D-P11 | `targets` in PATCH replaces the whole set (rows deleted and re-inserted; DELETE granted on `discount_targets` only). | Simplest consistent edit; history of targets is not required. |
| D-P12 | Deleting a category or brand that a promotion targets is refused (409 `category_in_use` / `brand_in_use`, from the RESTRICT foreign key); the message mentions products and subcategories only. | Existing catalogue behaviour; message wording is a minor follow-up. |

## Dependencies

- **Module 14 (checkout)** must, in its order transaction: take the cart's code, re-quote it with `promotion_service.quote()` on the repriced lines, call `promotion_service.redeem()` (row lock, limit checks, canonical phone), snapshot `orders.discount_id`, `discount_code_snapshot`, `discount_name_snapshot` and `discount_total`, and write each line's allocation to `order_items.discount_amount`.
- **Module 12 (delivery)**: the cart quote now passes the subtotal after discount (D-D5 satisfied); checkout must do the same with `quote_for_district`.
- **Payment and order lifecycle (modules 14–15)**: §7 Q12 makes an expired unpaid order `cancelled`; the expiry job already releases the redemption when the reservation expires.

## Verification (2026-10-25)

All database tests ran on `rwanda_ecommerce_test` only (Docker PostgreSQL on 127.0.0.1:55432) (per-test schemas, and the tests/postgres harness on its own runtime role). The development database was not migrated or seeded. Run from `backend/` with uv.

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_promotion_units.py` | 58 passed |
| `pytest tests/integration/test_promotions_api.py` (before D-P2 and S5) | 41 passed (including the two real-lock concurrency tests) |
| `pytest tests/integration/test_promotions_migration.py` | 13 passed |
| `pytest tests/postgres/test_pg_promotions.py` (real HTTP, runtime role, the expiry job) | 5 passed |
| `pytest tests --ignore=tests/postgres` (full, first run) | 1150 passed, 1 failed: `test_delivery_migration.py::test_downgrade_then_upgrade_keeps_legacy_zones_and_fee_history` assumed the delivery revision was head; corrected to upgrade to its own revision. |
| `pytest tests --ignore=tests/postgres` (full, rerun 2026-10-25 after that fix) | **1151 passed, 0 failed** (includes both migration test files) |
| `pytest tests/postgres` (full, rerun 2026-10-25) | **86 passed, 0 failed** |
| After D-P2 and S5 (2026-10-25): `pytest tests/integration/test_promotions_api.py tests/integration/test_cart_security.py tests/unit/test_promotion_units.py` | 131 passed (promotions API 50, including 3 D-P2 and 6 S5 tests; cart security 23, S1/S3 unchanged after the limiter refactor; units 58) |
| After D-P2 and S5: `pytest tests --ignore=tests/postgres` (full) | **1160 passed, 0 failed** |
| After D-P2 and S5: `pytest tests/postgres` (full) | **86 passed, 0 failed** |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (203 files) |
| `mypy .` (repository root) | 4 errors, all pre-existing and in files this module does not touch (`app/repositories/catalog.py:63` twice, migrations `c3a8e5f1d2b4` and `528e6436c34e`) |
| `alembic heads`, `alembic history`, `uv lock --check` | Single head `d2f7a9c4e8b1` (after `b6f1d3a9c8e4`); lockfile consistent (`tzdata` added as a direct dependency) |
| `git diff --check` | Clean |

## Open items before module 13 can be marked Done

1. Human review of this change and of decisions D-P1 to D-P12.
2. A formal amendment of the RE-026 B3 record confirming the D-P2 basis (decided and implemented 2026-10-25).
3. D-P10 / S5: approved and implemented 2026-10-25; nothing further.
4. Module 14 checkout calls `quote()` and `redeem()` in its order transaction and snapshots the discount on the order and its lines (row 28).
5. TC-06 on the storefront; PR review, CI and staging.
6. Migrating the development database (owner account), then `provision_runtime_role.py`.
