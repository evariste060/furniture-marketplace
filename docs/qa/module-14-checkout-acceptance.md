# Module 14 (orders and checkout) — acceptance record

| Field | Value |
| --- | --- |
| Module | 14 — orders & checkout (`docs/IMPLEMENTATION_PLAN.md` §5, "14 — orders & checkout"; §3 permission matrix; §7 Q11–Q16, Q18, Q21) |
| Requirements | PRD PR-05 (guest and account checkout; summary, delivery, fees and total before submission), PR-06 (order history and saved addresses), PR-07 (order statuses); RE-026 (server-side pricing, B1 delivery, B3 promotions, B7 guest lookup); ADR-002 (stock lifecycle); ADR-007 (money, rounding, VAT) |
| Linked tests | TC-06 (checkout as guest), TC-07 (checkout with account), TC-12 (cash on delivery, backend part), TC-13 (concurrent last unit), TC-14 (cancel and release stock) — definitions read from `docs/03_QA_UAT_and_Go_Live_Checklist.docx` |
| Branch | `feat/module-12-delivery` (current branch, on the owner's instruction). Not committed. |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-25 |
| Recommendation | **Not Done; ready for human review.** Implemented and verified at API and PostgreSQL level; D-O2 and D-O3 were decided on 2026-10-25 and are implemented. Open: the payments module (15), the storefront TC-06/TC-07 runs, PR review, CI and staging. |

## Acceptance criteria

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `POST /checkout` with a required `Idempotency-Key` | PASS | `tests/integration/test_checkout_api.py`: `test_tc06_guest_checkout_with_cash_on_delivery`, `test_the_header_is_required` |
| 2 | TC-06 guest checkout: address, delivery, fees, discount/tax treatment and total clear | PASS (API) | `test_tc06_guest_checkout_with_cash_on_delivery` (subtotal, delivery fee, total, VAT, zone, payment shown in the response), `test_a_promotion_is_snapshotted_allocated_and_redeemed` |
| 3 | TC-07 account checkout: saved address and order history | PASS (API) | `test_tc07_customer_checkout_with_a_saved_address_and_history`, `test_customer_checkout_with_an_inline_address` |
| 4 | Saved addresses only for their owner; guests inline only | PASS | `test_saved_addresses_belong_to_their_owner` |
| 5 | Lines repriced from the database; client amounts never trusted | PASS | `test_client_amounts_are_refused` (total, subtotal, delivery_fee, discount_total, tax_total, line prices, order number: 422), `test_a_changed_price_is_charged_at_the_current_price`, `test_a_request_names_exactly_one_address_and_no_amounts` |
| 6 | Promotion re-validated and its row locked; redemption recorded | PASS | `test_a_promotion_is_snapshotted_allocated_and_redeemed`, `test_a_code_that_stopped_applying_refuses_checkout`, `test_an_exhausted_limit_refuses_checkout`; the lock itself is module 13's `redeem()` (`test_two_checkouts_cannot_take_the_same_last_use`) |
| 7 | Delivery from the address district; threshold on the subtotal after discount; delivery never discounted | PASS | `test_a_promotion_is_snapshotted_allocated_and_redeemed` (205 000 − 20 500 = 184 500 < 200 000: fee charged), `test_districts_outside_the_area_and_cod_where_not_offered`, `test_delivery_configuration_failure_is_503` |
| 8 | total = subtotal − discount + delivery; VAT 18% extracted into `tax_total`, `vat_inclusive` snapshot | PASS | `test_tc06_*` (22 000 → VAT 3 356), `tests/unit/test_checkout_units.py` (`test_vat_is_extracted_from_the_inclusive_total`, `test_vat_never_lands_on_an_exact_half_and_refuses_negative_amounts`) |
| 9 | Order, items, history, redemption and holds created atomically; nothing partial on failure | PASS | `test_a_failure_late_in_checkout_writes_nothing` (no order, item, hold, redemption, history or payment row; the cart stays active) |
| 10 | Order snapshots immune to later catalogue changes | PASS | Lines store SKU, names, variant, specifications, warranty and prices; responses read only the snapshots (`order_detail`) |
| 11 | Response: order number, totals, payment methods for the zone | PASS | `test_tc06_*`, `test_districts_outside_the_area_and_cod_where_not_offered` |
| 12 | Payment method chosen at checkout (§7 Q15); card not offered (Q21); mobile money never shown as paid before module 15 (D-O2) | PASS | `test_invalid_requests_are_refused` (card, unknown method), `test_payment_methods_follow_the_zone_and_never_offer_card`, `test_mobile_money_orders_stay_unpaid_and_cannot_be_dispatched` (attempt stays `created`, no `succeeded_at`, dispatch refused, the hold keeps lapsing), `test_mobile_money_holds_15_minutes_and_cod_24_hours`, `test_q12_an_expired_unpaid_order_is_cancelled_with_its_code_released` |
| 13 | Non-sequential order numbers (§7 Q16) | PASS | `test_order_numbers_are_random_not_sequential`, `test_order_numbers_are_random_and_dated_in_kigali_time` |
| 14 | Idempotent replay; changed request refused; owner-scoped; concurrent retries | PASS | `test_a_retry_replays_the_order_and_writes_nothing`, `test_keys_are_scoped_to_their_owner`, `test_a_guest_retry_after_the_cart_closed_still_replays`, real HTTP: `tests/postgres/test_pg_checkout.py::test_concurrent_retries_with_one_key_place_one_order` |
| 15 | TC-13 concurrent last unit | PASS | `tests/postgres/test_pg_checkout.py::test_tc13_concurrent_checkouts_sell_the_last_unit_once` (6 buyers, two processes, runtime role: one order) |
| 16 | Holds (§7 Q11, Q13): mobile money 15 minutes, cash on delivery 24 hours | PASS | `test_mobile_money_holds_15_minutes_and_cod_24_hours` |
| 17 | Expired unpaid order cancelled, stock and code released (§7 Q12) | PASS | `test_q12_an_expired_unpaid_order_is_cancelled_with_its_code_released` (reason `payment_timeout`, attempt `expired`, redemption released `expired`) |
| 18 | COD: committed when staff confirm (Q13); succeeded on delivery (Q14); not paid before (TC-12) | PASS (backend) | `test_q13_confirming_cod_commits_stock_so_it_can_no_longer_be_cancelled`, `test_q14_delivering_cod_marks_the_payment_succeeded` |
| 19 | TC-14 cancellation releases stock and code exactly once; optional reason | PASS | `test_tc14_cancellation_releases_stock_and_code_exactly_once` (stock back, redemption released, payment cancelled, reason in history; a repeat is 409 and releases nothing) |
| 20 | Cancellation cutoff | PASS | Transitions allow `cancelled` only before dispatch (`test_q14_*`: 409 after delivery); committed stock is never released (`test_q13_*`) |
| 21 | Customer history and detail, ownership | PASS | `test_tc07_*`, `test_customers_see_only_their_own_orders` |
| 22 | Guest lookup; same 404 for a wrong phone and an unknown number | PASS | `test_guest_lookup_needs_the_number_and_the_phone` |
| 23 | Guest lookup rate-limited (ADR-008 S6: 5 failed per order number, 20 per IP, per 15 minutes; 429 with Retry-After; fail closed 503) | PASS | `backend/tests/integration/test_order_lookup_limits.py`: `test_the_policy_values_are_the_approved_ones`, `test_five_failures_per_order_number_then_429_until_the_window_ends`, `test_unknown_numbers_count_like_wrong_phones`, `test_successful_lookups_are_not_counted`, `test_twenty_failures_per_ip_across_order_numbers`, `test_an_unreachable_store_answers_503_for_hits_and_misses_alike`, `test_a_store_lost_while_counting_still_answers_the_404`; real Redis across two processes: `backend/tests/postgres/test_pg_checkout.py::test_concurrent_failed_lookups_are_counted_exactly_on_the_shared_store` |
| 24 | Staff list (status, from, to, payment_status) and detail, `orders:read` | PASS | `test_staff_list_filters_and_detail`, `test_staff_order_read_permissions` (admin, sales, operations 200; management, customer 403; anonymous 401), `test_sales_can_read_but_not_change_order_status` |
| 25 | Staff detail exposes no secrets or provider references | PASS | `test_staff_list_filters_and_detail` |
| 26 | Migration: request hash, upgrade/downgrade, `alembic check` | PASS | `tests/integration/test_checkout_migration.py` |
| 27 | Runtime role least privilege | PASS | `scripts/provision_runtime_role.py`; `test_order_fulfilment_tables_have_exactly_the_privileges_the_service_uses`; `test_runtime_role_cannot_delete_orders_or_payments` |
| 28 | Payments (initiation, callbacks, reconciliation) | Out of scope (module 15) | Mobile-money orders can be placed but not paid yet (D-O2) |
| 29 | Storefront TC-06/TC-07; PR, CI, staging | BLOCKED | Not committed; no storefront checkout; staging not available from here (§7 Q27) |

## Decisions (for the reviewer)

| # | Decision | Why / status |
| --- | --- | --- |
| D-O1 | Built on the current branch `feat/module-12-delivery`. | Owner's instruction. |
| D-O2 | **Decided by the project owner on 2026-10-25:** keep `mtn_momo` and `airtel_money` alongside `cash_on_delivery` where the zone allows it (§7 Q21); never `card`. Until the payments module (15) exists, a mobile-money order is never shown as paid: its attempt stays `created` ("not started"), no payment is processed, staff cannot dispatch it (no committed stock), and its 15-minute hold lapses into a `payment_timeout` cancellation that releases the stock and the promotion use. | Verified by the tests in criterion 12. Real payment processing remains module 15. |
| D-O3 | **Approved by the project owner on 2026-10-25 as ADR-008 S6 and implemented:** 5 failed lookups per order number and 20 per IP per 15 minutes, independent `order_lookup` counters, 429 with `Retry-After`, failures only, fail closed with 503. | Policy: ADR-008 S6. Verified implementation: criterion 23. |
| D-O4 | The Idempotency-Key is scoped to its owner (`user:<id>` or the guest token's pseudonym), stored with a SHA-256 of the normalised request; a reused key with another request is 409 `idempotency_key_reused`. Keys are kept with the order (no expiry approved). | Prevents one owner replaying another's order; matches the approved replay rule. |
| D-O5 | A cart with a flagged line, an empty cart, or a code that no longer applies refuses checkout (409 `cart_needs_attention` / `cart_empty`, 422 `promotion_not_applicable`) rather than dropping lines or the discount silently. | The customer must see the change before ordering (PR-05). |
| D-O6 | Cancelling an order turns an unpaid attempt (`created`, `pending`) into `cancelled`; an expired hold turns it into `expired`. Nothing is marked paid except cash on delivery on delivery (Q14). | No settlement is invented; mobile-money settlement is module 15. |
| D-O7 | Confirming an unpaid mobile-money order is allowed and commits nothing; its hold still lapses after 15 minutes. | Q13 commits stock on confirmation for cash on delivery only. |
| D-O8 | Guest lookup finds any order, including an account's, from its number and phone. | RE-026 B7 sets the proof (number + phone) without limiting it to guest orders. |
| D-O9 | VAT is extracted from the order total (merchandise after discount plus delivery, both VAT-inclusive) at order level; lines keep `tax_amount` 0. | ADR-007, RE-026 B2, §7 Q18. Per-line VAT display stays open (ADR-007). |
| D-O10 | Order numbers use the Kigali date and a 6-character suffix from 32 letters and digits (no 0/O/1/I), checked for collisions before use. | §7 Q16; numbers are read out by phone. |
| D-O11 | Staff `from`/`to` filters are instants (ISO date-times), inclusive. | Same convention as the audit-log filter. |
| D-O12 | After checkout the cart becomes `converted`; the guest token then answers 404 and a new cart starts on the next add. | Same lifecycle as a merged guest cart (module 11). |
| D-O13 | `orders:read` for administrator, sales and operations; management has none. | Plan §3 (approved). |

## Dependencies

- **Module 15 (payments):** initiation, callbacks and reconciliation for mobile money; `commit_order_reservations` on payment success; the payment status of mobile-money orders.
- **Module 12/13:** reused unchanged (`quote_for_district`, `quote`, `redeem`, `release_for_order`).

## Verification (2026-10-25)

All database tests ran on `rwanda_ecommerce_test` only (Docker PostgreSQL on 127.0.0.1:55432). The development database was not migrated or seeded. Run from `backend/` with uv.

| Command | Result |
| --- | --- |
| `pytest tests/integration/test_checkout_api.py` | 46 passed |
| `pytest tests/unit/test_checkout_units.py tests/integration/test_checkout_migration.py` | 16 passed |
| `pytest tests/postgres/test_pg_checkout.py` (real HTTP, two processes, runtime role) | 3 passed |
| `pytest tests --ignore=tests/postgres` (full, first run) | 1220 passed, 2 failed: two module 13 migration tests assumed the promotions revision was head; corrected to target their own revision |
| `pytest tests/postgres` (full, first run) | 88 passed, 1 failed: `test_runtime_role_cannot_create_delete_or_rewrite_reservations` asserted the runtime role cannot insert holds, which checkout now needs; renamed and narrowed to deletes and rewrites |
| `pytest tests --ignore=tests/postgres` (full, rerun after those fixes) | **1222 passed, 0 failed** |
| `pytest tests/postgres` (full, rerun) | **89 passed, 0 failed** |
| After D-O2 and D-O3 (2026-10-25): `pytest tests/integration/test_order_lookup_limits.py` | 7 passed |
| After D-O2 and D-O3: focused `test_checkout_api.py` lookup, mobile-money, hold and expiry tests (`-k "lookup or limit or policy or store or mobile_money or q12 or holds"`, with the limit file) | 12 passed |
| After D-O2 and D-O3: `pytest tests/postgres/test_pg_checkout.py` (adds concurrent failed lookups on real Redis) | 4 passed |
| After D-O2 and D-O3: `pytest tests --ignore=tests/postgres` (full) | **1230 passed, 0 failed** |
| After D-O2 and D-O3: `pytest tests/postgres` (full) | **90 passed, 0 failed** |
| After D-O2 and D-O3: `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (213 files) |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (212 files) |
| `mypy .` (repository root) | 4 errors, all pre-existing and in files this module does not touch (`app/repositories/catalog.py:63` twice, migrations `c3a8e5f1d2b4` and `528e6436c34e`) |
| `alembic heads`, `alembic history`, `uv lock --check` | Single head `f3a8c6e1b5d9` (after `d2f7a9c4e8b1`); lockfile unchanged |
| `git diff --check` | Clean |

## Open items before module 14 can be marked Done

1. Human review of this change and of decisions D-O1 to D-O13.
2. D-O2 and D-O3: decided and implemented 2026-10-25; nothing further.
3. Module 15 payments; TC-06/TC-07 on the storefront; PR review, CI and staging.
4. Migrating the development database (owner account), then `provision_runtime_role.py`.
