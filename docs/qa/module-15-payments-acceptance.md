# Module 15 (payments) — acceptance record

| Field | Value |
| --- | --- |
| Module | 15 — payments (`docs/IMPLEMENTATION_PLAN.md` §5, "15 — payments"; §3 permission matrix; §7 Q11–Q14, Q17, Q21) |
| Requirements | PRD PR-08 (each enabled method passes its test cases; payment status associated with the right order; duplicate callbacks never create duplicate paid orders); ADR-002 (approved stock lifecycle, late payment; payment consistency and idempotency); ADR-006; ADR-008 S6 (guest access limits) |
| Linked tests | TC-08 / TC-09 (mobile-money sandbox success — **mock only**, see below), TC-10 (card — disabled, §7 Q21), TC-11 (failed, cancelled, delayed and duplicate callbacks), TC-12 (cash on delivery) |
| Branch | `feat/module-15-payments`, based on the Module 14 commit `0a033d9`. The Module 15 changes are uncommitted in its working tree. |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-25 |
| Recommendation | **Not Done; ready for human review.** Implemented and verified against the mock and COD providers. Real MTN MoMo / Airtel Money / card integration is blocked on ADR-003 and sandbox credentials (§7 Q21). |

## Acceptance criteria

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `POST /payments/{order_number}/initiate`, `GET /payments/{order_number}/status` | PASS | `tests/integration/test_payments_api.py`: `test_a_guest_initiates_mobile_money_through_the_mock_and_reads_the_status` |
| 2 | Customer ownership; guest order number + phone; non-disclosing errors; guest limits (§7 Q17, ADR-008 S6) | PASS | `test_customers_pay_only_their_own_orders`, `test_guest_access_needs_the_orders_phone_and_mismatches_look_alike` (wrong phone and unknown number: identical 404), `test_guest_failures_count_on_the_lookup_limits` |
| 3 | Provider interface `initiate`, `verify_webhook`, `parse_event`, `check_status`; `mock` (HMAC, secret from env) and `cod` | PASS | `backend/app/integrations/payments/`; `tests/unit/test_payment_units.py` |
| 4 | §7 Q21: mock and COD only; card disabled; no real provider pretended | PASS | `test_methods_map_to_the_approved_providers_and_card_stays_disabled`; mock instructions say no real request is sent; `test_the_mock_secret_is_required_long_and_never_in_production` |
| 5 | Webhook authenticity before acceptance; forged, stale and unsigned callbacks store nothing | PASS | `test_forged_stale_and_unsigned_callbacks_store_nothing`, `test_the_mock_verifies_hmac_signatures_and_freshness` |
| 6 | Sanitised `payload_metadata`; no full phone, card data or secrets | PASS | `test_event_metadata_is_sanitised` (masked `+250******456`, no card/cvv/secret keys, digest only), `test_parsed_events_keep_only_allow_listed_facts` |
| 7 | Deduplication on (provider, event_key); 200 for duplicates; nothing repeated | PASS | `test_a_duplicate_event_is_acknowledged_and_repeats_nothing`; real HTTP, two processes: `tests/postgres/test_pg_payments.py::test_concurrent_duplicate_webhooks_apply_once` (8 copies: 1 processed, 7 duplicates, one commit) |
| 8 | Success commits the reservation atomically, only when amount and currency match | PASS | `test_a_verified_success_commits_the_stock_and_marks_the_payment_paid`, `test_a_mismatched_success_needs_reconciliation_and_changes_nothing` (amount; currency) |
| 9 | Late success after expiry: `needs_reconciliation`; nothing resurrected; not marked paid | PASS | `test_a_late_success_after_expiry_needs_reconciliation` (expiry job not yet run), `test_a_success_after_the_expiry_job_ran_needs_reconciliation` |
| 10 | Failure, cancellation, delayed status | PASS | `test_failure_and_cancellation_keep_the_hold_for_a_retry` (D-Y2), `test_a_delayed_outcome_stays_pending_until_the_final_event` |
| 11 | A later failure never regresses a success | PASS | `test_a_success_never_regresses_on_a_later_failure`; real HTTP race: `test_racing_success_and_failure_events_never_regress` |
| 12 | Provider error and unconfigured provider | PASS | `test_a_provider_error_fails_the_attempt_and_a_retry_starts_a_new_one` (history kept), `test_an_unconfigured_mock_answers_503` |
| 13 | Unknown reference kept for reconciliation | PASS | `test_an_unknown_reference_is_kept_for_reconciliation` |
| 14 | Atomic apply; a failure rolls back the event too | PASS | `test_a_failure_while_applying_rolls_everything_back` (no event row, hold active; the retry is processed) |
| 15 | TC-12: COD pending at checkout and until delivery; cash confirmation `payments:manage` | PASS (backend) | `test_cash_on_delivery_stays_pending_until_delivery`, `test_only_cod_payments_can_be_confirmed_as_cash` |
| 16 | `payments:read` (administrator, management) read-only; `payments:manage` (administrator) | PASS | `test_payment_permissions` (sales, operations, customer 403; anonymous 401; management cannot confirm), `test_the_staff_list_filters_and_shows_no_secrets` |
| 17 | Migration `payload_metadata` with downgrade | PASS | `tests/integration/test_payment_migration.py` |
| 18 | Runtime role least privilege | PASS | `payment_events`: SELECT, INSERT, UPDATE; `test_order_fulfilment_tables_have_exactly_the_privileges_the_service_uses`; `test_runtime_role_cannot_delete_payment_events` |
| 19 | Concurrent initiation: one provider call per attempt; a fresh claim gets `409 payment_initiation_in_progress`; a stale claim (older than 120 seconds) is retried with the same idempotency key only for a provider that guarantees idempotent initiation, otherwise `409 payment_initiation_needs_recovery` with a durable reconciliation record (attempt left unresolved, not marked failed); an unconfigured provider releases its claim | PASS (mock; the non-idempotent path is simulated by patching the mock's flag), with the limitations below | `tests/integration/test_payment_hardening.py`: `test_concurrent_initiations_make_one_provider_call` (two threads, separate sessions: the second is refused at once, one provider call, carrying the attempt's idempotency key), `test_a_fresh_claim_is_in_progress`, `test_a_stale_claim_is_retried_with_the_same_key_when_the_provider_is_idempotent` (the provider accepted the lost first call: the retry returns the same reference, one attempt), `test_a_stale_claim_needs_recovery_when_the_provider_is_not_idempotent` (no provider call, error logged, attempt unchanged, later requests refused too, one linked record for both refusals), `test_an_unconfigured_provider_releases_the_claim` |
| 20 | Webhook `reason` stored only as an allow-listed code (anything else becomes `"other"`); no free text in `payload_metadata` | PASS | `test_only_allow_listed_reason_codes_are_stored` (hardening); `tests/unit/test_payment_units.py::test_only_allow_listed_reason_codes_reach_the_metadata` |
| 21 | Webhook `status` of a non-string type (list, object, number, null, boolean) is a malformed event: 422 `malformed_event`, nothing stored (not a 500) | PASS | `test_a_non_string_status_is_a_malformed_event` (hardening); non-string cases in `test_the_mock_refuses_malformed_events` |
| 22 | A provider reference returned after the hold expired (or the order was cancelled) during the call is never lost: kept on the attempt, recorded once for reconciliation (linked, audited, sanitised, flagged in the staff list); order, attempt and stock keep their states; a later webhook for it is linked and handled as a late payment; a racing second reference is recorded and never overwrites the first | PASS (mock; the staff-cancellation variant shares the code path but has no test of its own) | `test_a_reference_returned_after_expiry_is_kept_for_reconciliation` (the expiry job runs in its own session during the provider call), `test_a_late_reference_is_recorded_once`, `test_a_racing_second_reference_is_recorded_and_never_overwrites_the_first`, `test_the_same_reference_from_a_racing_retry_is_not_a_conflict`, `test_no_webhook_can_write_as_the_internal_source`; records are `received`, never `verified`: `test_reconciliation_records_are_received_never_verified`; a provider event that arrived before the reference was saved is linked to the attempt (not applied): `test_an_event_before_the_reference_is_saved_is_linked_for_reconciliation` |
| 23 | An unknown provider outcome (`ProviderOutcomeUnknown`: timeout or transport error after sending) is never a failure: without the idempotency guarantee the claim stays and a reconciliation record is kept (409 `payment_initiation_needs_recovery`); with it the claim is released and the request gets 502, so a retry uses the same key | PASS (simulated by patching the mock) | `test_an_unknown_outcome_keeps_the_claim_and_needs_recovery_without_idempotency`, `test_an_unknown_outcome_with_an_idempotent_provider_can_be_retried`; an unexpected adapter exception is handled the same way (never a failure, never a 500; only its type is logged): `test_an_unexpected_adapter_error_is_an_unknown_outcome_not_a_failure`, `test_an_unexpected_adapter_error_with_an_idempotent_provider_can_be_retried` |
| 24 | Existing initiation, webhook, late-payment, expiry, cancellation and lock-order behaviour unchanged | PASS | `test_payments_api.py`, `test_pg_payments.py`, `test_checkout_api.py` (Q12 expiry), `test_order_lock_order.py`, `test_inventory_reservations.py`, `test_order_fulfilment_api.py`, `test_pg_checkout.py`; see "Final hardening run" |
| 25 | TC-08 / TC-09 with real MTN MoMo / Airtel Money sandboxes | **BLOCKED** | ADR-003 not decided; no sandbox credentials (§7 Q21). Only the mock is implemented |
| 26 | TC-10 card | Not applicable until enabled | Card disabled (§7 Q21) |
| 27 | Storefront payment flow; PR review, CI, staging | BLOCKED | Not committed; no storefront payment page; staging not available from here |

## Decisions (for the reviewer)

| # | Decision | Why / status |
| --- | --- | --- |
| D-Y1 | `mock` serves `mtn_momo` and `airtel_money`; `cod` serves cash on delivery; no provider for `card`. The mock is configured only when `PAYMENT_MOCK_WEBHOOK_SECRET` (32+ characters) is set and is refused when `APP_ENV=production`. | §7 Q21. A mock in production would accept self-signed "payments" that move no money. |
| D-Y2 | A failed or cancelled payment does not release the stock hold: the customer may start a new attempt until the hold lapses (15 minutes, Q11), when the order is cancelled (Q12). | ADR-002 lists release on "terminal payment failure" but leaves which failures are terminal open; retry within the hold is the safer reading. **Pending Product/Operations approval; not approved.** |
| D-Y3 | A success after a failure still commits while the hold lasts (the provider's latest word is success); a failure after a success is ignored. | ADR-002: never regress a success; arrival order is not chronology. |
| D-Y4 | A late success (hold lapsed or released) commits nothing and resurrects nothing; the order is cancelled for payment timeout (as the expiry job would) and the event is `needs_reconciliation`, listed for staff (`needs_reconciliation=true`). The refund or manual resolution is a finance process, not built. | ADR-002 late payment. The reconciliation procedure itself is unresolved (ADR-002 "remain unresolved pending ADR-003"). |
| D-Y5 | Forged, stale or unsigned webhooks are refused (401) and **not stored**, so unauthenticated requests cannot grow the table. | ADR-002 asks for durable receipts of events that cannot be applied; verified ones are always stored (including unknown references and mismatches). |
| D-Y6 | Guest initiation and status use the order number plus phone (body `phone` to initiate; `X-Order-Phone` header for status, never in the URL) and count failures on the guest-lookup counters (ADR-008 S6: 5 per order number, 20 per IP, 15 minutes, fail closed). | §7 Q17 names the same proof and a per-IP limit; one shared budget stops an attacker getting three. |
| D-Y7 | `POST /staff/payments/{attempt_id}/confirm-cod` records cash collected only for a delivered COD order; since delivery already marks it succeeded (Q14), it is normally a no-op. | Plan §5 names COD confirmation as a `payments:manage` action; Q14 already covers the state change. |
| D-Y8 | Payment success does not change the order's fulfilment status (it stays `received` until staff confirm). | ADR-002 keeps fulfilment state separate from payment state. |

## Payment hardening (concurrency and webhook input)

- **Initiation claim:** the first initiation transaction claims the attempt under the order's lock (provider set, no provider reference yet). A concurrent request for the same attempt finds the claim and gets `409 payment_initiation_in_progress` ("This payment is being started; try again in a moment."), so it never makes a second provider call. An unconfigured provider (503) releases the claim, so a later retry is not refused.
- **Stale claims:** a claim older than 120 seconds (`CLAIM_TIMEOUT`) has an unknown outcome: the first call may still be running, or the provider may have accepted it without its reference being saved. What happens depends on the provider adapter's `idempotent_initiation` flag, an explicit guarantee that `initiate()` repeated with the same idempotency key cannot start a second payment:
  - **Guaranteed (the mock and `cod`):** the call is retried with the attempt's same idempotency key, and a warning is logged.
  - **Not guaranteed:** no provider call. The request gets `409 payment_initiation_needs_recovery` ("This payment's start could not be confirmed. Please contact support; do not pay again."), and an `initiation_needs_recovery` reconciliation record is written (below). The attempt keeps status `created`, its provider and no reference: it is not marked failed, because the payment may exist. Later requests get the same 409 (one record). If the hold then expires, the expiry job expires the attempt and cancels the order as usual (ADR-002/Q12, unchanged); the record survives. A provider webhook for such a payment would arrive under an unknown reference and be kept as `needs_reconciliation`, unlinked.
- **Reconciliation records:** what needs a person is written as a `payment_events` row with provider `internal` (a source no webhook can produce: `/webhooks/internal` answers 404), `processing_status = needs_reconciliation`, linked to the attempt by `attempt_id`, so `GET /staff/payments?needs_reconciliation=true` flags the attempt and `GET /staff/payments/events` lists the record. Its `verification_status` is `received`, never `verified`: nothing in it is authenticated provider evidence (an `initiate()` answer is not signed), and ADR-002 asks to distinguish received from verified. It is audited (`payment.reconciliation`) and logged at error level (ids and kind only). Metadata is sanitised: kind, provider, provider reference (when there is one), method, amount, currency, attempt and order status; no phone, secret, signature or payload (`payload_digest` is empty). Each (kind, attempt, reference) is recorded once through the existing `(provider, event_key)` unique index, written in the same transaction as any attempt change, under the order's lock (existing lock order). No migration was needed. Kinds: `initiation_needs_recovery`, `initiation_outcome_unknown`, `late_reference`, `conflicting_reference`.
- **Late references:** if the provider returns a reference after the attempt left `created` (the expiry job ran, or staff cancelled the order, during the call), the reference is kept on the attempt (when it has none and no other attempt holds it) and a `late_reference` record is written; the attempt (`expired`/`cancelled`), the order (`cancelled`) and the stock (`expired`/`released`) keep their states, nothing is committed or revived, and the request gets `409 payment_initiation_needs_recovery`. A later success webhook for that reference is therefore linked to the attempt and follows the existing late-payment path (D-Y4: `needs_reconciliation`, nothing committed). A different second reference for an attempt that already has one is recorded as `conflicting_reference` and never overwrites the first.
- **Unknown provider outcomes:** adapters raise `ProviderOutcomeUnknown` (deliberately not a `ProviderError`) for a timeout or transport error after sending. Without the idempotency guarantee the claim stays (so nothing repeats the call), an `initiation_outcome_unknown` record is written and the request gets `409 payment_initiation_needs_recovery`; the attempt is not marked failed. With the guarantee, the claim is released and the request gets 502 `payment_provider_error`; a retry uses the same attempt and key. `ProviderError` now means, by contract, that no payment started; only then is the attempt marked failed. Any other exception from an adapter (a bug or an unwrapped transport error) is handled exactly like `ProviderOutcomeUnknown`: never marked failed, no 500, only the exception's type is logged (its message could carry provider data).
- **Early provider events:** a webhook that arrives before the initiation call has saved the attempt's reference is stored as `needs_reconciliation` ("unknown reference"). When the reference is then saved (normally or late), such events are linked to the attempt (matched on the event metadata's `reference`), audited (`payment.reconciliation`, kind `early_event_linked`), and left `needs_reconciliation`: they are not applied, so a person decides; the staff attempt list then flags the attempt.
- **Idempotency key:** the attempt's idempotency key is passed to the provider in `OrderForPayment.idempotency_key`. Real adapters must send it to the provider as its idempotency or merchant reference, and must leave `idempotent_initiation` false until the provider's support is confirmed.
- **Mock references:** the mock's reference is derived from the attempt's idempotency key (`MOCK-` plus 24 hex characters of its SHA-256), so repeating the call for one attempt returns the same reference; a new attempt after a failure has a new key and a new reference. `cod` makes no external call and its reference is the order number. These are the only adapters that claim the guarantee; no real provider's guarantee has been verified (ADR-003).
- **Webhook `status`:** must be a string and one of `pending`, `succeeded`, `failed`, `cancelled`. Any other JSON type gets the normal malformed-event response (422 `malformed_event`), not a 500.
- **Webhook `reason`:** stored in `payload_metadata` only as one of `insufficient_funds`, `declined`, `cancelled_by_payer`, `timeout`, `expired`, `provider_error`. Anything else, including free text, objects and numbers, is stored as `"other"`, because provider free text could carry personal data. The existing sanitisation (masked phone, allow-listed keys only) is unchanged.
- **Remaining limitations:**
  - Reconciliation records can be found but not resolved: there is no staff action to close a record, link an unlinked provider event to an attempt, or refund; that needs the finance reconciliation procedure (an unresolved Finance decision). Records stay `needs_reconciliation` until then.
  - Early-event linking relies on adapters putting the provider reference in the event metadata (the mock does), and an event committed at the same instant as the reference is saved can be missed (it stays an unlinked `needs_reconciliation` event, still listed). Linked early events are not applied automatically: a paid early success still needs a person.
  - A provider event for a payment whose reference was never returned (the needs-recovery and unknown-outcome cases) cannot be linked automatically: the attempt holds only its idempotency key, and whether real provider events carry it is unknown (ADR-003).
  - The customer-facing message for these cases ("contact support; do not pay again") assumes a support process that is not defined here.
  - The `idempotent_initiation` flag is a promise made by the adapter; the service cannot verify it. Each real adapter needs review against its provider's documented idempotency behaviour before it sets the flag (ADR-003).
  - For an adapter that does set the flag, a slow first call can still overlap the retry; it stays one payment only if the provider honours the idempotency key as promised.
  - The service does not ask the provider what happened to the first call before refusing; that would need a provider status lookup by idempotency key, which ADR-003 has not confirmed.

## Real-provider and approval dependencies

- **ADR-003** (provider selection, signature mechanism, event identifiers, ordering and retry semantics) and **sandbox credentials** for MTN MoMo and Airtel Money: until then only the mock exists (§7 Q21). TC-08/TC-09 cannot pass against a real sandbox.
- **Provider idempotency:** confirmation that the selected providers accept an idempotency or merchant reference; until then a real adapter must not set `idempotent_initiation`, and its stale claims need recovery (see "Payment hardening").
- **Finance:** the reconciliation and refund procedure for `needs_reconciliation` events (late success, amount mismatch, unknown reference), for the service's `internal` reconciliation records (`initiation_needs_recovery`, `initiation_outcome_unknown`, `late_reference`, `conflicting_reference`), and the duplicate-capture remedy (ADR-002).
- **D-Y2** Product/Operations approval (failure keeps the hold for a retry); pending.

## Verification (2026-10-25)

All database tests ran on `rwanda_ecommerce_test` only (Docker PostgreSQL on 127.0.0.1:55432). The development database was not migrated or seeded. Run from `backend/` with uv.

| Command | Result |
| --- | --- |
| `pytest tests/integration/test_payments_api.py` | 31 passed |
| `pytest tests/unit/test_payment_units.py tests/integration/test_payment_migration.py` | 13 passed |
| `pytest tests/postgres/test_pg_payments.py` (real HTTP, two processes, runtime role) | 3 passed |
| `pytest tests --ignore=tests/postgres` (full, first run) | 1271 passed, 10 failed: unit tests that build production `Settings` inherited the test-only mock secret from `tests/conftest.py`, which production now refuses; their helpers now pass `payment_mock_webhook_secret=None` |
| `pytest tests --ignore=tests/postgres` (full, rerun after that fix) | **1281 passed, 0 failed** |
| `pytest tests/postgres` (full) | **93 passed, 0 failed** |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (225 files) |
| `mypy .` (repository root) | 4 errors, all pre-existing and in files this module does not touch (`app/repositories/catalog.py:63` twice, migrations `c3a8e5f1d2b4` and `528e6436c34e`); the 2 typing errors this module introduced were fixed |
| `alembic heads`, `alembic history`, `uv lock --check` | Single head `a7c2e9d4f6b8` (after `f3a8c6e1b5d9`); lockfile unchanged |
| `git diff --check` | Clean |

### Payment hardening run (2026-10-25)

Focused run after the hardening changes, on `rwanda_ecommerce_test` only; the full suites were not rerun.

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_payment_units.py tests/integration/test_payment_hardening.py tests/integration/test_payments_api.py tests/integration/test_payment_migration.py tests/postgres/test_pg_payments.py` | **68 passed** |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (226 files) |

### Stale-claim recovery run (2026-10-25)

Focused run after the stale-claim change (retry only for idempotent adapters; otherwise `payment_initiation_needs_recovery`), on `rwanda_ecommerce_test` only; the full suites were not rerun.

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_payment_units.py tests/integration/test_payment_hardening.py tests/integration/test_payments_api.py tests/postgres/test_pg_payments.py` | **68 passed** |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (226 files) |

### Final hardening run (2026-10-25)

Focused run after the reconciliation-record changes (late references, unknown outcomes, durable needs-recovery), on `rwanda_ecommerce_test` only; no migration was added; the full suites were not rerun.

| Command | Result |
| --- | --- |
| `pytest tests/unit/test_payment_units.py tests/integration/test_payment_hardening.py tests/integration/test_payments_api.py tests/integration/test_payment_migration.py tests/postgres/test_pg_payments.py tests/integration/test_order_lock_order.py tests/integration/test_checkout_api.py` | **131 passed** |
| `pytest tests/integration/test_inventory_reservations.py tests/integration/test_order_fulfilment_api.py tests/postgres/test_pg_checkout.py` | **60 passed** |
| `pytest -k openapi tests/integration tests/unit` (after the OpenAPI text change) | 6 passed |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (226 files) |
| `mypy .` (repository root) | The same 4 pre-existing errors only (`app/repositories/catalog.py:63` twice, migrations `c3a8e5f1d2b4` and `528e6436c34e`) |
| `git diff --check`; trailing-whitespace check of untracked files | Clean |

The first run of the new tests found that re-processing the same late result through the recording helper was classed as a conflicting reference; the helper was fixed to record a repeat as the same `late_reference` (one record), and the tests were rerun.

### Pre-commit review run (2026-10-25)

After the pre-commit review fixes (reconciliation records `received`, unexpected adapter exceptions as unknown outcomes, early events linked), on `rwanda_ecommerce_test` only; no migration was added; the full suites were not rerun.

| Command | Result |
| --- | --- |
| `pytest tests/integration/test_payment_hardening.py` | 25 passed (before the early-event test was added) |
| `pytest tests/unit/test_payment_units.py tests/integration/test_payment_hardening.py tests/integration/test_payments_api.py tests/integration/test_payment_migration.py tests/postgres/test_pg_payments.py tests/integration/test_order_lock_order.py tests/integration/test_checkout_api.py tests/integration/test_inventory_reservations.py tests/integration/test_order_fulfilment_api.py` | **191 passed** |
| `ruff check . ../scripts`, `ruff format --check . ../scripts` | Pass (226 files) |
| `mypy .` (repository root) | The same 4 pre-existing errors only |
| `alembic heads` | Single head `a7c2e9d4f6b8` (unchanged) |
| `git diff --check`; trailing-whitespace check of untracked files | Clean |

## Open items before module 15 can be marked Done

1. Human review of this change, including the payment hardening, and of decisions D-Y1 to D-Y8 (D-Y2 pending Product/Operations approval).
2. ADR-003 and sandbox credentials; real provider adapters behind the same interface, sending the attempt's idempotency key and setting `idempotent_initiation` only once it is confirmed that the selected providers support it; TC-08/TC-09 against the sandboxes.
3. The finance reconciliation procedure (and refund responsibility) for `needs_reconciliation` events, including the service's `internal` reconciliation records (late, conflicting or unconfirmed initiations) and unlinked provider events; any staff action to resolve them.
4. Storefront payment flow; PR review, CI and staging.
5. Committing the Module 15 changes on `feat/module-15-payments`; migrating the development database (owner account), then `provision_runtime_role.py`.
