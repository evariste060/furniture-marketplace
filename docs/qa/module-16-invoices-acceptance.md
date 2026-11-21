# Module 16 (invoices) — acceptance record

| Field | Value |
| --- | --- |
| Module | 16 — invoices (`docs/IMPLEMENTATION_PLAN.md` §5, "16 — invoices"; §3 permission matrix; §7 Q19) |
| Requirements | PRD PR-14 (Finance approves VAT display, invoice format and the RRA EBM approach before release; no EBM claim until verified); ADR-007 (accepted: whole RWF, VAT-inclusive prices, VAT = amount × 18 / 118 rounded once to the nearest whole RWF, an exact half down); ADR-002 (lock order, payment consistency) |
| Linked tests | TC-18 (invoice and delivery note: approved template, correct customer/order totals, finance-approved tax display) |
| Branch | `feat/module-16-invoices`, created from `dev` at `34557d7` (Module 15 merged). The Module 16 changes are pending PR into `dev`. |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-26 |
| Recommendation | **Not Done; ready for human review.** Implemented and verified on the isolated test database. TC-18 cannot pass until Finance approves the invoice template and tax display (PR-14). |

## Owner decisions applied (2026-10-26)

| # | Decision | Implementation |
| --- | --- | --- |
| 1 | VAT is order-level only, ADR-007 exactly; no per-line VAT | `vat_amount = vat_component(order.total)` (`app/core/money.py`, exact fractions); it must equal the order's stored `tax_total`, or issuance is refused |
| 2 | Missing or invalid seller legal name, TIN or address refuses issuance; no number used | Checked before the counter is touched; refusal logged and audited (`invoice.issue`, `failure`, `seller_details_missing`) |
| 3 | Issue atomically with the payment success or the COD delivery (§7 Q19); downloads never issue | `issue_for_order` runs inside the webhook success transaction, the staff COD confirmation, and the `delivered` status change, after the order's locks |
| 4 | Delivery note: order number, recipient, delivery address, items; no prices or payment details | `render_delivery_note`; eligibility below is an engineering reading (see open decision O-2) |
| 5 | Unresolved, late or unconfirmed payment events issue nothing | Only the matched, committed success path calls issuance |

## Project owner decisions on open items (not formal approvals by the responsible owners)

The project owner has decided how the following are handled for now. None of them is a formal approval by the responsible owner named in the table; each stays open until that owner approves it. No approver or approval date is recorded because none has been given.

| # | Decision | Approval still required from | Status |
| --- | --- | --- | --- |
| P-1 | The implemented delivery-note eligibility rules (Design, "Delivery-note eligibility") are the project owner's **proposed default** | Product/Operations owner | Proposed default; not approved (O-2) |
| P-2 | Invoice recovery uses a **dedicated `invoices:recover` permission** (project owner's preference) instead of `payments:manage`. Following the established convention (`app/core/roles.py`, ADR-006, plan §3) it is held by administrator only, since administrator holds every declared permission | Any role other than administrator requires a recorded approval; none is assigned | Implemented; administrator only (O-3) |
| P-3 | A recovered invoice keeps the recovery date as its issue date and is numbered in that Kigali year | Finance | Provisional; not confirmed (O-9) |
| P-4 | TC-18 stays blocked until Finance approves the actual invoice PDF, its template and the tax display (PR-14) | Finance | Blocked (O-1) |

## Acceptance criteria

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GET /customers/me/orders/{id}/invoice` (owner), `GET /staff/orders/{id}/invoice` (`orders:read`), `GET /staff/orders/{id}/delivery-note` (`orders:fulfil`) | PASS | `tests/integration/test_invoices_api.py`: `test_customers_download_only_their_own_invoices`, `test_staff_invoice_and_delivery_note_permissions` (administrator, sales, operations, management; expectations read from `ROLE_PERMISSIONS`), `test_staff_routes_refuse_customers_and_anonymous_callers` |
| 2 | Ownership concealed: another customer's order is the same 404 as a missing one; ownership is in the service query | PASS | `test_customers_download_only_their_own_invoices` (identical 404 bodies); `invoice_service.customer_invoice` filters on `Order.user_id` |
| 3 | Issued with a verified payment success, once | PASS | `test_a_verified_payment_success_issues_one_invoice` (repeated success: still one invoice, counter 1); real HTTP on the runtime role: `tests/postgres/test_pg_invoices.py::test_a_paid_order_is_invoiced_and_downloadable_on_the_runtime_role` |
| 4 | Issued when a COD order is delivered, not before | PASS | `test_a_cash_on_delivery_order_is_invoiced_on_delivery` (confirmed and dispatched: none; delivered: one) |
| 5 | Nothing for pending, failed, cancelled, mismatched, unknown or late payments | PASS | `test_unconfirmed_outcomes_issue_nothing` (3 cases), `test_a_mismatched_or_unknown_success_issues_nothing`, `test_a_late_success_issues_nothing` (counter never created) |
| 6 | Missing or invalid seller details refuse issuance, use no number, keep the payment | PASS | `test_missing_seller_details_refuse_the_invoice_but_keep_the_payment` (attempt succeeded; no invoice; no counter; audit `failure`; endpoint 409; next invoice is still 000001), `test_an_invalid_stored_seller_setting_refuses_the_invoice`; cash on delivery: `tests/integration/test_invoice_recovery.py::test_a_cod_delivery_without_seller_details_is_refused_then_recovered_unchanged` (the delivery and the cash payment commit; no invoice, no counter; the refusal is audited with the delivering staff member as actor; recovery 409 while unset, then 201 once set; order and payment fields identical before and after recovery; repeat 200) |
| 7 | Seller details are settings keys with validation and the existing permissions | PASS | `test_seller_settings_are_managed_like_other_settings` (422, 403 for management, 200 for administrator); `tests/unit/test_invoice_units.py::test_seller_settings_are_validated_when_read` (13 cases) |
| 8 | Gapless, never-reused yearly numbers under concurrency (real PostgreSQL) | PASS | `tests/integration/test_invoice_numbering.py`: `test_concurrent_issuance_for_different_orders_is_gapless` (12 workers released at a barrier, the year's counter row created concurrently: numbers exactly 000001–000012, counter 12), `test_concurrent_issuance_for_one_order_issues_once` (8 workers: 1 issued, 7 already issued) |
| 9 | A rollback returns its number; committed numbers are never reused | PASS | `test_a_rolled_back_issuance_returns_its_number_to_the_waiting_transaction` (the second transaction is observed waiting on the lock in `pg_stat_activity`, then gets 000001 after the first rolls back), `test_committed_numbers_are_never_reused_or_duplicated` (cancelling an invoiced order frees nothing; duplicate number and second invoice per order refused by the database), `test_a_failure_after_the_number_is_taken_rolls_everything_back` (invoice, counter and payment success all roll back; the provider's retry gets 000001) |
| 10 | Per-year sequence in Kigali time; exhausted range refused without change | PASS | `test_each_kigali_year_has_its_own_sequence` (31 Dec 22:30 UTC is INV-2031), `test_an_exhausted_year_refuses_without_changing_the_counter` |
| 11 | VAT extraction and rounding (ADR-007) | PASS | `tests/unit/test_invoice_units.py`: boundary cases (0, 1, 3, 4, 118, 12 000, the storable maximum), a Decimal `ROUND_HALF_DOWN` cross-check for every total 0–49 999 and the top 2 000 storable totals, the half-down rule itself, and proof that an exact half cannot arise from a whole-RWF total |
| 12 | Invoice values agree across order, database, snapshot and PDF | PASS | `test_a_verified_payment_success_issues_one_invoice` (row = order = snapshot; lines + delivery = total), `test_the_invoice_pdf_matches_the_order_and_handles_long_and_accented_text` |
| 13 | Immutable snapshot; repeated downloads never issue again | PASS | `test_downloads_render_the_issued_snapshot_and_never_issue_again` (seller settings, product name and recipient changed afterwards: identical PDF bytes on every download, customer and staff; one invoice, counter 1) |
| 14 | Valid PDFs: `application/pdf`, safe filename, required fields, long text, page breaks, accented text, escaped user text, deterministic output | PASS | `test_customers_download_only_their_own_invoices` (headers, `%PDF-`/`%%EOF`); units `test_the_invoice_shows_the_required_fields_and_reconciled_totals`, `test_user_text_is_never_markup_and_undrawable_characters_become_question_marks`, `test_long_invoices_break_across_pages_with_totals_at_the_end` (70 lines, header repeated per page), `test_rendering_is_deterministic` |
| 15 | Delivery note: no prices or payment details; follows the fulfilment workflow | PASS for the implemented rule; **eligibility provisional, pending Product/Operations approval (P-1, O-2)** | `test_the_delivery_note_follows_the_fulfilment_workflow_and_shows_no_prices`, `test_no_delivery_note_for_unpaid_or_cancelled_orders`, unit `test_the_delivery_note_has_no_prices_or_payment_details`; every reachable state: `tests/integration/test_invoice_recovery.py::test_delivery_note_eligibility_for_every_reachable_state` |
| 16 | Migration with downgrade; no model drift | PASS | `tests/integration/test_invoice_migration.py` (round trip, unique and foreign-key constraints, `alembic check`) |
| 17 | Runtime role least privilege | PASS | `invoices` SELECT, INSERT; `invoice_counters` SELECT, INSERT, UPDATE: `tests/unit/test_runtime_role_grants.py::test_invoice_tables_have_exactly_the_privileges_module_16_uses`, invoices added to the append-only check; `tests/postgres/test_pg_invoices.py::test_the_runtime_role_cannot_change_or_remove_invoices` (UPDATE/DELETE invoices, DELETE counters refused) |
| 18 | No EBM claim (PR-14) | PASS | The PDF never mentions EBM (`test_the_invoice_shows_the_required_fields_and_reconciled_totals`) |
| 19 | Recovery of a refused invoice: administrator only, seller details validated, order and payments unchanged, existing counter and unique-order protections, idempotent, audited | PASS; **dedicated `invoices:recover`, administrator only (P-2, O-3); recovery date provisional, pending Finance (P-3, O-9)** | `tests/integration/test_invoice_recovery.py`: `test_an_administrator_recovers_a_refused_invoice_once` (409 while the seller is unset, no number; then 201 INV-…-000001, order status and payment unchanged, audit `recovery: true`; repeat 200 with the same number), `test_only_invoice_recoverers_can_recover` (sales, operations, management 403, each denial audited as `auth.access_denied`; anonymous 401; unknown 404; malformed id 422), `test_invoices_recover_not_payments_manage_gates_recovery` (a role given only `payments:manage` is refused; given `invoices:recover` it recovers once, audited with that actor; a repeat returns the same invoice), `test_unpaid_orders_cannot_be_invoiced_by_recovery` (409 `invoice_not_issuable`, audited), `test_recovery_refuses_amounts_that_do_not_reconcile`, `test_concurrent_recoveries_issue_one_invoice` (6 sessions at a barrier: one issued, five returned it, counter 1); real HTTP on the runtime role: `tests/postgres/test_pg_invoices.py::test_a_refused_invoice_is_recovered_once_on_the_runtime_role` |
| 20 | Staff COD-confirmation issuance | PASS | Unreachable through the API by design: checkout creates a COD attempt `pending`, and the only way to `delivered` (`dispatched → delivered`) settles it to `succeeded` and issues the invoice in the same transaction (`test_delivery_always_settles_a_cod_payment_so_confirmation_never_needs_to`: the later confirmation is a no-op, one invoice). The defensive call in `confirm_cod` is kept, so any success issues an invoice, and is covered directly on a state built in the database: `test_staff_cod_confirmation_of_an_unsettled_delivered_order_issues_the_invoice` (one invoice, idempotent) |
| 21 | TC-18: approved template and finance-approved tax display | **BLOCKED** (P-4, O-1) | PR-14: Finance has not approved the actual invoice PDF, its template or the tax display; the layout is an engineering draft |
| 22 | Storefront invoice links; PR review, CI, staging | BLOCKED | Pending PR into `dev`; no storefront pages; staging not available from here |

## Design

- **Issuance point and transactions (§7 Q19).** `app/services/invoice_service.issue_for_order` is called, inside the caller's transaction and after the order's locks (advisory lock, then the order row), from: the webhook success branch of `payment_service._apply` (after the stock commit and the attempt's `succeeded`); `PaymentService.confirm_cod`; and the `delivered` branch of `order_service._apply_payment_rules` for cash on delivery. The only new lock is the year's counter row, always taken after the order locks, so no new lock cycle is possible. Downloads read the stored invoice and never issue.
- **Numbering.** `INV-YYYY-NNNNNN`, the year in Kigali time at issuance (`statement_timestamp()`). One `INSERT ... ON CONFLICT (year) DO UPDATE SET last_number = last_number + 1 WHERE last_number < 999999 RETURNING last_number` takes the number and holds the row lock until the issuing transaction ends; a concurrent first insert for a new year waits on the primary key. The counter increment, the invoice row and its audit record commit or roll back together, so per year the committed numbers are exactly 1..`last_number`. Unique `order_id` and `invoice_number` are the database's final boundary; the runtime role cannot update or delete invoices or delete counters.
- **Refusal.** Seller details missing or invalid, stored amounts that do not reconcile (`line_subtotal − discount = line_total`, Σ lines = subtotal − discount, + delivery fee = total, VAT = `tax_total`), or an exhausted year: nothing is issued, no number is used, the payment or delivery still commits, and the refusal is logged and audited. An unexpected error after the number is taken rolls the whole transaction back (the webhook answers 500 and the provider's retry reprocesses it).
- **Snapshot (version 1).** Invoice number, issue time and Kigali date, currency; seller legal name, TIN and address; customer: recipient name and delivery address lines (no phone or email); order number, order date, payment method; lines (SKU, description, quantity, unit price, line subtotal, discount, line total); subtotal, discount (and code), delivery fee, total; VAT rate, amount, basis and rounding.
- **PDFs.** ReportLab 4.5.1 (pure-Python wheel; dependencies Pillow and charset-normalizer, already present), rendered in memory, deterministic (`invariant`), checked for `%PDF-`/`%%EOF` before returning. User text is XML-escaped; characters outside Windows-1252 are drawn as "?". `Content-Disposition: attachment` with a filename built from the invoice or order number only; `Cache-Control: no-store`.
- **Delivery-note eligibility (implemented rule, provisional pending Product/Operations approval: P-1, O-2).** Available when the order is not cancelled and all of its stock reservations are `committed` or `fulfilled`. Against the approved state machine (`received → confirmed|cancelled`, `confirmed → processing|cancelled`, `processing → dispatched|cancelled`, `dispatched → delivered`) and the stock rules, that is: a paid mobile-money order in `received`, `confirmed`, `processing`, `dispatched` or `delivered`; a cash-on-delivery order in `confirmed` (Q13 commits its stock), `processing`, `dispatched` or `delivered`. Not available: an unpaid mobile-money order in any status, a `received` cash-on-delivery order, and any `cancelled` order. A committed order cannot be cancelled (releasing committed stock is refused, 409), so `cancelled` never coincides with committed stock; the check is defensive.
- **Recovery.** `POST /api/v1/staff/orders/{order_id}/invoice` (`invoices:recover`, administrator only) calls `invoice_service.recover_invoice`: in one transaction it takes the order's locks, returns an existing invoice unchanged (200, no number), refuses an order without a succeeded payment or a cancelled one (409 `invoice_not_issuable`, audited as a conflict), otherwise calls `issue_for_order` with the succeeded attempt's method (same seller check, amount reconciliation, counter upsert and unique-order constraint; audited `invoice.issue` with `recovery: true`). A refusal commits only its audit record and answers 409 with the reason; no number is used. It never changes the order or its payments. The issue date is the recovery date, and the number belongs to that Kigali year.

## Open decisions and gaps (for the reviewer)

| # | Item | Why / status |
| --- | --- | --- |
| O-1 | **Finance approval of the invoice PDF, template and tax display (PR-14, TC-18)** | The layout, field set and wording are an engineering draft. Finance must approve the actual rendered PDF, its template and the tax display before release; TC-18 stays blocked until then (P-4). |
| O-2 | **Delivery-note eligible states — proposed default, not approved** | Plan §3 lists only "delivery note" under `orders:fulfil`; PRD, Technical Plan and TC-18 name no states. The implemented rule (see Design) is derived from the dispatch precondition. It is the project owner's proposed default (P-1); it is not approved until the Product/Operations owner approves it. Recipient phone and delivery instructions are excluded because the approved field list does not include them. |
| O-3 | **Recovery permission — dedicated `invoices:recover`, administrator only** | Recovery first used `payments:manage`; on the project owner's preference it now uses a dedicated `invoices:recover` permission (P-2), so `payments:manage` alone no longer allows it (`test_invoices_recover_not_payments_manage_gates_recovery`). Under the established convention administrator holds every declared permission and no other role receives one without a recorded approval; no other role has it. Giving it to another role (for example a finance role, which does not exist) is an open decision, not assumed. Orders to recover are found through the audit log (`invoice.issue`, status `failure`). |
| O-4 | **Characters outside Windows-1252** | The built-in PDF fonts cannot draw them; they print as "?". Embedding a Unicode font (a licensed TTF in the repository) would remove this; not done without approval. |
| O-5 | **Customer fields on the invoice** | Recipient name and delivery address only; phone and email are left out to minimise personal data. Finance may require more (for example a buyer TIN for business customers, which no requirement defines). |
| O-6 | **Guest invoices** | The approved endpoints serve signed-in customers and staff; a guest (order number + phone) has no invoice route. |
| O-7 | **EBM** | Not implemented; no claim made (PR-14). |
| O-8 | **TIN format** | Only shape is checked (letters, digits, spaces, hyphens, at most 40); no RRA format is assumed. |
| O-9 | **Recovered invoice date — provisional, not confirmed** | A recovered invoice carries the recovery date as its issue date and that Kigali year's number, not the payment date (§7 Q19 says issued "when payment succeeds"). The project owner has kept this provisionally (P-3); Finance must confirm it. |
| O-10 | **Orders paid before Module 16 is deployed — Finance decision needed** | Orders paid before Module 16 is deployed (mobile-money successes and delivered cash-on-delivery orders) have no invoice: issuance happens only with a payment success or delivery recorded after deployment. Whether to issue invoices for them retroactively, and with which issue date and year, is a Finance decision that has not been made; no policy is assumed. The recovery endpoint could issue them technically, but it must not be used for that until Finance decides. |

## Verification (2026-10-26)

All database tests ran on `rwanda_ecommerce_test` only (Docker PostgreSQL on 127.0.0.1:55432; Docker Desktop was started for this, which starts the existing containers and changes no data). The development database was not migrated or seeded. Run from `backend/` with uv; the full suites were not run.

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_invoice_units.py` | 33 passed |
| `pytest tests/integration/test_invoices_api.py` | 22 passed |
| `pytest tests/integration/test_invoice_numbering.py` | 6 passed |
| `pytest tests/integration/test_invoice_migration.py tests/integration/test_payment_migration.py` | 4 passed |
| `pytest tests/postgres/test_pg_invoices.py` (two API processes, runtime role) | 4 passed |
| Hardening (2026-10-26, after review): `pytest tests/integration/test_invoice_recovery.py` | 10 passed |
| Hardening: `pytest tests/postgres/test_pg_invoices.py` (adds recovery on the runtime role) | 5 passed |
| Combined run before hardening: the invoice tests above plus `test_payment_units`, `test_runtime_role_grants`, `test_payments_api`, `test_payment_hardening`, `test_checkout_api`, `test_order_fulfilment_api`, `test_order_lock_order`, `test_inventory_reservations`, `test_staff_authorization_api`, `test_delivery_api`, `test_pg_payments`, `test_pg_checkout`, `test_pg_delivery` | 438 passed, 0 failed |
| Combined run after hardening (the same set plus `test_invoice_recovery.py`) | 449 passed, 0 failed |
| Dedicated permission (`invoices:recover`): `test_invoice_recovery.py`, `test_roles.py`, `test_staff_authorization_api.py`, `test_pg_invoices.py`, `test_pg_staff.py` | 116 passed |
| **Combined run after the permission change** (the set above plus `test_roles.py` and `test_pg_staff.py`) | **470 passed, 0 failed** |
| `pytest -k "openapi or settings or permission" tests/integration tests/unit` | 68 passed |
| Pre-PR improvements: `test_invoice_recovery.py::test_a_cod_delivery_without_seller_details_is_refused_then_recovered_unchanged` (new) | 1 passed |
| **Combined final run after the pre-PR improvements** (the same 22 files; 471 tests) | **471 passed, 0 failed** |
| `alembic check` (`test_invoice_migration.py::test_alembic_check_finds_no_drift`, on the disposable test schema) | 1 passed |
| `pytest -k openapi tests/integration tests/unit` (after the OpenAPI text changes) | 6 passed |
| `pytest -k "openapi or settings" tests/integration tests/unit` | 42 passed |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (237 files, after hardening) |
| `mypy .` (repository root) | The 4 pre-existing errors only (`app/repositories/catalog.py:63` twice, migrations `c3a8e5f1d2b4` and `528e6436c34e`); reportlab is listed as untyped in `mypy.ini` and `pyproject.toml`, like openpyxl |
| `alembic heads`; `uv lock --check` | Single head `c5e8a2d7f4b1`; lockfile consistent |
| `git diff --check`; trailing-whitespace check of untracked files | Clean |

The first combined run had 2 failures in `test_delivery_api.py`: two module-12 tests asserted that the settings list held only the delivery threshold. They were updated to the registered keys (the seller details are new keys), and the rerun passed.

## Post-merge steps (not run)

1. With the owner account: `alembic upgrade head` on each environment's database (adds `invoices` and `invoice_counters`), then `scripts/provision_runtime_role.py` to grant the new tables.
2. `uv sync` so ReportLab is installed.
3. An administrator sets `seller.legal_name`, `seller.tin` and `seller.address` (`PATCH /api/v1/staff/settings`) with Finance-approved values **before** payments are taken; an order paid before that has no invoice until an administrator recovers it (`POST /api/v1/staff/orders/{order_id}/invoice`; O-3).
4. Orders paid before Module 16 is deployed (mobile-money successes and delivered cash-on-delivery orders) have no invoice: issuance happens only with a payment success or delivery recorded after deployment. Whether to issue invoices for them retroactively, and with which issue date and year, is a Finance decision that has not been made; no policy is assumed. The recovery endpoint could issue them technically, but it must not be used for that until Finance decides. (O-10)

## Open items before module 16 can be marked Done

1. Human review of this change and of O-1 to O-10.
2. Finance approval of the actual invoice PDF, template and tax display (PR-14); TC-18 run against it (P-4, O-1).
3. Product/Operations owner approval of the proposed delivery-note eligibility default (P-1, O-2).
4. Any assignment of `invoices:recover` beyond administrator needs a recorded approval (P-2, O-3); none is planned.
5. Finance confirmation of the recovered invoice's issue date and numbering year (P-3, O-9).
6. Finance decision on retroactive invoices for orders paid before deployment (O-10).
7. Storefront invoice links; PR review, CI and staging.
8. Committing the changes on `feat/module-16-invoices`; the post-merge steps above.
