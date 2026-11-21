# Module 11 (cart) — acceptance record

| Field | Value |
| --- | --- |
| Module | 11 — cart (`docs/IMPLEMENTATION_PLAN.md` §5, "11 — cart"; §7 Q10, approved with the plan on 2026-10-23) |
| Requirements | PRD PR-05 (cart and checkout, guest and account), PR-15 (security); RE-026 B7 (guest carts owned through a hashed token); AGENTS.md (never trust browser prices or totals) |
| Linked tests | TC-05 (add, remove and update cart quantities; totals update; invalid quantity rejected) |
| Branch | `feat/module-07-media` (owner's instruction; not committed) |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-24 |
| Recommendation | **Not Done; ready for human review.** The backend is implemented and verified. The project owner decided ADR-008 on 2026-10-24: S1, S2 and S4 approved; S3 direction approved, with details pending. Still open: the S3 detailed protections and residual-risk disposition, S1 clean-up, frontend token storage, audit retention/access, human review, the module 12 delivery quote, the storefront TC-05 run and staging. |

## Acceptance criteria

| # | Criterion (plan §5 / Q10) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `GET /cart?zone=` with authoritative totals; delivery fee and grand total with a zone | **Verified** (zone added by module 12, 2026-10-24) | `test_totals_match_the_pricing_service_and_follow_database_prices`; delivery fee and grand total in `tests/integration/test_delivery_api.py` (`test_cart_quote_*`) |
| 2 | `POST /cart/items`, `PATCH` and `DELETE /cart/items/{id}` | Verified | `test_add_update_and_remove_a_line`, `test_quantity_bounds`, `test_a_line_never_exceeds_99_units_in_total` |
| 3 | `POST /cart/merge` for customers only | Verified | `test_merge_is_for_customers_with_a_valid_guest_token` (anonymous 401, no token 422, unknown token 404), `test_staff_accounts_have_no_cart` (403), `test_dc7_a_staff_flagged_account_without_a_role_has_no_cart` |
| 4 | Guest token returned once, sent in X-Cart-Token, only its hash stored | Verified | `test_the_first_add_creates_a_guest_cart_and_shows_the_token_once` (SHA-256 stored; the raw token appears in no column; later responses omit it), `test_a_malformed_token_is_422`, `test_an_unknown_token_is_404_everywhere_and_never_creates_a_cart` |
| 5 | Ownership isolation | Verified | `test_owners_never_see_or_change_each_others_lines` (customer/customer, guest/customer and customer/guest: the same 404 as a missing line), `test_a_customer_token_ignores_x_cart_token_except_for_merge`, `test_an_invalid_bearer_token_is_401_not_a_guest`, `test_dc7_an_invalid_bearer_is_401_on_every_cart_route` |
| 6 | Totals from `pricing.quote_merchandise`; client prices never trusted | Verified | `test_totals_match_the_pricing_service_and_follow_database_prices`, `test_client_prices_and_totals_are_refused` (price, unit_price, line_subtotal, total, merchandise_subtotal: 422) |
| 7a | 1–99 per line, at most what is available | Verified | `test_quantity_bounds` (1, 99, 0, -1, 100, 1.5), `test_a_line_never_exceeds_99_units_in_total`, `test_more_than_is_available_is_refused_not_capped`, `test_a_refused_first_add_creates_no_guest_cart_and_no_token`, `test_dc1_a_guest_first_add_refused_with_422_creates_no_cart` |
| 7b | Inactive or hidden variants flagged and excluded from totals | Verified | `test_invalid_lines_are_flagged_and_left_out_of_the_totals` (inactive variant, inactive category, stock fallen below the line), `test_unsellable_or_unknown_variants_cannot_be_added` (unknown, inactive, hidden, no stock record) |
| 7c | Merge adds quantities, capped by availability | Verified | `test_merge_adds_guest_quantities_with_caps_and_closes_the_guest_cart`, `test_merge_creates_the_customer_cart_when_there_is_none`, `test_a_failed_merge_changes_nothing`, `test_dc3_a_merge_never_lowers_a_line_above_current_stock`; concurrent merges: `test_concurrent_merges_of_one_guest_cart_add_its_units_once` |
| 7d | Guest carts expire after 30 days | Verified | `test_guest_carts_expire_30_days_after_their_last_change`, `test_an_expired_guest_cart_cannot_be_read_changed_or_revived` |
| 8 | Tests: ownership, tampered amounts, merge, expiry, caps | Verified | Rows 3–7; concurrency and grants in `tests/postgres/test_pg_cart.py`; grant pins in `tests/unit/test_runtime_role_grants.py` |
| 9 | Runtime role least privilege | Verified | `scripts/provision_runtime_role.py`; `test_cart_tables_have_exactly_the_privileges_module_11_uses`; `test_runtime_role_cannot_delete_carts`; ADR-006. No grant was added for S1–S4: the merge audit uses the existing INSERT on `audit_records`. |
| 10 | PR reviewed, CI green, staging | **Open** | Not committed (by instruction) |
| 11 | TC-05 recorded | **Partial** | API level above; the storefront cart page does not exist yet |

## Requirements-to-evidence checklist (2026-10-24)

| Requirement (source) | Implemented | Evidence | Remaining |
| --- | --- | --- | --- |
| Five cart routes (plan §5) | Yes | Acceptance criteria rows 1–3; `test_openapi_documents_the_cart_routes`; live OpenAPI inventory in `tests/postgres/test_pg_http.py` | — |
| Delivery fee and grand total with `zone` (plan §5) | Deferred by owner instruction (503) | `test_a_zone_answers_503_until_delivery_quotes_exist` | Module 12 |
| Guest token once, in the body, hashed, `X-Cart-Token` (plan §5, Q10, B7) | Yes; transport confirmed by ADR-008 S2 (approved 2026-10-24) | Row 4 | Frontend token storage (ADR-006) |
| Ownership isolation (plan §5 tests) | Yes | Row 5 | — |
| Database prices only (AGENTS.md, plan §5) | Yes | Row 6; `test_totals_match_the_pricing_service_and_follow_database_prices` | — |
| Q10 rules (approved) | Yes | Rows 7a–7d | — |
| Amount bounds (ADR-007) | Yes | D-C10; `test_a_price_change_during_a_cart_read_is_flagged_not_a_500` | — |
| Concurrency and rollback | Yes | `test_concurrent_first_adds_by_one_customer_share_one_cart`, `test_concurrent_adds_on_one_guest_cart_lose_no_update`, `test_concurrent_merges_of_one_guest_cart_add_its_units_once`, `test_a_merge_racing_guest_adds_never_loses_or_doubles_units`, `test_a_failed_merge_changes_nothing`, `test_a_failed_audit_rolls_the_merge_back` | — |
| Least privilege (plan §2, ADR-006) | Yes | Row 9 | — |
| Abuse limits, audit, CORS (ADR-008 S1, S3, S4; D-C11) | Yes. S1 and S4 approved; S3 direction approved (project owner, 2026-10-24) | `tests/integration/test_cart_security.py`, `tests/unit/test_client_network.py`, `tests/unit/test_health.py` | S3 detailed protections and residual-risk disposition (ADR-008 "Still open") |
| Downstream checkout (plan §5, module 14) | Contract ready: lines carry `variant_id` and `quantity`; prices are never trusted | — | Module 14 must reprice and reserve stock in its own transaction |
| TC-05 | API level | Rows 2, 7a | Storefront run; staging |

## Decisions (for the reviewer)

| # | Decision | Why |
| --- | --- | --- |
| D-C1 | A guest's first `POST /cart/items` without X-Cart-Token creates the cart and returns `cart_token` once. `GET /cart` without a token returns an empty cart and creates nothing. If the first add is refused (409, 422 or 429), no cart and no token are created. | The owner's instruction for this task; it avoids empty carts from page views. Tests: `test_a_refused_first_add_creates_no_guest_cart_and_no_token` (409), `test_dc1_a_guest_first_add_refused_with_422_creates_no_cart`, `test_new_guest_carts_are_limited_per_network_with_retry_after` (429). |
| D-C2 | Adding or updating beyond availability is refused with 409 `insufficient_stock`, not capped. Beyond 99 units it is 422. Responses never contain a stock quantity (`test_refusals_never_reveal_a_quantity`); lines show a status. **Stock levels can still be inferred:** see S3. | Q10 says "never more than currently available"; capping silently would reveal the same number. |
| D-C3 | Merge caps each line at min(99, available). It never lowers a line the customer already has, even when stock has fallen below it, and reports `merged`, `capped` (`line_limit` or `insufficient_stock`) or `excluded` (`unavailable` or `insufficient_stock`) per guest line. | Q10 ("merge capped by availability"). Test for the "never lowers" rule: `test_dc3_a_merge_never_lowers_a_line_above_current_stock`. |
| D-C4 | After a merge the guest cart becomes `converted`, and its lines are kept, not deleted. A repeated merge, or any use of that token, gets 404 `cart_not_found` and adds nothing; the client then reads `GET /cart`. | Uses an existing status and keeps the record. A retry cannot double the units (concurrent merges: one 200, the rest 404, one audit record). |
| D-C5 | A guest cart expires 30 days after its last change; reads do not extend it. Expiry is checked on every read and change (404). The cart is marked `abandoned` when an expired token is next presented, so no scheduled job is needed. Carts never presented again stay `active` but unusable; clean-up is a separate decision (S1 notes). | Q10 says 30 days; counting from the last change keeps an active shopper's cart alive. No new infrastructure. |
| D-C6 | Customer carts have no expiry. | Q10 sets expiry for guest carts only. |
| D-C7 | Any staff-flagged account has no cart (403 `customer_only`), including one without a role assignment. A bearer token that is sent must be valid (401) on every route; the API never falls back to guest. | Carts belong to customers (plan: "merge (customer)"). The check is `user.is_staff or effective_roles(user) != {"customer"}`. Tests: `test_staff_accounts_have_no_cart`, `test_dc7_a_staff_flagged_account_without_a_role_has_no_cart`, `test_an_invalid_bearer_token_is_401_not_a_guest`, `test_dc7_an_invalid_bearer_is_401_on_every_cart_route`. |
| D-C8 | `GET /cart?zone=…` answers 503 `delivery_quote_unavailable` until module 12 is built; no fee or grand total is invented. Ownership is checked first. **Superseded by module 12 (2026-10-24):** the zone now returns the delivery quote and grand total; 503 remains only while the zone's fee or the threshold is not configured, and an unknown or inactive zone is 422 `delivery_zone_unavailable` (`docs/qa/module-12-delivery-acceptance.md`). | The owner approved deferring delivery quotes; 503 with a stable code follows the `password_reset_unavailable` precedent (§7 Q1). |
| D-C9 | Cart changes are not audited, except a successful merge (S4). | Customer profile and address changes are audited (`user.profile.update`, `address.*`); line changes are frequent, reversible and hold no personal data, and the order (module 14) records the purchase. A merge changes which account owns the items, so it is audited. |
| D-C10 | A line whose amount, alone or added to the cart's earlier lines, would exceed the largest storable amount (`pricing.MAX_AMOUNT`, 999,999,999,999 RWF) is flagged `amount_out_of_range` and left out of the totals when the cart is read (200, not 500). Adding or updating into that range is refused with 422 on `quantity`. Lines are taken in cart order, so the same line is always the one flagged. | The pricing service refuses such amounts (ADR-007). Tests: `test_unrepresentable_amounts_are_refused_on_add_and_update`, `test_a_read_flags_lines_beyond_the_amount_range_instead_of_failing`. |
| D-C11 | Browsers may send `X-Cart-Token` (and `Idempotency-Key` for stock adjustments) cross-origin: both are allowed CORS headers. Only explicit `CORS_ORIGINS` are allowed, and a `*` origin is refused at startup because CORS allows credentials. | Tests: `test_cors_preflight_allows_the_api_custom_headers`, `test_cors_preflight_with_custom_headers_rejects_an_unknown_origin`, `test_cors_preflight_still_refuses_unlisted_headers`, `test_a_cross_origin_guest_request_with_x_cart_token_is_allowed`, `test_wildcard_cors_origins_are_refused`. |

## Security decisions S1–S4

The formal record is `docs/architecture/ADR-008-cart-security-controls.md`, accepted in part by the project owner on 2026-10-24. This table summarises it; the ADR holds the details, risks and evidence.

| # | Decision (project owner, 2026-10-24) | Implementation | Still open |
| --- | --- | --- | --- |
| S1 Guest-cart creation limit | **Approved:** 10 new guest carts per client network per fixed hour. Redis outage: new guest-cart creation fails closed with 503 `cart_creation_unavailable`, and existing carts remain usable. | Matches: `CartRateLimiter.hit_guest_creation`, defaults `CART_GUEST_CREATIONS_PER_IP=10`, `CART_GUEST_CREATION_WINDOW_SECONDS=3600`; client network = IPv4 address (including IPv4-mapped IPv6) or IPv6 /64; direct peer only, `FORWARDED_ALLOW_IPS` limited to the proxy (never `*`). | Clean-up of never-reused guest carts: deferred to a separate decision; not built, not approved. |
| S2 Credential transport | **Approved:** keep `X-Cart-Token` for guest carts and `Authorization: Bearer` for customer sessions; no cookies, CSRF middleware or backend-for-frontend under Task 11; no credentials in URLs or logs. | Matches: no change to the transport; `*` CORS origins refused; `X-Cart-Token` allowed by CORS (D-C11). | Frontend token storage (ADR-006 open item). The header decision does not address XSS: a script in the page can read a browser-stored token and send requests. |
| S3 Stock probing | **Direction approved; detailed protections and residual-risk disposition pending.** Keep the Q10 availability rule and the public stock labels; retain 20 refusals per 15 minutes per network and per owner, and fail open with warnings during a Redis outage; any change to API responses needs a documented, reviewed plan first. | Matches: `check_stock_probe` / `record_stock_refusal`, defaults `CART_STOCK_REFUSALS_PER_WINDOW=20`, `CART_STOCK_REFUSAL_WINDOW_SECONDS=900`; lowering, removing and reading are never limited. | Whether to accept the four remaining inference paths (ADR-008 S3): repeated attempts and successful probes; merge responses (`added_quantity`, resulting quantity); repeated reads and line-status changes; public `low_stock`. **The limiter slows probing; it does not eliminate inference.** Module 14 must re-check and reserve stock transactionally; cart checks are not reservations. |
| S4 Merge audit | **Approved:** a successful merge writes its `cart.merge` record in the merge transaction, with the existing metadata and the actor email/phone snapshot; failed or repeated merges write no success record; no credentials in the metadata. | Matches: `AuditService.log_event` inside the merge's `atomic` block; no token, token hash, session token or `Authorization` value in the record. | Audit retention and access policy (ADR-006 open item). |

Completion-pass fixes (2026-10-24): (1) a new guest request refused by the stock-probe limit no longer uses up the creation budget (the probe check now runs first; `test_a_probe_refused_new_guest_request_does_not_use_the_creation_budget`); (2) a price change between the amount check and the quote during a cart read is re-checked and flagged instead of failing with 500 (`test_a_price_change_during_a_cart_read_is_flagged_not_a_500`).

Tests for S1–S4: `tests/integration/test_cart_security.py` (S1: limit with Retry-After and window reset; separate networks and IPv6 /64; spoofed forwarding headers; customers exempt; Redis down. S3: no quantity in refusals; probe limit with lowering and removal still allowed; per-owner limit across networks; Redis down. S4: audit content without secrets; audit failure rolls the merge back; no audit for refused or repeated merges). Plus `tests/postgres/test_pg_cart.py` (concurrent merges: exactly one audit record).

## Guest token handling (RE-026 B7)

- **Token:** `secrets.token_urlsafe(32)` (256 random bits). Only `sha256(token)` is stored in `carts.guest_token_hash`. The raw token is returned once, in the response that created the cart, and is never logged; log lines name cart IDs only. Rate-limit keys use a prefix of the hash, never the token.
- **Unknown tokens:** an unknown, expired or merged token gets the same 404 as one that never existed. A malformed token (not 20–100 URL-safe characters) gets 422.
- **Rotation and invalidation:** a token is invalidated by merge (`converted`) or expiry (`abandoned`). There is no rotation; a new token comes only with a new cart.

## Verification

Last full gate, run from `backend/` on the current Task 11 code (branch `feat/module-07-media`, uncommitted on top of `4f36502`), verified on 2026-10-24 against the disposable `rwanda_ecommerce_test` database:

| Command | Result |
| --- | --- |
| `uv run pytest -q --ignore=tests/postgres -rs` | 925 passed, 0 skipped, 0 failed |
| `uv run pytest -q tests/postgres -rs` | 74 passed, 0 skipped, 0 failed |
| `uv lock --check` | Passed |
| `ruff check . ../scripts` | Passed |
| `ruff format --check . ../scripts` | 179 files already formatted |
| `mypy` (repository root) | 4 errors that predate module 7; no new errors |
| `alembic heads` | `a3b4d2f1d8e6 (head)` |
| `git diff --check` | Clean |

These results show that the backend code and tests pass. They are **not** Product Owner or security approval, staging verification, or formal acceptance of Task 11.

## Open items before module 11 can be marked Done

1. Human review of this change and of decisions D-C1 to D-C11.
2. **S3:** the project owner's disposition of the detailed protections and the residual inference risk (ADR-008 "Still open" 1). Any response change needs a documented, reviewed implementation plan first.
3. Separate decisions that do not block the current implementation but stay tracked: S1 clean-up of never-reused guest carts (ADR-008 "Still open" 2), frontend token storage (ADR-006), and audit retention and access policy (ADR-006).
4. ~~Module 12 (delivery): `zone` must return the delivery fee and grand total.~~ Done in module 12 (2026-10-24, not committed). Module 14 checkout must reprice and re-check and reserve stock inside its own transaction.
5. TC-05 on the storefront cart page; staging deployment, including `FORWARDED_ALLOW_IPS` set to the proxy only.
