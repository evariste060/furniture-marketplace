# ADR-008: Cart security controls (guest-cart limits, stock probing, merge audit, credential transport)

Status: **Accepted in part (project owner, 2026-10-24; S5 approved 2026-10-25)** for the decisions marked *Approved*. S3 has an *approved direction* whose detailed protections and residual-risk disposition are still pending. Items under "Still open" are not approved and must not be implemented on an assumed answer. Recording these decisions does not make Task 11 accepted (`docs/qa/module-11-cart-acceptance.md`).

Context: Task 11 (module 11, cart; `docs/IMPLEMENTATION_PLAN.md` §5 and §7 Q10, approved 2026-10-23) and RE-026 B7 (guest carts owned through a hashed token; "security review still due with the cart and checkout modules"). The decision-readiness review recorded in `docs/qa/module-11-cart-acceptance.md` found that the approved documents decided none of S1–S4. ADR-006 approves rate limiting only for login failures, a policy that password reset reuses (plan §7 Q1/Q2), and lists "token storage for the frontend (bearer vs httpOnly cookie)" as still open. S1, S3 and S4 were built on `feat/module-07-media` (uncommitted) before these decisions; the owner's decisions below were made on 2026-10-24 against that implementation.

> **Superseded in part (2026-10-25):** the frontend token storage decision ("no cookies, CSRF middleware or backend-for-frontend") was replaced by ADR-006 (httpOnly cookies set by the Next.js route handlers) and ADR-011 (the `/api/backend` proxy with an Origin check). The API itself is unchanged.


Decision-maker: the project owner (as in ADR-006 and ADR-007). No separate security reviewer is assigned in the repository (ADR-002: "security owner unassigned").

## Decisions at a glance

| Item | Decision (project owner, 2026-10-24) |
| --- | --- |
| S1 Guest-cart creation limit | **Approved** |
| S2 Credential transport | **Approved:** keep the header-based contract. Frontend token storage remains open. |
| S3 Stock probing | **Direction approved; detailed controls and residual-risk disposition pending** |
| S4 Merge audit | **Approved.** Audit retention and access policy remain open (ADR-006). |
| S5 Promotion-code guessing (module 13) | **Approved (project owner, 2026-10-25)** with the settings below. |
| S6 Guest order lookup (module 14) | **Approved (project owner, 2026-10-25)** with the settings below. |

## S1 — Guest-cart creation limit

| | |
| --- | --- |
| Status | **Approved (project owner, 2026-10-24).** Implemented. |
| Problem | Every anonymous `POST /api/v1/cart/items` without `X-Cart-Token` creates a `carts` row. Guest carts reserve no stock, so they cannot block sales, but rows grow without bound, because carts never presented again stay `active` (decision D-C5). |
| Decision | Limit new guest carts per client network on the existing Redis rate-limit store: **10** new guest carts per client network per fixed hour (`CART_GUEST_CREATIONS_PER_IP=10`, `CART_GUEST_CREATION_WINDOW_SECONDS=3600`). Every guest request that would create a cart counts, including requests then refused for another reason (409, 422). Beyond the limit: 429 `rate_limited` with `Retry-After`, and no cart is created. Reads, line changes, removals, existing guest carts and customer carts are not limited by it. |
| Client identity | The client address from `app/core/request_context.py`: the shopper's address vouched for by the storefront with a signed header when `CLIENT_IP_SOURCE=signed`, otherwise the direct peer (ADR-006 client IP amendment, 2026-11-13), bucketed as the IPv4 address or the IPv6 /64 (`app/core/rate_limit.py: client_network`). An IPv4 client seen through a dual-stack IPv6 socket (`::ffff:a.b.c.d`, for example with `--host ::`) is bucketed by its IPv4 address (`address.ipv4_mapped`, fixed on 2026-10-24 after the ADR-008 review). Requests without a usable address share one `unknown` bucket. The application never reads `X-Forwarded-For`, `X-Real-IP` or `Forwarded` itself. Uvicorn rewrites the peer from `X-Forwarded-For` only for connections from `--forwarded-allow-ips` (env `FORWARDED_ALLOW_IPS`; default `127.0.0.1`; proxy headers are on by default). Behind a reverse proxy, set it to the proxy's addresses only, and never to `*` (`docs/deployment/README.md`). |
| Redis outage | **Approved:** fail closed for new guest-cart creation only, with 503 `cart_creation_unavailable`, logged at ERROR ("Guest cart creation refused: the rate-limit store is unavailable"). Existing carts remain usable. This matches the fail-closed login limiter (ADR-006). An in-process fallback was rejected: per-worker counters multiply the limit by the number of workers and differ between instances. |
| Monitoring | WARNING "Guest cart creation limit reached for a client network" when the limit is hit; ERROR on a store outage. Neither logs the IP address, a token or request data. There is no metrics backend or alerting in the repository; turning these log lines into alerts is part of the monitoring work in ADR-004. |
| Deferred | **Clean-up of never-reused guest carts is deferred to a separate decision** (see "Still open"). It is neither built nor approved. It would need a scheduled job and DELETE on `carts`, which the runtime role does not have (ADR-006). |
| Alternatives considered | Fail open during an outage (rejected: it silently disables the control); a per-cart CAPTCHA (new infrastructure and frontend work); no limit until launch. |
| Risks | Shared addresses (offices, mobile carrier NAT) share one bucket, so 10 per hour may refuse legitimate guests. Proxy misconfiguration makes every client share the proxy's bucket, and an over-broad `FORWARDED_ALLOW_IPS` (for example `*`) lets clients choose their own bucket. |
| Evidence | `tests/integration/test_cart_security.py`: `test_new_guest_carts_are_limited_per_network_with_retry_after`, `test_networks_are_counted_separately_and_ipv6_by_slash_64`, `test_ipv4_mapped_peers_are_limited_by_their_own_ipv4_address`, `test_forwarding_headers_from_the_client_are_not_trusted`, `test_customers_are_not_limited_by_the_guest_creation_limit`, `test_unusable_addresses_share_one_bucket`, `test_redis_down_refuses_new_guest_carts_but_existing_carts_keep_working`, `test_a_probe_refused_new_guest_request_does_not_use_the_creation_budget`; `tests/unit/test_client_network.py`. These run through the test client, not uvicorn: the forwarding-header test proves that the application ignores those headers, not how uvicorn is configured in a deployment. |

## S2 — Credential transport

| | |
| --- | --- |
| Status | **Approved (project owner, 2026-10-24): keep the existing header-based contract.** No change needed to the implementation. |
| Decision | Guest carts keep `X-Cart-Token` (plan §5, §7 Q10: the token is "returned once in the body, sent back in `X-Cart-Token`, stored only as `guest_token_hash`"). Customer sessions keep `Authorization: Bearer` with the opaque session token returned in the body by the approved login API (ADR-006). Server side, only SHA-256 hashes of both are stored. **No cookies, CSRF middleware or backend-for-frontend under Task 11.** Credentials must never appear in URLs or logs. |
| Still open | **Frontend token storage** (memory, `sessionStorage` or `localStorage`) is undecided. It stays tracked as the ADR-006 open item "token storage for the frontend", for both the guest cart token and the customer session token. |
| Security notes | Credentials travel only in headers that the page sets itself; browsers never attach them automatically, so classic CSRF does not apply to this design. **The header decision does not address XSS:** a script injected into the page can read a token kept in browser-accessible storage and send authenticated requests. XSS prevention (output encoding, a Content Security Policy) and the storage decision remain necessary. |
| Hardening in place | Only explicit `CORS_ORIGINS` are allowed, and `*` is refused at startup (`app/core/config.py`; `test_wildcard_cors_origins_are_refused`). `X-Cart-Token` and `Idempotency-Key` are allowed CORS headers (D-C11). |
| Alternatives considered | Cookies with the storefront and API on one site, for example through a same-origin reverse proxy, where `SameSite=Lax` or `Strict` is possible (still needs CSRF protection); cross-site cookies (`SameSite=None; Secure`) with credentialed CORS and CSRF tokens; a backend-for-frontend holding credentials server-side (new component; needs ADR-004). All were declined for Task 11. Cookie scope and `SameSite` would depend on the ADR-004 hosting topology, which is not written. |

## S3 — Stock probing

| | |
| --- | --- |
| Status | **Direction approved (project owner, 2026-10-24); detailed protections and residual-risk disposition pending.** The risk is **not** resolved. |
| Approved direction | Keep the Q10 availability rule (409 `insufficient_stock` above availability). Keep the public stock labels (`in_stock`, `low_stock`, `out_of_stock`) unless separately approved. Retain the current refusal limit and its outage behaviour (below). Any change to API response behaviour, or any control that affects the approved API contract, needs a documented, reviewed implementation plan first. |
| Current control (retained) | Responses never contain stock quantities: the public catalogue shows only `stock_status`, and cart lines show only a line status. Each 409 `insufficient_stock` counts per client network and per cart owner (a customer ID, or a prefix of the guest token's hash). After **20** refusals per **15 minutes** (`CART_STOCK_REFUSALS_PER_WINDOW=20`, `CART_STOCK_REFUSAL_WINDOW_SECONDS=900`), adding units or raising a quantity answers 429 `rate_limited` with `Retry-After`. Lowering a quantity, removing a line and reading the cart are never limited. |
| Redis outage (retained) | Fail open for cart quantity changes: the probe limit is skipped, with a WARNING on every occurrence ("Cart stock-probe limit skipped…", "Cart stock refusal not counted…"). Failing closed would block every quantity change in every existing cart. |
| Monitoring | WARNING "Cart stock-probe limit reached (ip or owner)" when the limit is hit. No IP address, token or quantity is logged. |
| Remaining inference paths | (1) **Repeated quantity attempts and successful probes:** each yes/no answer at a quantity reveals whether that many units are available. Stock from 0 to 99 (100 values) can be found in at most 7 requests by binary search (⌈log₂ 100⌉ = 7). Only refusals count, and successful requests are free, so one SKU costs at most 7 counted refusals: about 3–6 SKUs per network or owner per 15 minutes. (2) **Merge responses:** Q10 caps merges by availability, and the response reports `added_quantity` and the resulting line quantity. A customer whose own line plus a guest line exceed stock learns the exact available quantity (below 99) from one merge, and merges are not counted. (3) **Repeated cart reads and status changes:** reading is never limited, and a line shows `insufficient_stock` once stock falls below its quantity, so its holder can watch an availability boundary as often as they like. (4) **Public stock labels:** `low_stock` discloses that availability is at or below the variant's threshold (coarse availability, approved in module 6). **The refusal limiter slows probing; it does not eliminate stock inference.** |
| Dependency | Cart checks are not reservations. Module 14 checkout must independently re-check and reserve stock in its own transaction (`create_order_with_reservations`). |
| Options for the pending details | Leave `added_quantity` out of the merge report (the resulting line quantity would still show it, so this only helps together with the next option); report merged lines without their resulting quantity until the cart is read; count merges and repeated `insufficient_stock` reads towards the probe limit; require an account to hold a cart (conflicts with approved guest checkout, PR-05 and B7); cap silently (breaks Q10's "refuse"); stop enforcing availability in the cart (conflicts with Q10). Each changes an approved response or rule, so each needs the reviewed plan above. |
| Evidence | `test_refusals_never_reveal_a_quantity`, `test_repeated_refusals_are_limited_but_lowering_and_removing_still_work`, `test_the_probe_limit_follows_the_owner_across_networks`, `test_the_probe_limit_is_skipped_with_a_warning_when_redis_is_down`. |

## S5 — Promotion-code guessing (module 13)

| Aspect | Decision |
| --- | --- |
| Status | **Approved (project owner, 2026-10-25), with exactly these settings.** Implemented. |
| Risk | `POST /cart/apply-code` tells a valid, active code from an invalid one, so codes could be guessed by repeated requests. Unknown, draft and disabled codes all answer the same 422 `promotion_unavailable`. |
| Limit | **20 refused codes per 15 minutes (fixed window), per client network and per cart owner.** A refused code is a 422 `promotion_unavailable` or `promotion_not_applicable`. Beyond the limit, `POST /cart/apply-code` answers **429 `rate_limited` with `Retry-After`**, even for a valid code. |
| Not counted, never limited | Successful applies are not counted. `DELETE /cart/code` is never limited. Requests refused for another reason (404 `cart_not_found`, 422 schema validation) are not counted: no code was checked. |
| Keys | `CartRateLimiter` on the shared Redis store: `rl:cart_code:ip:<client network>` (the S1/S3 network: IPv4 address, IPv4-mapped IPv6 as IPv4, or IPv6 /64; direct peer only) and `rl:cart_code:owner:<owner>` (`user:<id>` for a customer, a pseudonym of the guest token hash for a guest; never the raw token). The network key is shared by every identity on that network, so switching between a guest cart and a customer session, or starting new guest carts (themselves limited by S1), does not reset the count. |
| Redis outage | **Fail open, as S3:** the limit is skipped and each skipped check or uncounted refusal is logged as a warning ("Promotion-code limit skipped", "Promotion-code refusal not counted"). Applying a code reserves nothing, so a skipped limit does not affect stock or usage limits. |
| Settings | `CART_CODE_REFUSALS_PER_WINDOW=20`, `CART_CODE_REFUSAL_WINDOW_SECONDS=900` (`app/core/config.py`; `.env.example`). |
| Evidence | `backend/tests/integration/test_promotions_api.py`: `test_refused_codes_are_limited_with_retry_after_and_the_window_expires`, `test_not_applicable_codes_count_too`, `test_successful_applies_and_removal_never_use_the_budget`, `test_the_limit_follows_the_cart_owner_across_networks`, `test_the_network_limit_covers_guests_and_customers_alike`, `test_the_code_limit_is_skipped_with_a_warning_when_redis_is_down`. |
| Residual risk | A distributed attacker using many networks and fresh guest carts can still try 20 codes per network per 15 minutes; codes should not be guessable (length and randomness of codes is an operational choice). |

## S6 — Guest order lookup (module 14)

| Aspect | Decision |
| --- | --- |
| Status | **Policy approved by the project owner on 2026-10-25 (module 14 D-O3), with exactly these settings. Implemented and verified (evidence below).** |
| Risk | `POST /orders/lookup` returns an order to anyone who knows its number and phone (RE-026 B7); without a limit, phones could be guessed for a known number, or numbers for a known phone. |
| Limit | **5 failed lookups per order number and 20 failed lookups per IP, per 15 minutes (fixed window), on independent `order_lookup` counters.** A failed lookup is any 404: an unknown number or a wrong phone. Beyond either limit the request answers **429 `rate_limited` with `Retry-After`** before the database is read, even with the right phone. Successful lookups are not counted. |
| Keys | `LoginRateLimiter` with prefix `order_lookup` on the shared Redis store: `rl:order_lookup:id:<HMAC pseudonym of the order number>` (keyed with `AUDIT_HMAC_KEY`; the number itself is never stored) and `rl:order_lookup:ip:<peer address>` (direct peer only, as login). Separate settings, so a change to the login values does not move these. |
| Redis outage | **Fail closed:** the limit is checked first, so while the store is unreachable every lookup answers 503 `order_lookup_unavailable` with the same body whether the order exists, the phone matches or neither; nothing about the order is revealed. If the store fails only while a refusal is being counted, that request still answers its 404 (a 503 there would reveal a miss) and the error is logged. |
| Also covers | Guest payment initiation and status (module 15, `/payments/{order_number}/...`), which use the same order number + phone proof (§7 Q17) and count failures on the same `order_lookup` counters, so the three routes share one budget. |
| Settings | `ORDER_LOOKUP_MAX_FAILURES_PER_ORDER=5`, `ORDER_LOOKUP_MAX_FAILURES_PER_IP=20`, `ORDER_LOOKUP_WINDOW_SECONDS=900` (`app/core/config.py`; `.env.example`). |
| Evidence | `backend/tests/integration/test_order_lookup_limits.py`: `test_the_policy_values_are_the_approved_ones`, `test_five_failures_per_order_number_then_429_until_the_window_ends`, `test_unknown_numbers_count_like_wrong_phones`, `test_successful_lookups_are_not_counted`, `test_twenty_failures_per_ip_across_order_numbers`, `test_an_unreachable_store_answers_503_for_hits_and_misses_alike`, `test_a_store_lost_while_counting_still_answers_the_404`; real Redis across two processes: `backend/tests/postgres/test_pg_checkout.py::test_concurrent_failed_lookups_are_counted_exactly_on_the_shared_store`. |
| Residual risk | Requests arriving together may each pass the check before the first failure is counted, so a burst can exceed 5 failures (the concurrency test allows up to its burst size); every failure is still counted exactly, so the number is refused from then on. A distributed attacker gets 5 phone guesses per number per 15 minutes across all IPs. |

## S4 — Merge audit

| | |
| --- | --- |
| Status | **Approved (project owner, 2026-10-24).** Implemented. |
| Problem | A merge moves a guest cart's items into a customer account and makes the guest token unusable. Customer profile and address changes are already audited (`user.profile.update`, `address.*`); the Technical plan §6 asks to "audit important changes" without defining them for customers. |
| Decision | A successful `POST /api/v1/cart/merge` writes one `cart.merge` record through `AuditService.log_event` in the merge's own transaction (`app.db.transaction.atomic`), so a rolled-back merge leaves no record. Failed or repeated merges (404) write no successful-merge record; concurrent merges of one guest cart write exactly one. Other cart changes are not audited (D-C9). |
| Metadata (approved as is) | `actor_user_id` (the customer), `entity_type` `cart`, `entity_id` (the customer cart ID), and a `change_summary` with `guest_cart_id`, `guest_lines`, `merged`, `capped`, `excluded`, `units_added` and `status` `success`. Like every audit record written by `AuditService.log_event` (ADR-006), it also holds the sanitised IP address and user agent, the record's timestamp, and **`actor_identifier_snapshot`: the customer's email (or phone if there is no email)**. That snapshot is personal data, retained so the audit stays meaningful if the user is later anonymised. It **never** holds the guest token, its hash, the session token, the `Authorization` value or any other credential. `audit_records.request_id` exists but nothing in the application sets it. |
| Permissions | The existing INSERT on `audit_records` (ADR-006); no new grant. |
| Still open | Audit **retention** and **access** policy (ADR-006 "audit retention/redaction policy"); no retention period is set here. |
| Alternatives considered | Do not audit merges; audit every cart change (high volume, little investigative value); audit merges without the actor snapshot (it would need a change to the shared audit service, affecting every audit record). |
| Evidence | `test_a_merge_is_audited_with_ids_and_counts_only`, `test_a_failed_audit_rolls_the_merge_back`, `test_a_repeated_or_refused_merge_writes_no_audit`; `tests/postgres/test_pg_cart.py::test_concurrent_merges_of_one_guest_cart_add_its_units_once` (exactly one record). |

## Still open (not approved)

1. **S3 detailed protections and residual-risk disposition:** whether to accept the four remaining inference paths, or which reviewed changes to make (options above). Changes to API responses need a documented, reviewed implementation plan first.
2. **S1 clean-up** of never-reused guest carts: whether and when, and the scheduled job and DELETE grant on `carts` it would need.
3. **Frontend token storage** for the guest cart token and the customer session token (ADR-006 open item).
4. **Audit retention and access policy** (ADR-006 open item), including how long merge records with the actor snapshot are kept and who may read them.

## Consequences

- The S1 and S3 values are settings, so a later decision can change them without a code change.
- The header-based contract stands. The frontend integration guidance in `docs/api/endpoint-inventory.md` describes it.
- Task 11 remains not accepted. Its other open items are listed in `docs/qa/module-11-cart-acceptance.md`: the S3 details, human review, Module 12, TC-05 and staging.
