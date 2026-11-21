# Backend Implementation Plan

Status: **Approved by the project owner, 2026-10-23.** This approval also approves the delivery and promotion table columns in §5 (RE-026 B5) and the proposed defaults in §7 unless the owner changes them.

- Base: `dev` at `0f82f0f`. One branch per step: `feat/module-XX-name` for modules, as named in each step below. Each branch is merged into `dev` by pull request before the next starts.
- Source of truth: `docs/Backend Modules — Implementation Order.md` (aligned with the code on 2026-10-23; see its "Deviations" section).
- Decisions used: ADR-002 (schema, stock lifecycle), ADR-006 (auth, roles), ADR-007 (money), RE-026 (delivery, promotions, guest checkout).
- Card IDs: only IDs found in the repository are used (RE-004, RE-018, RE-026). Requirement and test IDs are from the PRD (PR-xx) and the QA/UAT checklist (TC-xx).

## 1. Status

Updated after every step. "Done" means every box of the module done checklist is ticked, except staging deployment, which is outside this repository.

| Step | Item | Status | Branch | Linked tests |
| --- | --- | --- | --- | --- |
| A1 | Fix anonymous audit-log flood | Done (2026-10-23; 408 tests pass) | `fix/audit-session-invalid-flood` | PR-15 |
| A2 | Money migration to whole-RWF integers (ADR-007) | Done (2026-10-23; 411 tests pass) | `refactor/money-integer-rwf` | TC-06, TC-18 |
| A3 | Error format, handlers, pagination envelope, health DB check | Done (2026-10-23; 421 tests pass) | `feat/error-format-pagination-health` | — |
| A4 | Role and permission updates (inventory, orders) | Done (2026-10-23) | `feat/staff-permissions-inventory-orders` | TC-16 |
| A5 | Public inventory check functions | Done (2026-10-23) | `refactor/inventory-public-checks` | — |
| A6 | Dev dependencies (mypy, python-dotenv); flaky default-address test | Done (2026-10-23; see A6 results) | `chore/dev-deps-flaky-address-test` | — |
| 1 | core — remaining: logging module | Done (2026-10-23; 453 tests pass) | `feat/module-01-core-logging` | — |
| 2 | auth — remaining: forgot/reset password | Done (2026-10-23; customers only) | `feat/module-02-password-reset` | TC-07 |
| 3 | users | Done (paths differ from the first plan; routes re-checked 2026-10-23) | — | TC-07, TC-16 |
| 4 | audit — remaining: date filter | Done (2026-10-23) | `feat/module-04-audit-date-filter` | TC-16 |
| 5 | categories & brands | Merged into `dev` (PR #22, 2026-10-23; see module 5 results); not Done: no recorded human review, no OpenAPI examples, linked TC tests not recorded in the QA checklist, no dev seed data | `feat/module-05-categories-brands` | TC-02, TC-16 |
| 6 | products | Merged into `dev` (PR #22, 2026-10-23; see module 6 results); not Done: no recorded human review, no OpenAPI examples, linked TC tests not recorded in the QA checklist, no dev seed data | `feat/module-05-categories-brands` (not `feat/module-06-products`) | TC-04, TC-16 |
| 7 | media | Implemented on `feat/module-07-media` with OpenAPI examples and the backend part of TC-21 recorded (2026-10-24; see module 7 results and `docs/qa/module-07-media-acceptance.md`); not Done: PR not yet reviewed, production media serving undecided (ADR-004), TC-21 storefront run blocked, teammates' local migration status unconfirmed | `feat/module-07-media`, PR #24 (first committed directly to `dev` as `9392d4f`; reverted by PR #23, merged 2026-10-24) | TC-21 |
| 8 | import | Implemented on `feat/module-08-import`, not committed (2026-10-24; see module 8 results and `docs/qa/module-08-import-acceptance.md`); not Done: no commit, PR or review yet, TC-15 business UAT open, not on staging | `feat/module-08-import` | TC-15 |
| 9 | search | Implemented on `feat/module-09-search` (2026-10-24; see module 9 results and `docs/qa/module-09-search-acceptance.md`); not Done: no PR or review yet, TC-02/TC-03 storefront runs open; stacked on module 8 (not yet in `dev`) | `feat/module-09-search` | TC-02, TC-03 |
| 10 | inventory | Implemented on `feat/module-10-inventory` (2026-10-24; see module 10 results and `docs/qa/module-10-inventory-acceptance.md`); not Done: no PR or review yet, expiry job not scheduled in any environment; stacked on modules 8 and 9 | `feat/module-10-inventory` | TC-13, TC-14, TC-16 |
| 11 | cart | Implemented on `feat/module-07-media`, not committed (2026-10-24; see module 11 results and `docs/qa/module-11-cart-acceptance.md`); not Done: no review yet, delivery fee/grand total waits for module 12, ADR-008 decided in part on 2026-10-24 (S1, S2, S4 approved; S3 direction approved, details and residual risk pending) | `feat/module-07-media` (owner's branch decision; not `feat/module-11-cart`) | TC-05 |
| 12 | delivery | Implemented on `feat/module-12-delivery`, not committed (2026-10-24; see module 12 results and `docs/qa/module-12-delivery-acceptance.md`); not Done: no review yet, seed values are placeholders | `feat/module-12-delivery` | TC-17 |
| 13 | promotions | Implemented on `feat/module-12-delivery` (current branch), not committed (2026-10-25; see module 13 results and `docs/qa/module-13-promotions-acceptance.md`); not Done: no review yet, redemption at checkout waits for module 14 | `feat/module-13-promotions` | TC-06 |
| 14 | orders & checkout | Implemented on `feat/module-12-delivery` (current branch), not committed (2026-10-25; see module 14 results and `docs/qa/module-14-checkout-acceptance.md`); not Done: no review yet, payments are module 15 | `feat/module-14-orders-checkout` | TC-06, TC-07, TC-12, TC-13, TC-14 |
| 15 | payments | Implemented in the working tree of `feat/module-12-delivery`, not committed (2026-10-25; see module 15 results and `docs/qa/module-15-payments-acceptance.md`); not Done: no review yet, real providers wait for ADR-003 (§7 Q21) | `feat/module-15-payments` | TC-08 – TC-12 |
| 16 | invoices | Implemented on `feat/module-16-invoices`, pending PR into `dev` (2026-10-26; see module 16 results and `docs/qa/module-16-invoices-acceptance.md`); not Done: no review yet; TC-18 blocked until Finance approves the actual invoice PDF, template and tax display (PR-14); delivery-note states are the owner's proposed default pending Product/Operations approval; recovered invoice date provisional pending Finance | `feat/module-16-invoices` | TC-18 |
| 17 | notifications | Implemented on `feat/module-17-notifications`, rebased onto `origin/dev` at `4475eb9` (frontend phase 1 merge); pushed to `origin/feat/module-17-notifications` up to `6a2d1f3`, and the deterministic payment-race test fix committed locally on top, not pushed (2026-10-26/28; see module 17 results and `docs/qa/module-17-notifications-acceptance.md`); not Done: no review yet; real SMS/email delivery blocked until ADR-005 is decided (§7 Q22: mock only), so TC-19 can be run only against the mock; message wording and language unapproved; retry, lease and schedule values unapproved | `feat/module-17-notifications` | TC-19 |
| 18 | reports | Implemented on `dev`, based on `96c6324` (PR #30; commit and push state: see the Git history) (2026-10-28; see module 18 results and `docs/qa/module-18-reports-acceptance.md`); not Done: no review yet; the sale date, top-products ranking and limit, range limit and empty-period presentation are engineering defaults awaiting approval (R-1 to R-4), the exported columns need the product owner's sign-off (R-7, PRD "export approved data"), auditing of exports is an open policy choice (R-6); full CI test commands passed on 2026-10-28 (1,768 passed, exit 0; PostgreSQL 102 passed, exit 0, on a second run after one transient connection reset in a module 12 test); UAT scenario 7 not run | `feat/module-18-reports` (the owner set `dev` as the target) | PR-13, UAT scenario 7 |
| 19 | settings & content | Implemented on `feat/frontend-phase-1` (2026-10-29; see module 19 in §5). It replaces the module 19 first merged into `dev` from `feat/module-19-settings-content` (PR #32; owner decision 2026-10-29); not Done: no review yet; final page texts and contact details are business content to supply and approve (TC-20) | `feat/frontend-phase-1` | PR-15, TC-20; contact details for PR-01, PR-04 |
| FP1 | Frontend phase 1 backend: finance role, B1 category images and descriptions plus brand logos, B2 `is_featured`, B3 `sort_by=bestselling`, B4 `created_at`, B6 CORS, ADR-009 image storage and pipeline (approved 2026-10-25) | Merged into `dev` locally on 2026-10-26 together with checkpoint 1b (see "Frontend phase 1 backend" and "Checkpoint 1b" below; migration heads joined by merge revision `a1d9c3e5f7b2`); not Done: no PR review | `feat/frontend-phase-1-backend` | TC-02, TC-04, TC-16, TC-21 |
| CP2 | Development catalogue seed, production seed guard, `seed_dev.py` threshold 50 000 (approved 2026-10-26) | Implemented on `feat/frontend-phase-1` (2026-10-26; see "Checkpoint 2" below); not Done: no review yet | `feat/frontend-phase-1` | TC-02, TC-04 |
| 20 | reviews (SC-01, approved 2026-10-27) | Backend done on `feat/frontend-phase-1` (2026-10-27): part 1 (tables, product rating fields, `min_rating`, `sort_by=top_rated`) and part 2 (review links, submission, moderation, public list, seed). Screens: product page (phase 3), WriteReview (phase 5), admin Reviews (phase 6) | `feat/frontend-phase-1` | — |
| 21 | wishlist (SC-01, approved 2026-10-27) | Implemented on `feat/frontend-phase-1` (2026-10-27); not Done: no review yet | `feat/frontend-phase-1` | — |

## 2. How every step is delivered

For each step: models + Alembic migration (upgrade, downgrade to the previous revision and upgrade again, then `alembic check`); Pydantic schemas for every body, query and path parameter; service rules; router with `require_permission` on every staff endpoint; runtime-role grants for new tables in `scripts/provision_runtime_role.py`, pinned in `tests/unit/test_runtime_role_grants.py` and listed in ADR-006; dev seed data in `scripts/seed_dev.py` (refuses to run outside `APP_ENV=development`); tests (service unit tests, PostgreSQL integration tests for the main endpoints, a forbidden-role test, and real-HTTP tests where concurrency matters); full suite with Postgres + Redis, Ruff, and a check of `/docs`; then the endpoint inventory (`docs/api/endpoint-inventory.md`), this status table, and a short summary with a suggested commit message. Then stop for approval.

## 3. Target permission matrix

Permissions are added only when the feature that uses them is built (ADR-006). Administrator keeps every permission. "—" means no access. The roles and permissions are defined in code only (`backend/app/core/roles.py`); the database holds just the role names (a check constraint), so a matrix change needs no migration.

**Final staff matrix (approved by the project owner on 2026-10-26, checkpoint 1b).** It replaces the four-role table of 2026-10-23: finance became a fifth role on 2026-10-25, and on 2026-10-26 `catalog:read` and `content:manage` were added, operations gained `inventory:adjust` and `delivery:read`, management gained `catalog:read`, `inventory:read`, `orders:read`, `reports:read` and `content:manage`, and sales gained `promotions:read`. Finance changes nothing.

| Permission | Used by | Administrator | Sales | Operations | Management | Finance | Added in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `staff:self_read` | own staff identity | ✓ | ✓ | ✓ | ✓ | ✓ | exists |
| `staff:read`, `staff:manage` | staff accounts | ✓ | — | — | — | — | exists |
| `audit:read` | audit log | ✓ | — | — | — | ✓ | exists; finance 2026-10-25 |
| `catalog:manage` | categories, brands, products, variants, images, imports, bulk upload | ✓ | ✓ | — | — | — | 5 |
| `catalog:read` | staff product list and detail (drafts included) | ✓ | ✓ | ✓ | ✓ | — | 2026-10-26 |
| `inventory:read` | stock list and figures | ✓ | ✓ | ✓ | ✓ | — | A4; management 2026-10-26 |
| `inventory:adjust` | stock adjustments | ✓ | ✓ | ✓ | — | — | A4; operations 2026-10-26 |
| `orders:read` | staff order list and detail, staff invoice download | ✓ | ✓ | ✓ | ✓ | ✓ | 14; management 2026-10-26 |
| `orders:fulfil` | status changes, cancellation, assignment, delivery note | ✓ | — | ✓ | — | — | A4 |
| `delivery:read` | view zones, fees and fee history | ✓ | — | ✓ | ✓ | — | 12; operations 2026-10-26 |
| `delivery:manage` | edit zones and fees | ✓ | — | — | — | — | 12 |
| `promotions:read` | view promotions | ✓ | ✓ | — | ✓ | — | 13; sales 2026-10-26 |
| `promotions:manage` | create, edit, disable promotions | ✓ | — | — | — | — | 13 |
| `content:manage` | storefront banners; policy pages (module 19) | ✓ | — | — | ✓ | — | 2026-10-26; pages 2026-10-29 |
| `settings:read` | view settings such as the free-delivery threshold | ✓ | — | — | ✓ | — | 12 |
| `settings:manage` | change settings | ✓ | — | — | — | — | 12 |
| `reports:read` | reports and exports | ✓ | — | — | ✓ | ✓ | declared 2026-10-25; used by 18 (built) |
| `payments:read` | reconciliation list | ✓ | — | — | ✓ | ✓ | 15; finance with the merge of 2026-10-26 (matrix above) |
| `payments:manage` | any change to payment data | ✓ | — | — | — | — | 15 |
| `invoices:recover` | issue a paid order's missing invoice (recovery) | ✓ | — | — | — | — | 16 (project owner's preference for a dedicated permission; administrator only by convention) |
| `notifications:manage` | notification log and retry | ✓ | — | — | — | — | 17 |
| `reviews:moderate` | approve or reject customer reviews | ✓ | ✓ | — | — | — | 20 part 2 (SC-01, 2026-10-27) |
| `quotes:manage` | business quote requests: list and status | ✓ | ✓ | — | — | — | 19 (owner decision 2026-10-29) |
| `sellers:read` | seller applications, stores and owner contact details | ✓ | — | — | — | — | ADR-014 phase 1 (owner decision 2026-11-21) |
| `sellers:manage` | approve, reject, suspend, reinstate stores; commission override | ✓ | — | — | — | — | ADR-014 phase 1 (owner decision 2026-11-21) |

## 4. Before module 5 (in this order)

### A1 — Anonymous audit-log flood
- Problem: `get_current_session` (`app/core/dependencies.py:39-48`) writes an `auth.session_invalid` audit row for every request with an unknown bearer token. Anyone can grow the append-only `audit_records` table without limit.
- Fix: an unknown token (no session row with that hash) returns 401 and writes nothing. A token that matches an expired or revoked session is audited at most once per session per 15 minutes (checked against the existing `audit_records` index on entity type, entity ID and time, so no Redis dependency). The number of rows is then bounded by the number of real sessions.
- Trade-off: random-token probing is no longer audited; tokens are 256-bit random, so probing is not a realistic attack. Record this in ADR-006.
- Tests: unknown tokens write no audit rows; repeated use of a revoked token writes one row per window; 401 responses unchanged.

### A2 — Money migration (ADR-007)
- Migration: one revision converting `product_variants.price`, `compare_at_price`; `orders.subtotal`, `discount_total`, `delivery_fee`, `tax_total`, `total`; `order_items.unit_price`, `line_subtotal`, `discount_amount`, `tax_amount`, `line_total`; `payment_attempts.amount`; `delivery_fee_rules.fee`; `discount_redemptions.amount` from `Numeric(14,2)` to `BIGINT`. The upgrade aborts with a clear message if any value has a fractional part. It adds a `<= 999999999999` check per amount. The downgrade converts back without loss. `discounts.value` is replaced in module 13 together with the rest of the promotion schema (no code uses it).
- Code: models become `Mapped[int]` with `BigInteger`. Catalogue schemas become `price: int`. The `min_price`/`max_price` filters become integers. `app/services/pricing.py` moves to `int` with `MAX_AMOUNT = 999_999_999_999`. Every test and fixture with decimal amounts is updated.
- API change: amounts are JSON numbers (`1500`) instead of strings (`"1500.00"`). The frontend does not read prices yet.

### A3 — Error format, pagination envelope, health DB check
- `app/core/errors.py`: `AppError(status, code, message, details=None)` with `BadRequest`, `Unauthorized`, `Forbidden`, `NotFound`, `Conflict`, `TooManyRequests`, `ServiceUnavailable`. Handlers in `app/main.py` for `AppError`, Starlette `HTTPException` (unknown routes, 405), `RequestValidationError` and unexpected exceptions (500 `internal_error`, logged without request bodies).
- Body: `{"error": {"code": "...", "message": "...", "details": ...}}`. For 422 the code is `validation_error` and `details` lists `{type, loc, msg}` without the submitted values (ADR-006). Headers stay (`WWW-Authenticate`, `Retry-After`). The 33 `raise HTTPException(...)` calls in 9 files, including the catalogue's manual 422s, become `AppError` subclasses with stable codes (e.g. `not_found`, `email_taken`, `insufficient_stock`, `invalid_transition`, `rate_limited`).
- `ErrorResponse` and `app/api/v1/responses.py` describe the new shape in OpenAPI.
- Pagination: `Page[T] = {items, total, page, size}` with query parameters `page` (≥ 1) and `size` (1–100, default 20). This changes `GET /catalog/products` (`page_size` → `size`), `GET /staff` and `GET /audit-logs` (`limit`/`offset` and a bare list → `page`/`size` and the envelope).
- Health: `GET /health` runs `SELECT 1` with a short timeout. It returns `{"status": "ok", "database": "ok"}`, or 503 `database_unavailable`.
- Tests: about 22 assertions on `detail` and the OpenAPI contract test are updated; new tests cover each error class, the 422 shape, the 500 handler not leaking data, pagination bounds and health with the database down.

### A4 — Roles and permissions
- `inventory:read` → administrator, sales, operations. `inventory:adjust` → administrator, sales. `orders:fulfil` → administrator, operations (§3).
- ADR-006 matrix, endpoint inventory and OpenAPI descriptions updated. Allow and deny tests for every role on the inventory and order fulfilment endpoints (TC-16 pattern).

### A5 — Public inventory checks
- Rename `_check_quantity` → `check_quantity` and `_check_sellable` → `check_sellable` in `app/services/inventory.py` (module owner approved 2026-10-23), update every caller including `app/services/pricing.py`, and remove the comment there about private helpers.

### A6 — Small fixes

Results (2026-10-23):
- `mypy` 1.20 and `python-dotenv` are dev dependencies; `uv.lock` updated (`uv` installed into `.venv`, Q24). mypy reports 11 errors in 5 files (3 in `app/api/v1/endpoints/inventory.py` response maps, 2 in `app/services/inventory.py` Optional returns, 6 in tests). All 11 already existed on `dev` at `0f82f0f`; none came from A1–A5. mypy stays out of CI until they are fixed (Q23). **Update:** commit `64aa67e` fixed all 11 errors; `py -m mypy .` from the repository root now passes (128 source files).
- The flaky address test did not fail in 25 isolated runs, 5 runs of `test_pg_http.py` and 6 full-suite runs. The code path is correct (user row lock before counting, plus the partial unique index on defaults), so no fix was guessed. The test now records each request's status and error code and the stored counts in its failure message, so a recurrence identifies its cause.

Plan:
- Add `mypy` and `python-dotenv` to the `dev` dependency group and update `uv.lock`. Run mypy once and report the result (§7 Q23).
- Flaky `tests/postgres/test_pg_http.py::test_concurrent_first_addresses_produce_exactly_one_default` (failed once in five runs; the failing assertion was not captured). Reproduce with repeated runs, record which assertion fails, and fix the cause. The service already serialises on the user row lock, so the suspects are request timeouts or pool limits under ten parallel requests across two processes. No retries or skips.

### Module 1 — core (remaining)
- `app/core/logging.py`: one logging configuration (level from `LOG_LEVEL`, added to `.env.example`), used by `main.py` and the scripts; a test that request bodies, tokens and passwords never reach log records.

### Module 2 — auth (remaining: forgot/reset password)
- Table `password_reset_codes`: `id`, `user_id` (FK, cascade), `code_hash` (HMAC-SHA256 with a server key), `channel` (`email`|`sms`), `expires_at`, `attempts`, `consumed_at`, `created_at`.
- `POST /auth/forgot-password {identifier}` → always 202 with the same body (no account enumeration), rate-limited like login. `POST /auth/reset-password {identifier, code, new_password}` → checks the code, sets the password, revokes every session, audits `auth.password_reset`.
- Rules (proposed, §7 Q2): 6-digit code, 15-minute lifetime, 5 attempts, a new request invalidates older codes.
- Delivery depends on a notification provider (module 17, ADR-005). See §7 Q1.
- Tests: enumeration-safe responses, expiry, attempt limit, session revocation, rate limit.

### Module 4 — audit (remaining)
- `GET /audit-logs` gains `from` and `to` (timestamps, inclusive range validated) on top of the existing filters, using the A3 envelope.

## 5. Modules 5–21

### 5 — categories & brands (RE-018)
- Endpoints: `GET /catalog/categories` returns the active category tree (nested `children`); `GET /catalog/brands` returns active brands with a `product_count` of public products. Staff: `POST /staff/categories`, `PATCH /staff/categories/{id}`, `DELETE /staff/categories/{id}`, and the same for `/staff/brands` (`catalog:manage`).
- Model: no new table. The slug is generated from the name (lowercase ASCII, hyphens, numeric suffix on collision) and editable.
- Rules: a category cannot become its own ancestor (cycle check); DELETE removes a category or brand only when it has no products and no child categories, otherwise 409 (deactivate with `is_active=false` instead); every change is audited.
- Route fix: `/staff/{staff_id}` routes switch to the `{staff_id:uuid}` path converter, so that `/staff/categories`, `/staff/orders` and similar can never be captured by the staff-account routes. Staff-account URLs do not change.
- Tests: tree building, cycle rejection, slug collisions, delete conflict, forbidden for operations/management/customer.

Results (2026-10-23, branch `feat/module-05-categories-brands`):
- Built as specified. `catalog:manage` goes to administrator and sales (§3). The runtime role gets INSERT, UPDATE and DELETE on `categories` and `brands` (ADR-006). The staff-account routes use `{staff_id:uuid}`.
- Tests: `tests/unit/test_slugs.py` (11), `tests/unit/test_catalog_admin_errors.py` (2), `tests/integration/test_catalog_admin_api.py` (45) and `tests/postgres/test_pg_catalog.py` (4, real HTTP on the runtime role, including concurrent slug allocation and opposite parent changes). The full suite passes: 498 passed, 0 failed, 0 skipped. mypy passes: commit `64aa67e` fixed the 11 errors recorded under A6.
- Deletes use a plain SQL `DELETE`, so the database's RESTRICT foreign keys are the final guard. An ORM delete would have set referencing products' `brand_id` to NULL. A delete refused by a foreign key (`23001` restrict_violation for these RESTRICT keys, `23503` for NO ACTION keys) is reported as 409 `*_in_use`; any other integrity error is re-raised.
- Decisions within the plan:
  - A rename keeps the slug; a new slug must be sent explicitly. An explicit slug that is taken returns 409 `slug_taken` instead of being silently suffixed.
  - A cycle returns 409 `category_cycle`; an unknown `parent_id` returns 422.
  - A request that changes nothing is not audited.
  - Category changes, and separately brand changes, are serialised by an advisory lock.
- Known differences, open for the owner:
  - With the `:uuid` converter, a non-UUID staff ID returns 404 instead of 422.
  - The public tree hides a category whose parent or any ancestor is inactive. Product visibility (module 6) still checks only the product's own category.
  - No staff list or read routes exist for categories and brands; the plan does not include them.
- Dev seed data (§2): none was added for this module, and `scripts/seed_dev.py` does not exist yet. Categories and brands are business catalogue input, which ADR-002 forbids inventing ("do not invent categories, brands, …"; PRD §7 assigns final categories to the business owner). Tests create their own disposable rows.
- Merged into `dev` with PR #22 (merge commit `5106b86`, 2026-10-23), together with module 6. CI passed on the PR (backend and frontend jobs). The PR has no recorded human review; only an automated review comment.
- Verification on `dev` at `5106b86` (2026-10-24), modules 5 and 6 together: full suite 600 passed, 0 failed, 0 skipped; Ruff lint and format pass; mypy passes; `uv lock --check` passes; Alembic has one head (`37b61c6765c1`).
- Done checklist items still open: human PR review, OpenAPI examples, linked TC tests (TC-02, TC-16) run and recorded in the QA checklist, and dev seed data (see above). Staging deployment is outside this repository.

### 6 — products
- Endpoints: `POST /staff/products`, `PATCH /staff/products/{id}` (fields and `status`: draft, active, hidden, archived); `POST /staff/products/{id}/variants`, `PATCH /staff/products/{id}/variants/{variant_id}`, `DELETE /staff/products/{id}/variants/{variant_id}` (`catalog:manage`).
- Model: no new table.
- Rules: slugs unique and generated from the name; only `active` products in active categories (and active brands) are public; a variant DELETE deactivates it (`is_active=false`) because variants are referenced by stock and orders; price changes are audited with old and new values.
- Public stock status: catalogue responses replace `available_quantity` with `stock_status` (`in_stock`, `low_stock` when available ≤ `low_stock_threshold` and the threshold > 0, `out_of_stock`) on both the product list and the product detail.
- Tests: slug generation, visibility rules, variant deactivation, price audit, no exact quantities in public responses, forbidden roles.

Results (2026-10-23, commit `3272976` on branch `feat/module-05-categories-brands`, merged with PR #22):
- Built as specified. No new table and no migration: the existing `products` and `product_variants` columns cover every field. All five routes require `catalog:manage` (administrator, sales). The runtime role gets INSERT and UPDATE on `products` and `product_variants`, and no DELETE (ADR-006).
- Tests: `tests/integration/test_product_admin_api.py` (50) and `tests/postgres/test_pg_products.py` (4, real HTTP on the runtime role, including concurrent slug allocation, one SKU created only once, and no DELETE privilege). Existing public-catalogue tests now check `stock_status` instead of `available_quantity`. Verification on `dev`: see the module 5 results.
- Decisions within the plan:
  - Slugs follow module 5: a rename keeps the slug, and a taken explicit slug returns 409 `slug_taken`. SKUs are unique (409 `sku_taken`) and may not contain whitespace or `/`, because they appear in `/inventory/{sku}`.
  - A new product is a `draft` unless `status` is sent. `category_id` and `brand_id` must exist (422); an inactive category or brand is allowed and keeps the product hidden.
  - `compare_at_price` is display only (§7 Q20). `in_stock` is kept beside `stock_status`; neither exposes a quantity.
  - A variant DELETE returns 204 and repeating it is a no-op; PATCH `is_active: true` reactivates the variant.
  - Long text, specifications and attributes are audited as changed, without their content.
- Known differences, open for the owner:
  - Product visibility checks the product's own category only, not its ancestors (see module 5).
  - Delivered on `feat/module-05-categories-brands`, not on the planned `feat/module-06-products`, so PR #22 covered modules 5 and 6.
  - The same commit changed the console log layout to uvicorn's (`INFO:     message`; module 1 logging). Redaction is unchanged, but timestamps and logger names are no longer printed. It also annotated a module 2 response map for mypy and added root `pytest.ini` and `ruff.toml`.
- Dev seed data (§2): none added, as for module 5.
- Done checklist items still open: as for module 5 (human PR review, OpenAPI examples, linked TC tests TC-04 and TC-16 recorded in the QA checklist, dev seed data).

### 7 — media
- Endpoints: `POST /staff/products/{id}/images` (multipart upload, optional `variant_id` and `alt_text`); `PATCH /staff/images/{id}` (`sort_order`, `alt_text`, `variant_id`); `DELETE /staff/images/{id}` (`catalog:manage`).
- Model: `product_images` gains `thumbnail_key`, `width` and `height`.
- Rules (§7 Q6–Q7, approved with this plan): JPEG, PNG or WebP up to 5 MB; the file must decode with Pillow (the declared content type is not trusted); metadata is stripped; it is saved at most 1600 px wide plus a 400 px thumbnail; it is stored under `MEDIA_ROOT` with a random key and served from `MEDIA_BASE_URL` (both added to `.env.example`).
- New dependencies: `Pillow` (decode, resize, strip metadata); `python-multipart` (required by FastAPI for file uploads).
- Tests: rejects wrong types, oversize and corrupt files; ordering; delete removes the files; forbidden roles.

Results (2026-10-24, on `dev`; no feature branch or PR was used for this module, as requested for the task):
- Built as specified. Migration `76768b844c03` adds nullable `thumbnail_key`, `width` and `height` to `product_images`, so existing rows stay valid, with checks that width and height are positive and set together. Dependencies `pillow` 13.0.0 and `python-multipart` 0.0.32 were added with `uv add`. New settings `MEDIA_ROOT` (relative values resolve against `backend/`) and `MEDIA_BASE_URL` are in `backend/.env.example`; `backend/media/` is git-ignored. All three routes require `catalog:manage` (administrator, sales). The runtime role gets INSERT, UPDATE and DELETE on `product_images` (ADR-006).
- Decisions (D1–D6, approved 2026-10-24):
  - D1: only with `APP_ENV=development` does the API serve `MEDIA_ROOT` itself, at `/media`. Staging and production need a web server, CDN or object storage at `MEDIA_BASE_URL`; that is **not configured** and stays open under ADR-004.
  - D2: public images keep `image_ref` and add `url`, `thumbnail_url`, `width` and `height`. Rows from before module 7 have no thumbnail or size (null).
  - D3: each image is turned upright from its EXIF orientation, rebuilt from raw pixels so no metadata survives, reduced to its first frame, resized to at most 1600 px wide and given a thumbnail at most 400 px wide (never enlarged). It is re-encoded in its own format: JPEG and WebP at quality 85 (lossy), PNG losslessly; resizing always loses detail. PNG and WebP keep transparency.
  - D4: uploads over 5 MB get 413 `file_too_large`. A middleware limits the whole request while it is received, and the file itself is checked against exactly 5 MB. Before answering 413, it discards the rest of the body up to 32 MB so clients can read the response. Files that are not valid JPEG, PNG or WebP get 422, and Pillow decompression-bomb checks count as invalid.
  - D5: a new image goes after the product's highest `sort_order`, under the product advisory lock; PATCH accepts any value of 0 or more; ties are ordered by ID.
  - D6: `variant_id` must be a variant of the same product (422); inactive variants are allowed; PATCH `variant_id: null` makes the image product-level.
- Files: keys are generated server-side (`products/<32 hex>.<ext>`), checked against a fixed pattern and confined to `MEDIA_ROOT`. Writes are atomic (temporary file, then rename). If an upload fails after writing (database or audit error), its files are removed. A delete commits the database change first, then removes the files; a file that cannot be removed is logged as a warning and is not reported as removed. No orphan clean-up job exists.
- Tests: `tests/unit/test_image_processing.py` (28), `tests/unit/test_media_storage.py` (20, including the upload limit), `tests/integration/test_image_admin_api.py` (25), `tests/integration/test_image_media_migration.py` (6: upgrade → downgrade → upgrade on a disposable test schema, constraints and `alembic check`), `tests/postgres/test_pg_images.py` (4, real HTTP on the runtime role). The runtime-grant and OpenAPI-contract tests were updated.
- Verification on `dev` (2026-10-24): full backend suite 683 passed, 0 failed, 0 skipped, 0 errors, exit code 0, in 8 minutes. An earlier full run had one setup error, a PostgreSQL connection timeout in module 6's `test_stock_status_boundaries[3-1-low_stock]`; that test then passed on its own (1 passed, exit code 0) and in the clean full run. Ruff lint and format, mypy, `uv lock --check` and a single Alembic head (`76768b844c03`) pass. `git diff --check`, the conflict-marker scan and the secret scan are clean.
- Known differences, open for the owner:
  - An oversized upload gets 413 before authentication is checked, because the size limit runs in front of the app.
  - `order_items.image_snapshot` is a plain string, not a foreign key. If checkout (module 14) stores an image key there, deleting that image later removes the file an old order points to.
  - Delivered on `dev`, not on the planned `feat/module-07-media`.
- Dev seed data (§2): none added; product images are business catalogue input.
- Done checklist items still open: a reviewed pull request (none was opened), OpenAPI examples, TC-21 run and recorded in the QA checklist, dev seed data, and production media serving (ADR-004). Staging deployment is outside this repository.

Recovery and completion (2026-10-24, branch `feat/module-07-media`):
- History: `9392d4f` was committed to `dev` without a pull request. PR #23 (`revert/module-07-media-from-dev`) reverts it; it was merged on 2026-10-24 (`e9c6a52`), and `dev` then matched `d884eae` exactly. `feat/module-07-media` holds the same work as `290a841`, whose tree is identical to `9392d4f` (`555b2de`). The follow-up commits on that branch add what was missing. Merge order, checked with `git merge-tree`: on top of PR #23 the branch merges without conflicts, and the result is exactly the branch tree. Into today's `dev` (which still contains `9392d4f`) it conflicts in 8 files, because both sides add the same files with different content. So PR #23 was merged first. `origin/dev` was then merged into the branch (`a02ada8`) without conflicts and without changing the branch's content.
- Added on the branch:
  - OpenAPI request, response and error examples for the three image routes and the public `CatalogImage`; the 409 `sort_order_full` response is now documented. `openapi_with_standard_errors` keeps route-specific 422 examples, which it used to drop.
  - Outside development the API refuses to start unless `MEDIA_BASE_URL` is a public `https://` URL. `MEDIA_ROOT` and `MEDIA_BASE_URL` are in the staging and production templates. `docs/deployment/media.md` lists what a host must provide.
  - Tests: malformed IDs, a failed file write (no row, no file, generic 500), no free `sort_order` (409), an oversized anonymous upload (413) next to a small one (401), the examples validated against the models, and every documented error example compared with the real response.
  - `docs/qa/module-07-media-acceptance.md`: the acceptance criteria with their evidence, the TC-21 record (backend part, with measured image sizes), and decisions D-M1 to D-M4. These cover production serving (ADR-004), 413 before authentication, image deletion and order history (for module 14), and seed data.
- Tests: `tests/integration/test_image_admin_api.py` now 32 (was 25), `tests/unit/test_media_storage.py` 37 (was 20); `tests/unit/test_password_reset_units.py` sets an https `media_base_url` for its production settings, which the new rule requires.
- Verification on the branch (2026-10-24, uv-managed `backend/.venv`, Python 3.14.0, SQLAlchemy 2.1.5, PostgreSQL 18 and Redis 7.4 in Docker):
  - `pytest --ignore=tests/postgres`: 645 passed, exit code 0. `pytest tests/postgres`: 62 passed, exit code 0. That is 707 in total, 0 failed and 0 skipped.
  - After a formatting fix to one test file: Ruff lint and format pass, `uv lock --check` passes, and the module 7 and contract tests pass again (126 passed).
  - One Alembic head (`76768b844c03`). The local development database reads `37b61c6765c1` (`alembic current`, read-only), so it never applied the module 7 migration.
- mypy baseline: `uv run mypy .` from the repository root (mypy 1.20.2) reports **4 errors in 3 files that module 7 does not change in those places**: `alembic/versions/c3a8e5f1d2b4…py:26`, `alembic/versions/528e6436c34e…py:45` and two at `app/repositories/catalog.py` (brand product counts). The same 4 errors appear on `d884eae` (dev before module 7) and on `290a841`, each checked in a separate worktree. The global interpreter (`py -m mypy .`, SQLAlchemy 2.0.51, no `redis` package) reports a different set of 5 errors. So the earlier "mypy passes" notes (A6, module 5 and the first module 7 results) do not hold in either environment today. mypy is not in CI (§7 Q23). These errors are not fixed here, because they are outside module 7.
- Open before Done: human review of the pull request; the ADR-004 decision on serving images outside development (D-M1); TC-21 on the storefront over a constrained connection and a decision on large PNG photos (F-1); confirmation of D-M2 and D-M4; staging deployment. Migration status, checked read-only on 2026-10-24: there are no GitHub environments, deployments or secrets, and the CI database is disposable. The local development database reads `37b61c6765c1` (`alembic current`). Teammates' local databases are not verified: anyone who ran `alembic upgrade head` on `dev` between `9392d4f` and PR #23 is at `76768b844c03`, and Alembic fails for them until PR #24 is merged.

### 8 — import
- Endpoints: `POST /staff/imports` (CSV or XLSX upload); `GET /staff/imports/{id}`; `GET /staff/imports/template?format=csv|xlsx` (`catalog:manage`).
- Table `import_jobs`: `id`, `created_by_user_id`, `filename`, `file_format`, `status` (`processing`|`completed`|`failed`), `total_rows`, `imported_rows`, `error_rows`, `errors` (JSONB list of `{row, field, message}`, capped at 1 000), `created_at`, `finished_at`.
- Rules: every row is validated first; valid rows are imported in one transaction and invalid rows are reported by row number and field (TC-15). Rows are matched by SKU: create or update (§7 Q3). Category and brand are referenced by slug. Up to 5 000 rows per file, processed within the request (the catalogue is 100–200 products).
- New dependency: `openpyxl` (read XLSX, write the template; reused by reports).
- Tests: mixed valid and invalid file, duplicate SKUs in one file, unknown category, formula and injection-like cells, template round trip, forbidden roles.

Results (2026-10-24, branch `feat/module-08-import`, not committed):
- Built as specified. Migration `9d820b74f718` (revises `76768b844c03`) creates `import_jobs` with the planned columns, plus `errors_truncated`, `updated_at` and checks on format, status, counts, the error cap and `finished_at`. `created_by_user_id` is RESTRICT. Dependency `openpyxl` 3.1.5 (`>=3.1.5,<4`, with `et-xmlfile` 2.0.0) was added with `uv add`; mypy ignores its missing type information. The runtime role gets SELECT, INSERT and UPDATE on `import_jobs` (ADR-006). All three routes require `catalog:manage`.
- File schema, row rules and error semantics: `docs/api/catalogue-import.md`. Decisions D-I1 to D-I11 (among them `product_slug` required, `attr:`/`spec:` columns, blank keeps, conflicts refused on every row, 10 MB limit, shared job access, injection rule, `opening_stock` needs `inventory:adjust`) are listed in `docs/qa/module-08-import-acceptance.md`.
- Transactions: the job is committed as `processing` first. Rows are checked, then applied in one transaction under the product-change advisory lock together with the job's final state and audit records. An unexpected error rolls the import back and marks the job `failed` in a new transaction.
- `ProductAdminService` methods now wrap `apply_product_create`, `apply_product_update`, `apply_variant_create` and `apply_variant_update`, which run in the caller's transaction. Route behaviour is unchanged; the module 6 tests pass as before.
- `UploadSizeLimitMiddleware` takes a message per route; a second instance limits `POST /api/v1/staff/imports` to 10 MB + 64 KB.
- Tests: `tests/unit/test_import_files.py` (30), `tests/unit/test_catalog_import_rows.py` (39), `tests/integration/test_catalog_import_api.py` (42), `tests/integration/test_import_jobs_migration.py` (12) and `tests/postgres/test_pg_imports.py` (4: runtime role, opening stock, concurrent imports of one new SKU in two processes). The runtime-grant test and the live OpenAPI inventory were updated.
- Verification (2026-10-24, uv `backend/.venv`, Python 3.14.0, PostgreSQL 18 and Redis 7.4 in Docker): `pytest --ignore=tests/postgres` 768 passed; `pytest tests/postgres` 66 passed (834 in total, 0 failed, 0 skipped). Ruff lint and format pass and `uv lock --check` passes. One Alembic head (`9d820b74f718`). mypy from the repository root reports the same 4 baseline errors as before module 7 and none from module 8.
- Timing (local): 5,000 new SKUs across 1,000 new products in 31.8 s; re-importing the same file in 1.7 s.
- Dev seed data (§2): none, as for modules 5–7; the import is how catalogue data is loaded.
- Open before Done: commit, pull request and human review; the TC-15 business UAT with the real catalogue spreadsheet; reviewer confirmation of D-I1 to D-I11; staging (the proxy must allow 10 MB + 64 KB bodies and about 60 s for the largest files).

### 9 — search
- Endpoint: `GET /catalog/products` keeps its filters and adds `sort_by` = `name` | `price` (lowest active variant price) | `newest`.
- Migration: a `search_vector` tsvector on `products` (name, model and brand name, `simple` configuration), maintained by a trigger that also fires on brand renames, plus a GIN index.
- Rule: `q` uses full-text search with prefix matching (`websearch_to_tsquery` plus `:*`) instead of substring matching (§7 Q5); an empty result returns 200 with an empty page.
- Tests: name, brand and model matches, prefix matches on model numbers, ranking and sort stability, combined filters.

Results (2026-10-24, branch `feat/module-09-search`, stacked on module 8 because its migration follows `9d820b74f718`):
- Built as specified. Migration `a3b4d2f1d8e6` adds `products.search_vector` (tsvector, `simple` configuration; name weight A, model B, brand name C) with a GIN index (`ix_products_search_vector`). The trigger `products_search_vector` recomputes the vector on every product insert and update; `brands_search_vector` recomputes that brand's products when its name changes. Existing rows are backfilled. The downgrade removes the triggers, functions, index and column without touching other data.
- Model numbers: the `simple` parser reads "GX-10" as "gx" and "-10", so a word containing punctuation is also indexed with the punctuation turned into spaces and with it removed. "GX-10", "GX 10", "gx10", "gx1" and "10" then all find GX-10. Plain words are indexed once, so quoted phrases keep their order.
- `q`: `websearch_to_tsquery('simple', q)`, with every word of the result made a prefix (`'word'` → `'word':*`) and reparsed with `to_tsquery`. The text is a bound parameter. Input without letters or digits gives an empty query that matches nothing (200, empty page). §7 Q5 applies: "iph" finds iPhone; "phon" does not.
- Sorting: `sort_by` is `name`, `price` (lowest active variant price; products without an active variant come last in both directions) or `newest` (`created_at`). Default directions are asc, asc and desc. Without `sort_by`, a search is ordered by `ts_rank` (best first) then name, and a listing by name. Product ID breaks every tie. The previous default (`sort_by=name`, `sort_direction=asc`) is unchanged for listings without `q`.
- Changed contract: `q` no longer matches literal substrings (`%`, `_`, `!` were literal before). Two existing tests were rewritten to the full-text rules: `test_catalog_validates_filters_and_hides_nonpublic_or_missing_slugs` now refuses `sort_by=popularity` instead of `price`, and the search test became `test_catalog_search_fields_punctuation_and_combined_filters`.
- Tests: `tests/integration/test_catalog_search.py` (47), `tests/integration/test_product_search_migration.py` (2) and `tests/postgres/test_pg_search.py` (1, runtime role, brand rename through the staff API).
- Runtime role: no new grants. The triggers run with the caller's existing SELECT on `brands` and UPDATE on `products`.

### 10 — inventory
- Endpoints: `GET /inventory?low_stock=&q=&page=&size=` (`inventory:read`): one row per SKU with on-hand, unavailable, reserved, committed, available and threshold. Existing `GET /inventory/{sku}` and `POST /inventory/{sku}/adjustments` are kept.
- Rules: low stock means available ≤ threshold with a threshold > 0. The low-stock alert is this filtered list (§7 Q9).
- Already done: reservation lifecycle, triggers, expiry job, idempotent adjustments.
- Tests: list and filter correctness under reservations, pagination, permission matrix.

Results (2026-10-24, branch `feat/module-10-inventory`, stacked on module 9):
- Built as specified, with no migration and no new grants. The effective path is `GET /api/v1/inventory` (`inventory:read`). It returns one row per SKU, active or not, ordered by SKU, in the standard page envelope. Each row has the `GET /inventory/{sku}` fields plus `product_id`, `product_name`, `variant_name`, `low_stock_threshold` and `is_low_stock`.
- One stock calculation: `app.services.inventory.stock_figures()` is a single SELECT (inventory balance plus one grouped pass over `active` and `committed` reservations). `availability()` (used by `GET /inventory/{sku}`, the adjustment response and the services) and the list both read from it, and `is_low_stock` is computed in the same SELECT as `available_quantity`. The list runs two queries per page (count and page) whatever its size. Sellability is computed in SQL by the same rule as before.
- Low stock: `available <= threshold AND threshold > 0`. `low_stock=true` is the low-stock alert (§7 Q9); `false` returns the others; omitted returns all.
- `q`: case-insensitive literal substring of the SKU, variant name or product name (decision D-V1 in the acceptance record; the plan does not define `q` here).
- Tests: `tests/integration/test_inventory_list_api.py` (21) and `tests/postgres/test_pg_inventory_list.py` (1, runtime role, two processes). The live OpenAPI inventory was updated. The existing inventory and reservation tests pass unchanged on the shared calculation.
- Operational follow-up: `scripts/expire_reservations.py` exists and is tested but is not scheduled anywhere. Until it runs on a schedule, overdue holds keep counting as reserved (ADR-002 / ADR-004).

### 11 — cart
- Endpoints: `GET /cart?zone=` (totals; the delivery fee and grand total are included when a zone is given); `POST /cart/items`; `PATCH /cart/items/{id}`; `DELETE /cart/items/{id}`; `POST /cart/merge` (customer).
- Model: `carts` and `cart_items` exist. Guests get a cart token (returned once in the body, sent back in `X-Cart-Token`, stored only as `guest_token_hash`; RE-026 B7).
- Rules (proposed, §7 Q10): 1–99 units per line and never more than currently available; inactive or hidden variants are flagged and excluded from totals; merge adds quantities, capped by availability; guest carts expire after 30 days. Totals always come from `pricing.quote_merchandise`, never from the client.
- Tests: guest and customer ownership (one owner can never see another's cart), tampered amounts rejected, merge, expiry, availability caps.

Results (2026-10-24, on `feat/module-07-media`, not committed):
- Built as specified, with no migration (the `carts` and `cart_items` tables from `8f534feaaedc` were enough). The runtime role gets SELECT, INSERT and UPDATE on `carts` and SELECT, INSERT, UPDATE and DELETE on `cart_items` (ADR-006). The routes are `/api/v1/cart`, `/api/v1/cart/items`, `/api/v1/cart/items/{item_id}` and `/api/v1/cart/merge`.
- Q10 (approved): 1–99 units per line, never more than available, flagged lines excluded from totals, merge capped by availability, guest expiry after 30 days. Totals come from `pricing.quote_merchandise`.
- Shared rules, not copies: `inventory.sellable_variants` (now also behind `check_sellable`) flags lines. `catalog.get_available_quantities`, used by the pricing service and the cart, now reads the module 10 `stock_figures` calculation.
- Decisions D-C1 to D-C9 are recorded in `docs/qa/module-11-cart-acceptance.md`: the first `POST` creates the guest cart; GET creates nothing; refuse rather than cap on add and update; cap on merge; the guest cart is `converted` after a merge and a retry gets 404; expiry 30 days after the last change, enforced on every access with no job; staff have no cart; the zone gives 503 until module 12.
- Tests: `tests/integration/test_cart_api.py` (47) and `tests/postgres/test_pg_cart.py` (4: concurrent first adds create one cart; concurrent merges add once; runtime-role grants), plus CORS preflight tests in `tests/unit/test_health.py`. The grant pins and the live OpenAPI inventory were updated.
- Security audit fixes (2026-10-24):
  - `X-Cart-Token` and `Idempotency-Key` are now allowed CORS headers. Before, browsers refused them; the `Idempotency-Key` gap dates from the stock-adjustment API.
  - Lines beyond the largest storable amount are flagged `amount_out_of_range` instead of answering 500, and adding or updating into that range is 422 (D-C10, D-C11).
  - D-C2 now states that stock can be probed.
  - Guest-cart rate limiting (S1), frontend token storage (S2), stock probing (S3) and merge auditing (S4) are **pending owner or security decisions**; none is approved.
- Security follow-up (2026-10-24, to the reviewer's engineering direction):
  - S1 is implemented: a guest-cart creation limit per client network, 10 per hour by default, with 429 `Retry-After`. It fails closed (503) when Redis is down.
  - S3 is implemented: a limit on repeated 409 `insufficient_stock`, 20 per 15 minutes by default, per network and per owner. Lowering and removing a line are never limited, and the limit is skipped with a warning when Redis is down.
  - S4 is implemented: one `cart.merge` audit record, written atomically with the merge.
  - Staff-flagged accounts without a role are refused, and a `*` CORS origin is refused at startup.
  - Project owner decisions (2026-10-24, ADR-008):
    - S1 is approved as built (10 per network per hour; fail closed on creation).
    - S2 is approved: keep the header transport; no cookies, CSRF middleware or BFF under Task 11.
    - S3: the direction is approved and the current limit and fail-open behaviour are retained; the detailed protections and residual-risk disposition are pending.
    - S4 is approved, including the actor snapshot.
    - Still open: S1 clean-up, frontend token storage, and audit retention and access.
  - Tests: `tests/integration/test_cart_security.py` (23) and `tests/unit/test_client_network.py` (11). `tests/postgres/test_pg_cart.py` is now 6: concurrent adds on one guest cart, and a merge racing guest adds, were added.
  - Completion pass: a request refused by the probe limit no longer uses up the creation budget, and a price change during a cart read is flagged instead of answering 500. The IPv4-mapped IPv6 peer bucketing was fixed after the ADR-008 review.

### 12 — delivery (RE-026 B1, B6)
- Endpoints: `GET /delivery/zones` (public: active zones with fee, COD availability and free-delivery threshold). Staff: `GET /staff/delivery/zones` (`delivery:read`), `POST /staff/delivery/zones`, `PATCH /staff/delivery/zones/{id}` (`delivery:manage`), `GET /staff/settings` (`settings:read`), `PATCH /staff/settings` (`settings:manage`, only `delivery.free_delivery_threshold` in this module).
- Tables (approval requested, RE-026 B5):
  - `delivery_zones`: `id`, `code` (unique), `name`, `district` (unique; Gasabo, Kicukiro or Nyarugenge), `cod_available` (bool, default true), `sort_order`, `is_active`, timestamps. The unused `coverage` JSONB column is dropped.
  - `delivery_fee_rules`: `id`, `zone_id`, `fee` (BIGINT RWF), `currency_code`, `is_active`, `starts_at`, `ends_at`, timestamps; at most one active rule per zone (partial unique index). Changing a fee closes the old rule and adds a new one in one transaction, so history is kept. The unused `rule_data` JSONB column is dropped.
  - `settings` (new): `key` (primary key), `value` (JSONB), `updated_by_user_id`, `updated_at`. Module 19 adds further keys.
- Rules: the zone is chosen from the delivery address district; addresses outside the three districts cannot be delivered to. Delivery is free when the merchandise subtotal after discount is at least the threshold. Fees are VAT-inclusive.
- Seeds: `scripts/seed_dev.py` adds the three zones (Nyarugenge 1 500, Kicukiro 2 000, Gasabo 2 000) and the 200 000 threshold, all **placeholders** to be replaced before launch. No production seed migration, so placeholders cannot reach production unnoticed.
- Tests: fee quote, threshold boundary (199 999 / 200 000), inactive zones, fee history, management can view but not edit, others forbidden.

Results (2026-10-24, on `feat/module-12-delivery`, not committed):
- Built as specified. Migration `b6f1d3a9c8e4` (after `a3b4d2f1d8e6`) changes the existing tables in place: `delivery_zones` gains `district` (unique, checked against the three districts), `cod_available` and `sort_order` and drops `coverage`; `delivery_fee_rules` drops `rule_data`, and its (zone, active) index is replaced by the partial unique index `uq_delivery_fee_rules_one_active_per_zone` plus a (zone, created_at) history index; `settings` is created. The upgrade refuses, changing nothing, if a legacy zone's district cannot be read from its name or code, if `coverage` or `rule_data` holds data, or if a zone has two active rules. The dev and test databases had no delivery rows.
- Permissions: `delivery:read` and `settings:read` for administrator and management; `delivery:manage` and `settings:manage` for administrator only (B6, §3).
- Runtime grants: SELECT, INSERT and UPDATE on `delivery_zones`, `delivery_fee_rules` and `settings`; no DELETE (ADR-006).
- Cart: `GET /cart?zone=<code>` now returns `delivery` and `grand_total` (two new response fields, null when no zone is sent; an additive change). The 503 `delivery_quote_unavailable` remains only for a zone without a current fee or an unset threshold; an unknown or inactive zone is 422 `delivery_zone_unavailable`. Carts have no discount until module 13, so the subtotal after discount is the merchandise subtotal of the available lines.
- `delivery_service.quote_for_district` gives module 14 the zone and fee from an address district; it is not called by any route yet.
- Decisions D-D1 to D-D9 are in `docs/qa/module-12-delivery-acceptance.md`.
- `scripts/seed_dev.py` seeds the placeholders (Nyarugenge 1 500, Kicukiro 2 000, Gasabo 2 000, threshold 200 000; **50 000 since 2026-10-26**, checkpoint 2, to match the storefront design), refuses unless `APP_ENV=development`, and never changes an existing zone, fee or threshold.
- Tests: `tests/integration/test_delivery_api.py`, `test_delivery_migration.py`, `test_seed_dev.py`, `tests/unit/test_delivery_units.py`, `tests/postgres/test_pg_delivery.py`; the role and grant pins were extended and the cart zone test updated.

### 13 — promotions (RE-026 B3, B6)
- Endpoints: `POST /cart/apply-code`, `DELETE /cart/code`. Staff: `GET /staff/promotions`, `GET /staff/promotions/{id}` (`promotions:read`), `POST /staff/promotions`, `PATCH /staff/promotions/{id}` (`promotions:manage`).
- Tables (approval requested, RE-026 B5):
  - `discounts`: `id`, `code` (required; unique case-insensitively, stored upper-case), `name`, `kind` (`percent`|`fixed`), `percent_off` (integer 1–100, set only for `percent`), `amount_off` (BIGINT RWF, set only for `fixed`), `applies_to` (`all`|`targets`), `status` (`draft`|`active`|`disabled`), `starts_at`, `ends_at` (entered in Africa/Kigali time, stored in UTC), `min_subtotal`, `max_discount` (BIGINT, optional), `usage_limit_total`, `usage_limit_per_customer` (integer, optional), timestamps. The `value` and `rules` columns are dropped.
  - `discount_targets`: `id`, `discount_id`, exactly one of `category_id`, `brand_id`, `product_id`. The unused `variant_id` column is dropped.
  - `discount_redemptions`: `id`, `discount_id`, `order_id`, `user_id` (optional), `customer_phone` (canonical), `amount` (BIGINT), `status` (`active`|`released`), `released_at`, `release_reason` (`cancelled`|`expired`), timestamps; unique (`discount_id`, `order_id`).
  - `carts` gains `discount_id` (optional).
- Rules:
  - One code per order.
  - A code applies to eligible merchandise only, never delivery.
  - A category target includes its subcategories.
  - Percentage rounding follows ADR-007 (the payable amount is rounded, halves down).
  - `max_discount` caps the discount, and a total can never go negative.
  - The discount is split across eligible lines in proportion to their amounts, with the remainder on the largest line.
  - Usage counts active redemptions only. The total limit is checked under a row lock on the discount at checkout. The per-customer limit counts by `user_id` or phone for registered customers and by phone for guests (§7 Q26).
  - Cancellation before dispatch and reservation expiry both release the redemption.
- New dependency: `tzdata`, because Python on Windows has no timezone database for `Africa/Kigali`.
- Tests: worked examples for every rule above, including window boundaries in Kigali time, concurrent last-use, allocation sums and the rounding example (10% off 1 005 → pays 904); management can view only.

Results (2026-10-25, on `feat/module-12-delivery`, not committed):
- Built as specified. Migration `d2f7a9c4e8b1` (after `b6f1d3a9c8e4`) changes the existing tables in place. It carries legacy discounts over only when the mapping is unambiguous and otherwise refuses, changing nothing: a NULL or unusable code, a case-insensitive duplicate, a fractional or out-of-range value, status `expired`, non-empty `rules`, a variant target, or any existing redemption.
- Permissions: `promotions:read` for administrator and management; `promotions:manage` for administrator only (B6, §3). Runtime grants: `discounts` SELECT, INSERT, UPDATE; `discount_targets` SELECT, INSERT, DELETE (targets are replaced as a set); `discount_redemptions` SELECT, INSERT, UPDATE (ADR-006).
- Cart: every response re-checks the cart's code and re-prices the discount (`discount`, `discount_total`, `subtotal_after_discount`, and `discount_amount` per line; additive fields). The delivery quote and the free-delivery threshold now use the subtotal after discount (B1); the fee itself is never discounted.
- Redemptions: `promotion_service.redeem()` locks the code row and re-checks the limits; cancellation before dispatch (`OrderService.change_status`) and reservation expiry (`expire_due_reservations`) release them in the same transaction. No route creates a redemption yet: checkout (module 14) must call `redeem()`.
- `tzdata` is a direct dependency; `app/core/kigali_time.py` converts Kigali local time to UTC and refuses ambiguous or missing local times.
- Decisions D-P1 to D-P12 are in `docs/qa/module-13-promotions-acceptance.md`. On 2026-10-25 the project owner decided D-P2 (the minimum compares the whole merchandise subtotal before discount, without delivery; a formal RE-026 B3 amendment is still to be recorded) and approved D-P10 as ADR-008 S5 (20 refused codes per 15 minutes per network and per cart owner, 429 with `Retry-After`, fail open); both are implemented.

### 14 — orders & checkout (RE-026)
- Endpoints: `POST /checkout` (`Idempotency-Key` required); `GET /customers/me/orders` (paginated history); `GET /customers/me/orders/{id}` (extended with lines and totals); `POST /orders/lookup {order_number, phone}` (guests, rate-limited per IP); `GET /staff/orders?status=&from=&to=&payment_status=` and `GET /staff/orders/{id}` (`orders:read`). Existing `PATCH /staff/orders/{id}/status` and `/assignment` are kept (`orders:fulfil`); the status body gains an optional `reason`. There is no separate cancel endpoint: cancellation is the `cancelled` transition.
- Checkout, in one transaction:
  - Reprice every line from the database (pricing service).
  - Re-validate the code and lock its row.
  - Compute the delivery fee from the address district and the threshold.
  - Compute the total: subtotal − discount + delivery.
  - Snapshot VAT (`tax_treatment = vat_inclusive`, rate 18%, the extracted amount in `orders.tax_total`).
  - Create the order, its items and status history, the discount redemption and the reservations (`create_order_with_reservations`).
  - Return the order number, totals and the payment methods available for the zone.
- Rules:
  - Customers use a saved address or an inline address; guests use an inline address.
  - The payment method is chosen at checkout (§7 Q15).
  - Order numbers are non-sequential (§7 Q16).
  - The idempotency key replays the original order.
  - Hold TTL, expiry and COD handling follow §7 Q11–Q14.
- Tests: TC-06 and TC-07 flows, tampered amounts, concurrent last unit (TC-13), cancellation releasing stock and code (TC-14), idempotent retry, guest lookup returns the same 404 for a wrong phone, history ownership.

Results (2026-10-25, on `feat/module-12-delivery`, not committed):
- Built as specified, with one small migration `f3a8c6e1b5d9` (after `d2f7a9c4e8b1`): `orders.checkout_request_hash`, so a retry with the same `Idempotency-Key` replays only the same request (409 otherwise). Keys are scoped to their owner. No other schema change: the chosen payment method is the order's first `payment_attempts` row (cash on delivery `pending`, mobile money `created`).
- Checkout is one transaction (cart lock, then stock, then the promotion row) reusing the cart pricing, `promotion_service.quote()`/`redeem()`, `delivery_service.quote_for_district()` and `create_order_with_reservations`. VAT is extracted from the total at 18% (`app/core/money.py`, ADR-007); lines keep `tax_amount` 0 (Q18).
- §7 Q11–Q14: holds of 15 minutes (mobile money) and 24 hours (cash on delivery); an expired hold cancels the order (`payment_timeout`) and expires its payment attempt; confirming a cash-on-delivery order commits its stock; delivering it marks the payment succeeded. Cancellation also cancels an unpaid attempt.
- Permissions: `orders:read` for administrator, sales and operations (§3). Runtime grants: `orders` INSERT, `order_items` SELECT/INSERT, `stock_reservations` INSERT, `payment_attempts` SELECT/INSERT/UPDATE (ADR-006).
- Decisions D-O1 to D-O13 are in `docs/qa/module-14-checkout-acceptance.md`. On 2026-10-25 the owner decided D-O2 (keep mobile money alongside cash on delivery; never shown as paid before module 15) and approved D-O3 as ADR-008 S6 (5 failed lookups per order number, 20 per IP, per 15 minutes; 429 with `Retry-After`; fail closed); both are implemented.

### 15 — payments
- Endpoints: `POST /payments/{order_number}/initiate` and `GET /payments/{order_number}/status` (the customer who owns the order, or a guest with the order number and phone); `POST /webhooks/{provider}`; `GET /staff/payments` (`payments:read`); payment changes such as COD confirmation (`payments:manage`).
- Model: `payment_attempts` and `payment_events` exist. `payment_events` gains `payload_metadata` (JSONB, sanitised; no full phone numbers, no card data).
- Provider interface in `app/integrations/payments/`: `initiate(order)`, `verify_webhook(request)`, `parse_event(request)`, `check_status(ref)`, with a `mock` provider (HMAC-signed webhooks, secret from env) and a `cod` provider.
- Webhook flow (TC-11): verify → store the event → skip if `(provider, event_key)` was seen → update the payment and commit the reservation in one transaction → 200 quickly. A late success after expiry becomes `needs_reconciliation` (ADR-002).
- Rules: COD creates a `pending` attempt at checkout and is never marked paid at order time (TC-12); success never regresses on a later failure; amounts must match the order total.
- Real providers: see §7 Q21.
- Tests: success, failure, cancel, delay, duplicate and forged callbacks, late success, amount mismatch, COD state, management read-only.

Results (2026-10-25, working tree on `feat/module-12-delivery`, not committed):
- Built as specified. Migration `a7c2e9d4f6b8` (after `f3a8c6e1b5d9`) adds `payment_events.payload_metadata`. Providers in `app/integrations/payments/`: `mock` for `mtn_momo` and `airtel_money` (HMAC-SHA256 webhooks, `PAYMENT_MOCK_WEBHOOK_SECRET`, refused in production) and `cod`; card has none (§7 Q21).
- Webhooks: verified before storing; `(provider, event_key)` deduplicated; the event, the attempt and the stock commit change in one transaction under the order's common lock order. A late success commits nothing and needs reconciliation; a failure never regresses a success; mismatched amounts or currencies and unknown references need reconciliation.
- Guests pay and read status with order number + phone on the ADR-008 S6 counters. `payments:read` (administrator, management) lists attempts and events; `payments:manage` (administrator) records COD cash for delivered orders. Runtime grant: `payment_events` SELECT, INSERT, UPDATE.
- Decisions D-Y1 to D-Y8 are in `docs/qa/module-15-payments-acceptance.md`; D-Y2 (a failure keeps the hold for a retry) needs owner confirmation. Real MTN MoMo / Airtel Money adapters wait for ADR-003 and sandbox credentials.

### 16 — invoices
- Endpoints: `GET /customers/me/orders/{id}/invoice` (owner); `GET /staff/orders/{id}/invoice` (`orders:read`); `GET /staff/orders/{id}/delivery-note` (`orders:fulfil`).
- Tables: `invoices` (`id`, `order_id` unique, `invoice_number` unique, `issued_at`, `total`, `vat_amount`, `snapshot` JSONB) and `invoice_counters` (`year`, `last_number`; locked row, so numbers are gapless and never reused).
- Rules: VAT is extracted at 18% from the inclusive total (ADR-007), with no EBM claim; the issue point and format are in §7 Q19. Seller details (legal name, TIN, address) become settings keys in this module.
- New dependency: `reportlab` (pure-Python PDF generation, no system libraries, works on Windows and Linux).
- Tests: numbering under concurrency, VAT extraction and rounding, ownership, PDF contains the required fields.

Results (2026-10-26, `feat/module-16-invoices`, pending PR into `dev`):
- Built as specified. Migration `c5e8a2d7f4b1` (after `a7c2e9d4f6b8`) adds `invoices` and `invoice_counters`. Runtime grants: `invoices` SELECT, INSERT; `invoice_counters` SELECT, INSERT, UPDATE. Settings keys `seller.legal_name`, `seller.tin`, `seller.address`.
- Issued in the transaction that records the payment success (webhook, staff COD confirmation) or delivers a cash-on-delivery order, after the order's locks; nothing for pending, failed, cancelled, late or mismatched payments. Numbers `INV-YYYY-NNNNNN` (Kigali year) come from one counter upsert in that transaction, so committed numbers per year are exactly 1..N; a rollback returns its number. VAT is order-level, `vat_component(total)`, and must equal the stored `tax_total`.
- With a seller detail missing or invalid (or amounts that do not reconcile) nothing is issued and no number is used; the payment still stands; the refusal is logged and audited. An administrator then issues it with `POST /staff/orders/{id}/invoice` (`invoices:recover`, administrator only; same checks, locks and counter; idempotent; the order and payments unchanged).
- Project owner decisions (not formal approvals by the responsible owners): the delivery-note eligibility rules are the owner's proposed default until the Product/Operations owner approves them; recovery uses a dedicated `invoices:recover` permission held by administrator only (any other role needs a recorded approval); the recovery date and year for recovered invoices stay provisional until Finance confirms. TC-18 stays blocked until Finance approves the actual invoice PDF, template and tax display (PR-14). Details: P-1 to P-4 in `docs/qa/module-16-invoices-acceptance.md`.
- Orders paid before Module 16 is deployed (mobile-money successes and delivered cash-on-delivery orders) have no invoice: issuance happens only with a payment success or delivery recorded after deployment. Whether to issue invoices for them retroactively, and with which issue date and year, is a Finance decision that has not been made; no policy is assumed. The recovery endpoint could issue them technically, but it must not be used for that until Finance decides.
- PDFs (ReportLab 4.5, in memory) render from the stored snapshot; delivery notes show no prices or payment details. Evidence and open decisions: `docs/qa/module-16-invoices-acceptance.md`.

### 17 — notifications
- Internal `notify(event, order)` run as a background task after commit for `confirmed`, `dispatched`, `delivered` and `cancelled`. Endpoints: `GET /staff/notifications`, `POST /staff/notifications/{id}/retry` (`notifications:manage`).
- Table `notification_logs`: `id`, `order_id`, `event`, `channel` (`sms`|`email`), `recipient`, `status` (`pending`|`sent`|`failed`), `attempts`, `last_error` (sanitised), `provider_message_id`, `next_attempt_at`, `sent_at`, timestamps.
- Rules: never blocks or fails checkout or status changes; up to 3 attempts with backoff via a cron script (`scripts/retry_notifications.py`); messages contain no secrets.
- Providers: mock only until ADR-005 (§7 Q22). This module also connects password reset (module 2) to a real channel.
- Tests: send after commit only, failure logged and retried, retry endpoint, no duplicate sends.

Results (2026-10-26, branch `feat/module-17-notifications` rebased onto `origin/dev` at `4475eb9`; on `origin` up to `6a2d1f3`, the payment-race test fix committed locally on top, not pushed):
- Built as specified. Migration `e4b9c1f7a3d6` (after `a1d9c3e5f7b2`, the merge head of `dev`) adds `notification_logs` with the listed columns plus `claimed_until` (the sending worker's lease, needed so two workers or a staff retry never send one message at once); unique (`order_id`, `event`, `channel`); CHECKs on event, channel, status, attempts (0–3), recipient format per channel and the sent/pending invariants. Runtime grants: SELECT, INSERT, UPDATE (no DELETE). `notifications:manage` for administrator only (§3).
- After commit only: the row is inserted in the order's own transaction under a savepoint (transactional outbox), so a rolled-back change leaves nothing and a failed insert never fails the change; the provider is called only after the commit, by a background task after the response or by `scripts/retry_notifications.py` (cron). Events: staff status changes to confirmed, dispatched, delivered, cancelled; the expiry job's and a late payment's `payment_timeout` cancellation. Checkout (`received`) and `processing` send nothing.
- Retries: at most 3 attempts, the 2nd 5 minutes and the 3rd 30 minutes after a failure; a provider error marked permanent ends them. Delivery claims one row at a time (`FOR UPDATE SKIP LOCKED`), immediately before its provider call, with a 2-minute lease that the sending worker renews every 30 seconds while the call runs; a result is stored only if the row still carries that claim (fencing on `attempts`). `attempts` counts provider calls initiated, so rows not yet sent keep their attempts when a batch stops on a database error. An attempt whose lease ended with no recorded result is labelled `outcome_unknown`; a row whose worker stopped after its third attempt is closed as `failed` with `outcome_unknown`. Timeouts are unknown outcomes, never treated as "not delivered". Each message carries a stable idempotency key (`notification:<id>`); only a provider with idempotent delivery can drop a duplicate after an unknown outcome, which a database transaction alone cannot prevent.
- Review fix (2026-10-26): batches previously claimed every row up front with one shared lease, so a slow provider could let later rows' leases expire (a second worker could then send them concurrently) and a database error mid-batch spent attempts on rows never sent. Both are fixed and covered by regression tests on real PostgreSQL connections (see the acceptance record).
- `last_error` holds a sanitised code only (provider text never stored or logged); no message text is stored; the staff list masks recipients.
- Password reset (module 2) now sends through the same provider abstraction, once, after commit, with failures isolated and logged by type only; codes never reach `notification_logs`. Only a provider that reaches the person may send codes, so with the mock both reset endpoints still answer 503.
- Providers (§7 Q22): `NOTIFICATION_PROVIDER=mock` (delivers nothing; refused in production) and `console` (development). ADR-005 is not in the repository and the provider decision (PRD: Operations + technical lead) is open, so no real SMS or email provider is integrated and real delivery stays blocked, for order notifications and for password reset alike.
- Evidence and open decisions: `docs/qa/module-17-notifications-acceptance.md`.

### 18 — reports
- Endpoints: `GET /staff/reports/sales?from=&to=&group_by=day|week`, `/staff/reports/top-products`, `/staff/reports/stock`, `/staff/reports/{type}/export` (XLSX) (`reports:read`).
- Rules: count only paid orders and delivered COD orders (UAT scenario 7); days and weeks in Africa/Kigali time, weeks starting Monday (§7 Q25); amounts in whole RWF.
- Tests: totals reconcile with fixture orders, excluded states, week boundaries, export matches the JSON.

Results (2026-10-28, on `dev`, based on `96c6324`):
- Built as specified, read-only: no table, migration, dependency, cache or worker (`openpyxl` and `tzdata` were already dependencies). `app/api/v1/endpoints/reports.py`, `app/services/report_service.py` (queries), `app/services/report_xlsx.py` (workbooks), `app/schemas/reports.py`. All four routes require `reports:read` (administrator, management, finance, §3).
- Paid orders and delivered cash-on-delivery orders are the orders with a `succeeded` payment attempt (mobile money through its verified webhook; cash on delivery on delivery, §7 Q14); exactly the invoiced orders (§7 Q19). Each counts once: one row per order, dated by its first success, so a duplicate succeeded attempt is not a second sale. Kigali days and Monday weeks (§7 Q25) are computed in PostgreSQL; amounts are BIGINT sums.
- Top products per product (a deleted product's lines keep the name they were sold with); stock is the `GET /inventory` query (`inventory_admin.stock_list_query`, formerly the private `_stock_rows`, made public so the stock list, the single-SKU read and the stock report visibly share it), paginated with totals over every SKU.
- Each XLSX export is built from the same service call as its JSON; text cells are never formulas.
- Not approved (engineering defaults, `docs/qa/module-18-reports-acceptance.md`): R-1 sale date = first payment success (not the order date); R-2 top products by units, then revenue, then name, 10 by default (1–100); R-3 inclusive Kigali dates, at most 366 days; R-4 zero-filled periods, weeks cut at the range. Refunds and returns are not subtracted (no module records them). R-6: no source requires auditing reads or exports (the technical plan audits "important changes"; ADR-006 audits changes and security events), so none is written; whether to audit them anyway is the security owner's choice. R-7: the PRD lets management "export approved data" and no document lists it, so the exported columns need the product owner's sign-off (with Finance for sales figures).

### 19 — settings & content

Planned: public `GET /settings`, `GET /pages/{slug}?lang=`, `PATCH /staff/settings`, `PUT /staff/pages/{slug}`, table `pages`. **As built (2026-10-29, branch `feat/frontend-phase-1`)**, with the owner's decisions of 2026-10-29: business quotes are stored and listed in the admin, the announcement bar is included, the development seed has draft policy text, and Markdown is rendered with react-markdown and remark-gfm.

- **Settings keys** (`PATCH /staff/settings`, `settings:manage`): `store.name` (2–80), `contact.phone` and `contact.whatsapp` (international form, e.g. `+250 788 123 456`: 8–15 digits after the plus), `contact.email` (stored in lower case), `contact.address` (3–200, one line), `contact.hours` (3–100, one text shown in both languages), `announcement.enabled` (strict boolean), `announcement.text_en` and `announcement.text_rw` (3–120). A set value can be changed but not cleared (null is refused). The announcement can be switched on only when both texts are set (422 on `announcement.enabled`). One email only, as in Settings.dc.html.
- **`GET /settings`** (public, cached 60 s): `store_name`, `phone`, `whatsapp`, `email`, `address`, `hours` and `announcement {en, rw}` (null unless switched on with both texts). Seller details and the delivery threshold are never public.
- **Pages**: table `pages` as planned, unique (`slug`, `locale`), with checks on locale, slug shape, title and body length (50 000). Six fixed slugs: `about-us`, `delivery-information`, `returns-and-refunds`, `warranty`, `privacy-policy`, `terms-and-conditions` (an unknown slug is 422 for staff, 404 in public). `GET /pages/{slug}?lang=en|rw` returns the published version in that language only; a missing or unpublished translation is 404, never another language. `GET /staff/pages` lists every page with both versions; `PUT /staff/pages/{slug}?lang=` writes one version whole (title, Markdown body, `is_published`) under an advisory lock, audited as `content.page_update` with before and after snapshots (title, published, body length). An unchanged write is not audited. Both need `content:manage`.
- **Quote requests** (Contact.dc.html "Request a business quote"): table `quote_requests` holds `reference` (`Q-YYMMDD-XXXXXX`), company, contact name, Rwandan phone, optional email, 1–20 product and quantity lines (JSONB), delivery location, needed-by date (today to one year ahead, Kigali time), message, the page language, status (`new`, `contacted` or `closed`), and who handled it and when.
  - `POST /quote-requests` is public, limited in Redis per phone number (3 an hour) and per network (10 an hour). Every attempt counts. With Redis down it refuses (503) rather than letting the table be flooded.
  - `GET /staff/quote-requests?status=` and `PATCH /staff/quote-requests/{id}` (status, audited as `quote.status_change`) need the new `quotes:manage` (administrator, sales).
  - Staff are not notified of new requests yet: notifications are module 17. The admin sidebar shows the count of new requests.
- **Migration** `b2f6d8e4a1c9_policy_pages_and_quote_requests`, after both `a8d2f6c1e3b7` (frontend phase 1) and `edebaf558c2d` (the `pages` table of the module 19 first merged into `dev`, which stays in the history as databases on `dev` may have run it). It gives `pages` the shape below (slug at most 60, title at most 120, the model's constraint names; a row that does not fit stops the upgrade instead of being cut, and no row is changed) and adds `quote_requests`; the downgrade restores the `edebaf558c2d` shape. Runtime grants (SELECT, INSERT, UPDATE) for both tables in `scripts/provision_runtime_role.py`.
- **Seed**: the development catalogue seed adds the six pages in English and Kinyarwanda as marked drafts (each starts with a "draft, to be replaced" note) and sample store contact values. It writes only missing pages and settings, and its cleanup removes only those still equal to the seed text, so staff edits survive. Production starts empty: the store leaves out unset contact lines, and the policy pages show not found until staff write them.
- **Frontend**: see ADR-011, "Module 19".
- **Replaces PR #32** (owner decision 2026-10-29): `dev` had a first module 19 from `feat/module-19-settings-content` (four contact keys with `+2507XXXXXXXX` phones, free page slugs with titles up to 200, `PUT` answering 201 on create, no staff page list, no quote requests). When `dev` was merged into `feat/frontend-phase-1`, this implementation was kept: its API is what the storefront and admin use. Its `services/page_service.py` was removed; its migration, migration test and real-HTTP test were kept and adapted (`tests/integration/test_pages_migration.py`, `tests/postgres/test_pg_settings_content.py`). Its acceptance record (`docs/qa/module-19-settings-content-acceptance.md`) is kept for history, marked as replaced. Its open point stands: the policy texts must be business-approved (TC-20); the development seed's pages are marked drafts and production starts with none.
- **Tests**: `tests/integration/test_settings_content_api.py`; the settings key list in `tests/integration/test_delivery_api.py`; permission sets in `tests/integration/test_staff_authorization_api.py`; the seed in `tests/integration/test_seed_development_catalogue.py`.

### 20 — reviews (SC-01, approved by the project owner on 2026-10-27)
Built in two parts. **Part 1**, before frontend phase 2 continues: the tables, the product rating fields, the `min_rating` filter and the `top_rated` sort; ratings stay empty until part 2. **Part 2**, before frontend phase 3's product page: review links, submission, moderation, the public list and seed reviews. Screens: product page (frontend phase 3), WriteReview (phase 5), admin Reviews (phase 6).

- **Who reviews:** verified buyers only, one review per delivered order item. Signed-in customers get a "Write a review" button on OrderDetail and MyOrders for delivered items; guests get the same buttons on `/track` after the order lookup. Each button opens `/review/[token]`. Sending the link by SMS or email waits for module 17.
- **Review links:** table `review_tokens`: `id`, `order_item_id` (unique; one per order item), `token_hash` (SHA-256 of a random token, unique; the token itself is never stored), `expires_at` (delivery time + 90 days), `used_at` (set when the review is sent: single use), timestamps. A link is issued on demand for a delivered item of the caller's own order (customer session, or the guest's order lookup); issuing again replaces the hash while the link is unused and unexpired. The design's expired and already-reviewed states map to `expires_at <= now()` and `used_at IS NOT NULL`.
- **Reviews:** table `product_reviews`: `id`, `product_id`, `order_item_id` (unique: one review per item), `user_id` (null for a guest order), `rating` (1–5), `title` (optional, at most 80), `body` (optional, at most 2,000), `author_name` (first name and last initial, taken from the order when the review is sent, at most 80), `status` (`pending` | `approved` | `rejected`), `moderation_reason` (optional, at most 500), `moderated_by_user_id`, `moderated_at`, timestamps. Plain text only: stored and returned as text, never rendered as HTML. No photos, no editing after sending.
- **Moderation:** new reviews are `pending`; only `approved` reviews are public. `POST /staff/reviews/{id}/approve` and `/reject` (optional reason) with `reviews:moderate` (administrator, sales; finance and the others get 403). Audit `catalog.review_approve` / `catalog.review_reject`.
- **Product rating fields:** on `products`: `rating_count`, `rating_average` (NUMERIC(2,1); null when the count is 0) and the distribution `rating_1_count` … `rating_5_count`; database checks keep the count equal to the sum of the distribution and the average between 1 and 5. Recalculated from the approved reviews in the same transaction as approve or reject. Public product summaries carry `rating {average, count}`; the product detail adds `distribution {5, 4, 3, 2, 1}`.
- **Catalogue:** `min_rating=1..5` keeps products whose average is at least that value (products without reviews are left out); `sort_by=top_rated` orders by average (highest first), then review count, then ID, with unreviewed products last.
- **Public list:** `GET /catalog/products/{slug}/reviews`, approved only, newest first, paginated: rating, title, body, author name, "verified purchase", date.
- **Abuse:** review submissions are rate limited per token and per IP: every attempt counts, at most 5 per link and 20 per network an hour (`REVIEW_SUBMIT_*` settings); an unreachable limit store refuses (503). A guest's link request uses the order lookup's counters.
- **Links (as built):** `POST /customers/me/orders/{order_id}/items/{order_item_id}/review-link` and `POST /orders/review-link` (guest: order number, phone, item) return the token once; only its SHA-256 hash is stored. Asking again replaces an unused link, so an earlier link stops working. `GET /reviews/{token}` tells the page whether the link is open, expired or used.
- **Seed:** approved reviews for the items of the 8 delivered seed orders, plus 1–2 pending and 1 rejected; the seed cleanup removes them.
- **Tests:** link single use, expiry and ownership; delivered items only; totals after approve and reject; filter and sort; permissions (finance 403); text stays plain (no HTML).

### 21 — wishlist (SC-01, approved by the project owner on 2026-10-27)
- **Who:** signed-in customers only; staff accounts get 403 `customer_only` (as carts). A guest who taps the heart goes to sign-in and the frontend saves the product after sign-in (return URL plus the pending product ID).
- **Table** `wishlist_items`: `id`, `user_id`, `product_id`, timestamps; unique (`user_id`, `product_id`); index (`user_id`, `created_at`). Rows are deleted when the customer removes a product (runtime role: SELECT, INSERT, DELETE). Not audited (no business or security effect).
- **Endpoints** (customer session): `GET /customers/me/wishlist` (newest first, standard page envelope: product ID, date added, `available`, and the public product summary while it is sold, otherwise its name, slug and first image so the page can show "No longer available" with a remove button); `GET /customers/me/wishlist/ids` (all saved product IDs and the count, for the hearts and the header badge); `PUT /customers/me/wishlist/{product_id}` (idempotent add; only a product currently sold can be added, else 404); `DELETE /customers/me/wishlist/{product_id}` (idempotent remove). Both changes return the product ID, whether it is saved and the new count.
- **Limit:** at most 200 products (409 `wishlist_full`); the count check holds the customer's row lock, so parallel adds cannot pass it.
- **Catalogue stays cacheable:** public product responses carry no per-customer fields; the storefront reads `/wishlist/ids` for the signed-in customer and marks hearts in the browser.
- **Frontend:** header Wishlist link with the count, `/account/wishlist` (no design: Account layout and ListingCard grid), a Wishlist item in the account menu.
- **Tests:** idempotent add and remove, the 200 limit (also under concurrency), authentication and staff refusal, products no longer sold, add after sign-in.

## 6. Prerequisites RE-006, RE-007, RE-016 (RE-026 B10)

Not recorded as approved. I could not summarise what they require: none of the three is described in the repository, the commit history or the three requirement documents, and the Trello board returned HTTP 401. The only mention is PR #4 (catalogue, RE-018): "Prerequisites RE-002 and RE-016 remain unverified." To decide, please paste the card text or confirm that this plan proceeds without them.

## 7. Open questions (proposed default in bold; approving the plan accepts it)

1. Password reset before a provider exists (module 2 comes before 17): **build it behind the notification provider interface; outside development the endpoints return 503 `password_reset_unavailable` until a provider is configured.**
2. Reset rules: **6-digit code, 15 minutes, 5 attempts, newest code only, all sessions revoked on reset.**
3. Import: **create or update by SKU; an optional `opening_stock` column is applied as a `receipt` movement for new SKUs only.**
4. Cost price and internal notes (named in the first plan, not in PR-10): **not added.**
5. Search: **full-text with prefix matching replaces today's substring matching** (e.g. "phon" no longer matches "iPhone"; "iph" does).
6. Image storage: **local disk (`MEDIA_ROOT`) for the MVP; object storage decided with hosting (ADR-004).**
7. Images: **JPEG/PNG/WebP, 5 MB, 1600 px plus a 400 px thumbnail.** Superseded on 2026-10-25 by ADR-009: no resized variants or format conversion; the exact original is kept privately and one public source (longest side at most 2400 px) is served; resizing happens at delivery.
8. Deletes: **categories and brands only when unused (else 409); variant DELETE deactivates.**
9. Low-stock alerts: **the filtered staff list only; no messages.**
10. Cart: **`X-Cart-Token` header, 99 units per line, 30-day guest expiry, merge capped by availability.**
11. Hold TTL for mobile money and card: **15 minutes from order creation, no renewal** (ADR-002 recommendation).
12. Expired unpaid order: **moves to `cancelled` (system actor, reason `payment_timeout`), releasing stock and code.**
13. COD stock hold: **committed when staff confirm the order; if not confirmed within 24 hours the hold expires and the order is cancelled.**
14. COD payment: **marked `succeeded` automatically when the order is moved to `delivered`.**
15. Payment method: **chosen at checkout.**
16. Order numbers: **`ORD-YYMMDD-XXXXXX` with a random suffix, not sequential.**
17. Guest access to payment initiation and status: **order number + phone (RE-026 B7), rate-limited per IP, same 404 for any mismatch.**
18. VAT detail (ADR-007 open point): **order-level VAT only; `order_items.tax_amount` stays 0.**
19. Invoices: **issued when payment succeeds (or a COD order is delivered); numbered `INV-YYYY-NNNNNN`, gapless per year.**
20. PR-12 "product discounts" without a code, and `compare_at_price`: **out of the MVP; `compare_at_price` is display-only.**
21. Real payment providers (MTN MoMo, Airtel Money, card): **mock and COD only until ADR-003 is decided and sandbox credentials exist; card stays disabled until then (TC-10 "if enabled").**
22. Notifications: **mock provider until ADR-005; SMS when the order has a phone, otherwise email.** Amended 2026-10-31 (approved by the project owner): an `smtp` provider may be used for development and staging tests until ADR-005 is decided (refused in production); with it, order messages go to the order's email address, and orders without one get no message. Amended 2026-11-01 (approved by the project owner): the Render test deployment, which runs with `APP_ENV=production`, may temporarily send through Gmail with `TEMPORARY_GMAIL_SMTP_ENABLED=true`; Resend is the planned replacement, and ADR-005 stays open.
23. mypy: **added as a dev dependency now; added to CI only once it passes.**
24. `uv` is not on PATH on this machine, and `uv.lock` must be updated whenever a dependency is added: **I install `uv` into the project `.venv` (`python -m pip install uv`).**
25. Report weeks: **Africa/Kigali time, Monday start.**
26. Per-customer code limit for registered customers: **counted by account or by phone, so the same person cannot reuse a code by checking out as a guest.**
27. "Deployed to staging" in the done checklist: **not possible from here; recorded as pending on each module.**

## Frontend phase 1 backend (2026-10-25)

Approved by the project owner on 2026-10-25 with the frontend phase 1 plan. Scope: local development only.

- **Finance role** (revision `a7c2e4f9b1d3`): see §3. The downgrade refuses while anyone holds the role.
- **B1** (revision `b8d3f5a1c2e7`): `categories.description` (1–500 characters), one category image and one brand logo, through `POST`/`DELETE /staff/categories/{id}/image` and `POST`/`DELETE /staff/brands/{id}/logo` (`catalog:manage`). Public categories carry `description` and `image`, brands `logo`.
- **B2**: `products.is_featured` (default false, partial index), editable by staff; `GET /catalog/products?featured=true|false`.
- **B3**: `sort_by=bestselling`: units in order lines of orders delivered in the last 90 days (rule changed on 2026-10-26, checkpoint 1b: delivery is the one status that is a reliable sale today, cash on delivery included; the date is the order's `delivered` status history entry, as orders have no `delivered_at`). Most first by default; `sort_direction` flips only the units; ties go featured first, then newest, then ID, so the section is never empty or random. Refunds and returns are subtracted when module 15 adds them.
- **Staff product list and detail** (2026-10-26): `GET /staff/products` and `GET /staff/products/{id}` with `catalog:read`, every status, filters `status`, `has_images`, `category_id`, `brand_id`, `featured`, `q`.
- **`PublicImage`** (2026-10-26): one shared schema (`app/schemas/images.py`) for product images, category images, brand logos and banners, so the generated TypeScript has one image type.
- **B4**: `is_featured` and `created_at` on catalogue product responses.
- **B6**: `http://127.0.0.1:3000` added to the default `CORS_ORIGINS` and `.env.example`.
- **Images (ADR-009)**: storage interface with one `local` backend; `media/private` (exact originals, never served) and `media/public` (served at `IMAGE_PUBLIC_BASE_URL`); public source in its original format, upright, without metadata, transparency kept, longest side at most 2400 px, JPEG/WebP at quality 92; keys `<owner>/<id>/<uuid>-<hash>.<ext>`; Pillow in the threadpool with `IMAGE_PROCESSING_CONCURRENCY`. The public image object is `{url, width, height, alt, position}` (breaking: `id`, `image_ref`, `thumbnail_url`, `alt_text` and `sort_order` are no longer in the public catalogue; the staff image response keeps them, with `thumbnail_url` equal to `url`). Module 7 rows and files keep working.
- Not changed: catalogue import has no image column, so there is no image processing to move into its job.
- Runtime role: no new grants (new columns only; `categories`, `brands`, `products` and `product_images` already have UPDATE).
- Tests: `tests/unit/test_image_processing.py`, `tests/unit/test_media_storage.py`, `tests/unit/test_roles.py`, `tests/integration/test_image_admin_api.py`, `tests/integration/test_catalog_merchandising_api.py`, `tests/integration/test_frontend_phase_1_migrations.py` (upgrade → downgrade → upgrade, constraints, `alembic check`), `tests/postgres/test_pg_images.py`, `tests/postgres/test_pg_staff.py`, plus finance cases in the staff, audit and order tests.

## Checkpoint 1b (2026-10-26)

Approved by the project owner on 2026-10-26 after the checkpoint 1b architecture review. Delivered as separate commits on `feat/frontend-phase-1-backend`.

- **Final staff matrix** (§3): `catalog:read`, `content:manage`, and the widened read access; code-defined, no migration.
- **Media registry** (revision `c4e8f2a6b9d1`, ADR-009 §6): `media_objects` tracks every stored file (pending → active → deleting); images, category images and brand logos link to it by foreign key; files are deleted only by the cleanup worker (`python -m app.worker`) after the change that retired them is committed, with retries, backoff and `GET /staff/media/cleanup-problems` for staff. The storage interface is `put`/`get`/`exists`/`delete`/`public_url`/`list`/`free_bytes`, shaped for two R2 buckets later (design only). The module 7 layout and its `/media` fallback are removed (no hosted environment held images); `scripts/reset_dev_images.py --confirm` clears a development database before the migration. `/health` reports `checks.storage`. Runtime role: `media_objects` SELECT, INSERT, UPDATE, DELETE.
- **Durable job queue** (revision `d5f9b3c7e1a2`, ADR-010): `jobs` and `job_items` in PostgreSQL, done by the worker process (`python -m app.worker`, `JOB_WORKER_CONCURRENCY` threads, default 2) with `SKIP LOCKED` claims, ordering per target, 3 attempts, a 10-minute stale requeue, `GET /staff/jobs/{id}` and `POST /staff/jobs/{id}/retry-failed` (`catalog:manage`). Runtime role: `jobs`, `job_items` SELECT, INSERT, UPDATE.
- **Catalogue import stays synchronous** (2026-10-26): it runs in one transaction, so a crash changes nothing; the worker marks an import left `processing` for 10 minutes as failed (audited). **Revisit** (move it onto the job queue) if an import exceeds about 2 000 rows or 30 seconds.
- **Bulk image upload** (2026-10-26): `POST /staff/products/bulk-images`, 20 files / 100 MB per request, files named `<slug>.<ext>` or `<slug>__<n>.<ext>` (matched on the product slug; products have no SKU of their own), processed by the worker per position in job order, with per-image and per-job audit records.
- **SKU rules and positions** (revision `e7b2d6f4a8c3`): SKUs unique ignoring case (index on `lower(sku)`; the import and `/inventory/{sku}` match ignoring case), `__` refused in SKUs, one product image per position (partial unique index). The migration refuses, with a list, while existing data breaks these rules.
- **Publication guard** (2026-10-26): `ensure_publishable` on product create and update, the import (rows asking for active without images become drafts with a warning in `import_jobs.warnings`), image delete, moving an image to a variant, bulk replace and `POST /staff/products/bulk-activate` (≤200 IDs). Existing active products without images are not deactivated.
- **Banners** (revision `f8c3e7a9b4d5`, topic 9): `banners` with `_en`/`_rw` text, an on-site CTA URL, one image, position, active flag and window; public `GET /banners` (cached 60 s) and staff routes under `/staff/banners` with `content:manage`; audited with before and after values. Runtime role: `banners` SELECT, INSERT, UPDATE, DELETE. No migration inserts sample content (a test scans every migration).
- **mypy required in CI** (2026-10-26): `uv run mypy` (from `backend/`, `app` and `tests`) runs in the backend CI job after Ruff. The last error, `app/repositories/catalog.py` brand product counts typed as `object`, is fixed with `type_coerce(..., Integer)`; mypy reports no issues.

## Checkpoint 2: development catalogue seed (2026-10-26)

Approved by the project owner on 2026-10-26 (frontend phase 1, step 1). Branch `feat/frontend-phase-1`.

- **Command** (from `backend/`): `uv run python ../scripts/seed_development_catalogue.py --confirm`, and `--cleanup --confirm`. It lives in the root `scripts/` folder like the other operator scripts (the approved wording `python -m scripts.seed_development_catalogue` needs a `backend/scripts` package that does not exist). Both refuse unless `APP_ENV=development` is set explicitly and the database host is local (`localhost`, `127.0.0.1`, `::1` or a docker-compose service). Nothing runs it on startup, deploy or migration.
- **Through the real services**, on the runtime role: the seed administrator (created directly, audited as `staff.seed_create`, like the bootstrap CLI) creates the other staff, the taxonomy, products, variants and opening stock (`receipt` adjustments); product photos go through the bulk image upload in batches of at most 20 files and the worker, then `bulk_activate`; banners through the banner service; each seed customer places cash-on-delivery orders through the cart and checkout, and the seed administrator moves them through the order statuses. Services rather than HTTP, so the per-network guest-cart and login rate limits do not apply.
- **Content** (`scripts/seed_catalogue_data.py`; development sample data, not approved business content): the five categories of the `Header.dc.html` nav with the `Main.dc.html` subtitles and generated images; 12 brands with generated logos; 42 products, 47 variants (`DEV-` SKUs) with specifications, RWF prices, 8 with `compare_at_price`, stock in stock / low (2 of threshold 3) / out of stock, 7 featured; 3 banners (the `Main.dc.html` hero, plus two built from its trust points; Kinyarwanda is draft test data); 5 staff (one per role) and 5 customers at `@seed.3sixty.local`; 15 orders (8 delivered, 2 dispatched, 1 processing, 1 confirmed, 2 received, 1 cancelled).
- **Idempotent**: seed keys are the `DEV-` SKU plus the slug (products), the slug (categories, brands), the English title (banners), the e-mail (people) and the checkout idempotency key `seed-order-NN` per customer (orders). No `is_seed` column and nothing in public JSONB. A rerun reports created/updated/skipped/failed, never resets stock or prices, and never touches other customers' orders. A slug held by a non-seed product is reported as failed and left alone.
- **Cleanup** (schema owner, one transaction): carts holding seed variants → reservations → status history, discount redemptions, invoices, payment events and attempts → order lines → seed orders → stock movements and balances → product images (files retired to the worker) → variants → products → banners → seed people (their jobs and import jobs first). It refuses, removing nothing, if a seed variant is in an order line or stock reservation of anyone else, or a promotion targets a seed product. **Two deviations from the approved order:** `stock_reservations` rows are never deleted by the application (trigger `stock_reservations_guard`), so the cleanup runs `SET LOCAL app.dev_seed_cleanup = 'on'` in its transaction and the guard lets a DELETE through only while that setting is on and the current user is a member of the table's owner role (migration `b4e7d1a9c3f2`, 2026-10-27; it replaced `ALTER TABLE ... DISABLE TRIGGER`, as the owner asked). The runtime role cannot use it: it has no DELETE privilege on the table and is not the owner (tested in `tests/integration/test_inventory_reservations.py` and `tests/postgres/test_pg_inventory.py`). The cleanup also deletes invoices (module 16 issues one when a cash-on-delivery order is delivered and seller details are set); approved 2026-10-27 for this cleanup only: no application service or API route may delete an invoice (`tests/unit/test_invoices_are_never_deleted.py`). Categories and brands are kept (not in the approved list).
- **Threshold**: `scripts/seed_dev.py` now seeds 50 000 RWF; the catalogue seed never touches it.
- **Production guard** (`app/services/dev_data_guard.py`): with `APP_ENV=production`, any `DEV-` SKU is logged as an error at startup and on each health check, and `GET /health` reports `checks.catalogue: "degraded"`.
- **Bug found and fixed** (separate commit): the customer-cart upsert (`ensure_customer_cart`) failed under a generic plan of its prepared statement, which made every customer add-to-cart answer 500 on a connection that had run it several times (`tests/integration/test_cart_repository_plans.py`).
- **Tests**: `tests/integration/test_seed_development_catalogue.py` (seed, rerun, storefront reads, cleanup and reseed; refusal on foreign orders; non-seed slug; guards; production health), `test_seed_dev.py` and `test_pg_delivery.py` (50 000).
- **Not covered by the taxonomy or the API** (reported for phase 2): the nav's "Brands" and "Deals" are not categories, and there is no API filter for discounted products ("Deals", "View Deals"); `Main.dc.html` shows a sixth tile "Gaming" and `MobileMenu.dc.html` a "Networking" item that the header nav does not have; the hero's overline ("Latest electronics, better everyday life") and trust points have no banner fields.

## Frontend phase 4 backend (2026-10-27)

Approved by the project owner on 2026-10-27 (frontend phase 4 decisions). Branch `feat/frontend-phase-1`.

- **Price-change notice** (decision 1; `Cart.dc.html` "Price updated: was …" and "Accept changes"): `cart_items.price_at_add` (migration `f1a7c3e9d2b4`, nullable, so older lines show no notice) holds the variant's price when the line was added, topped up or accepted; merge carries it. Cart lines return `previous_unit_price` when it differs from today's price, the cart `has_price_changes`, and `POST /cart/accept-prices` notes the current prices. Display only: totals and checkout always use the current price.
- **Cart line product ID**: cart lines also return `product_id`, so the cart's "Save for later" can move a line to the wishlist (which is keyed by product).
- **Line images**: cart lines and order lines return `image` (the variant's first image, else the product's; `app/services/line_images.py`), read live. `order_items.image_snapshot` stays unused.
- **Switching the payment method** (decisions 2 and 2a): `POST /payments/{order_number}/method`, for the owner or a guest with the order's phone. The current attempt is cancelled and a new one starts as at checkout. The stock hold moves to the order's creation + the new method's hold (§7 Q11, Q13), which needed the reservation trigger to allow an active hold's expiry to change, never beyond 24 hours after the hold was created (migration `a8d2f6c1e3b7`; ADR-002 and ADR-006 updated). Refused while a mobile-money request is open, once paid, when the stock is no longer held, or when the new method's time has passed.
- **Mock payments in development** (decision 3): `scripts/mock_payment.py ORDER --succeed|--fail [--reason …]` signs a mock event with `PAYMENT_MOCK_WEBHOOK_SECRET` and hands it to the webhook handler. It refuses unless `APP_ENV=development` is set explicitly.
- **Guest account on the confirmation page** (decision 4): a link to registration with the name and phone filled in; the guest order is not attached to the account (no backend change).
- **Tests**: `tests/integration/test_cart_prices.py`, `test_payment_method_change.py`, `test_mock_payment_script.py`; the trigger rule in `tests/postgres/test_pg_inventory.py`; the two operations in `tests/postgres/test_pg_http.py`.

## Frontend phase 5 backend (2026-10-28)

Approved by the project owner on 2026-10-28 (frontend phase 5 decisions). Branch `feat/frontend-phase-1`. No migrations.

- **Change password** (`Profile.dc.html`): `POST /auth/change-password` for active customers, with the current password; other sessions are revoked, this one stays. A wrong current password counts on the login counters. Staff passwords stay administrator-managed (ADR-006).
- **Log out everywhere** (`Profile.dc.html`): `POST /auth/logout-all` revokes every session of the user (ADR-006).
- **Order page by number** (`/account/orders/[number]`): `GET /customers/me/orders/number/{order_number}`, owner only.
- **Order lines for reviews** (`OrderDetail.dc.html` "Write a review" / "Reviewed"): order lines return the order item `id`, the product's public `product_slug` (null once it is no longer sold) and `reviewed`.
- **Not built** (decision 3): features with no backend data stay out of phase 5 and are listed in ADR-011's design differences (notification settings, language preference, deals by SMS, review photos and display name, rider and delivery code on Track, order search and status tabs).
- **Tests**: `tests/integration/test_account_security_api.py`; order lines in `tests/integration/test_reviews_api.py`.

## Frontend phase 6 backend (2026-10-28)

Requested by the project owner in the frontend plan (phase 6, "first add backend PUT /staff/products/{id}/images/order"). Branch `feat/frontend-phase-1`. No migrations.

- **Reorder images** (Product editor drag reorder): `PUT /staff/products/{product_id}/images/order` with `image_ids`, every product-level image of the product exactly once (at most 99, the bulk upload positions). They get sort_order 0..n-1 in one transaction under the product-change lock; two passes (first above every current position, then the final ones) keep the unique position index satisfied row by row. Variant images keep their order. The current order is not rewritten or audited. Bulk upload file names (`<slug>__<n>`) follow the new positions.
- **Tests**: `tests/integration/test_image_admin_api.py` (reorder section); the OpenAPI completeness list in `tests/postgres/test_pg_http.py`.
- **Admin list data** (owner decision 2026-10-28, all four proposed additions approved):
  - Orders list: `customer_name` and `customer_phone` (the recipient snapshot), `q` (a Rwandan mobile number matching the order's phone, else part of an order number) and `payment_method` (latest attempt).
  - `GET /staff/categories` and `GET /staff/brands` (`catalog:read`): every category and brand, hidden ones included, with `product_count` (any status).
  - Staff product list: `sku`, `price`, `available_quantity`, `has_low_stock` per row and a `low_stock` filter (active variants only; the stock figures of module 10).
  - `GET /staff/orders/assignees` (`orders:fulfil`): active staff (id, name, role) for the Assign control; the staff order detail adds `fulfilment_assignee_name`.
  - Tests: `tests/integration/test_admin_lists_api.py`.
- **Left out, listed as gaps in ADR-011** (decision 3 of phase 5 applied again): dashboard revenue, customers, charts, top categories and best sellers (module 18), CSV exports, product Kinyarwanda text and meta title, internal order notes, review replies and photos, price-cut promotions, delivery times and store pickup, staff invitations and last activity, store contact, announcement bar, review-request settings and policy pages (module 19), Analytics, Reports and Notifications screens (modules 17-18).

## 8. Risks and notes

- **Breaking API changes** in A2 and A3 (number amounts, error body, pagination envelope, `page_size` → `size`) and in modules 5–6 (category tree, `stock_status`). The frontend does not use these endpoints yet; this was checked on 2026-10-23.
- **New dependencies**, each added only in the step that needs it: `mypy` and `python-dotenv` (dev, A6), `python-multipart` and `Pillow` (7), `openpyxl` (8), `tzdata` (13), `reportlab` (16). An HTTP client for real providers (`httpx` as a runtime dependency) is added only when a real provider is approved.
- **Dev database**: run `alembic upgrade head` and `provision_runtime_role.py` after every pull that adds a migration (the local development database was at head `a1d9c3e5f7b2` on 2026-10-26).
- **Route ordering**: fixed in module 5 (`{staff_id:uuid}`), before any new `/staff/<name>` route exists.
