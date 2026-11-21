# Remediation Report: Authentication, Customer Accounts, Saved Addresses, Staff Authorization, Audit

> **Superseded schema note (2026-10-21, later the same day):** this work was rebased onto the commerce identity schema from PR #2. Migration `5c2f9a1d7e40` and the `users.role`/`phone_number` design described below no longer exist; see `docs/architecture/ADR-006-authentication-security-controls.md` ("Rebase�") and `docs/qa/auth-deployment-acceptance-report.md` for the current schema, deployment and test evidence. The defect analysis and controls below still apply.

| Field | Value |
| --- | --- |
| Date | 2026-10-21 |
| Scope | Backend only. No frontend pages, checkout, orders, payments or admin dashboard. |
| Source audit | `docs/qa/acceptance-audit-auth-accounts-2026-10-21.md` (verdict: APPROVAL BLOCKED) |
| Requirements | PR-06, PR-15, TC-07, TC-16. Trello card IDs are still unverified (board access failed during setup). |
| Branch state | `dev` @ `6489dac` + uncommitted working tree (nothing committed) |
| Decisions applied | Approved by the project owner in session on 2026-10-21 and recorded in `docs/architecture/ADR-006-authentication-security-controls.md` |
| **Recommendation** | **Security/integrity corrections: READY FOR REVIEW. Card: NOT DONE.** PR-06 order history and TC-07 are BLOCKED by unbuilt order/checkout features. TC-16 is DEFERRED to real staff functions. |

## 1. Phase 1: Audit review and correction plan

All findings were re-reproduced on the unchanged code before any fix: the original 33 live HTTP probes gave the same **14 FAIL**, and the audit-bypass probe again showed a change persisted with no audit row.

| Category | Items |
| --- | --- |
| Fixed under existing requirements (PR-15, Tech Plan §6, ADR-002 l.48 atomic audit, AGENTS.md) | D-02 audit bypass, D-04 registration 500s, D-05 phone login, D-08 audit immutability, D-10 timing, D-13 Ruff, D-14 OpenAPI accuracy, D-15 tests, D-16 checkpoint script, D-18 leftover dir (partly; see §3) |
| Needed a policy decision first, approved in session, then fixed | D-01 rate-limit thresholds and store (5/identifier, 20/IP, 15 min, Redis); D-03 default rule (exactly one); D-09 pseudonymisation (keyed HMAC) |
| Not changed: still awaiting approval | Password recovery; session lifetime/idle/logout-all; identifier verification and re-auth (C6); permission matrix and staff provisioning (D-07); frontend token storage; Swagger exposure in production; invalid-token audit throttling (D-11); CORS `allow_credentials` (D-17) |
| Dependencies outside this card | Order history (D-06, PR-06/TC-07); real staff business operations (TC-16); formal approval of ADR-002 schema scope (D-12) |

The existing architecture (opaque bearer tokens hashed in PostgreSQL, scrypt, FastAPI dependencies) was kept.

## 2. Findings → root cause → correction

| ID | Original finding | Root cause | Correction | Status |
| --- | --- | --- | --- | --- |
| D-02 (S1) | A 600-char User-Agent → change persisted, audit lost, HTTP 500 | Header values went unbounded into `VARCHAR(512)`; repositories committed the change before the audit insert | `core/request_context.py` validates IPs and strips/truncates User-Agent. `audit_service.py` bounds every field and `details` (keys, depth, string and list length). Repositories only `flush()`; services commit change + audit together via `db/transaction.atomic`, so any audit failure rolls the change back | **FIXED** |
| D-03 (S2) | 10 concurrent "create as default" → 3 defaults; zero defaults possible | No DB constraint; count-then-insert and unset-then-set were unsynchronised; PUT allowed clearing the default | Partial unique index `uq_addresses_one_default_per_user`. Every address write locks the customer row (`SELECT … FOR UPDATE`) in one transaction. Approved rule enforced: first = default, clearing the current default → 422, delete promotes the newest remaining. Migration fixes existing rows deterministically | **FIXED** |
| D-01 (S1) | No login rate limiting | Not implemented | `core/rate_limit.py`: Redis-backed `LoginRateLimiter`, 5 failures/identifier and 20/IP per 15-min fixed window → 429 + `Retry-After`; success clears the identifier counter; keys are HMAC pseudonyms; unknown accounts are treated identically; fails closed (503) if Redis is down | **FIXED** |
| D-04 (S2) | Concurrent duplicate registration → 9×500; email >255 → 500 | Check-then-insert race unhandled; no length limit on email | Email ≤254, password ≤256, identifier/phone/street bounds. `IntegrityError` → 409 with the same message as the fast-path check (no DB internals). User + session + audit committed atomically | **FIXED** |
| D-05 (S2) | `07…` accepted at registration, rejected at login | Login looked up the raw identifier; only registration normalised | Shared `core/identifiers.py` used by registration, login, profile and addresses. DB CHECK keeps phones canonical. **No data migration needed:** every write path already stored `+2507XXXXXXXX`; dev DB checked read-only: 0 non-canonical of 5. The new CHECK makes the migration fail loudly if any existed | **FIXED** |
| D-08 (S2) | Audit rows modifiable; audit not atomic | No DB protection; app ran as a superuser role | Trigger blocks UPDATE/DELETE/TRUNCATE for all roles, except the users-FK `SET NULL`. `scripts/provision_runtime_role.py` creates a non-owner, non-superuser runtime role (SELECT/INSERT only on `audit_records`). Alembic uses `MIGRATION_DATABASE_URL` | **FIXED** (local dev `.env` still uses the superuser role; see §8) |
| D-09 (S2) | Raw email/phone in failed-login/registration audit | Logged verbatim | `identifier_ref` = HMAC-SHA256 with `AUDIT_HMAC_KEY`. The sanitizer replaces any `identifier`/`email`/`phone` key | **FIXED** |
| D-10 (S3) | Login timing revealed account existence (71.8 vs 14.5 ms) | No password work for unknown users | `burn_password_check` runs equal scrypt work | **FIXED** (93.8 vs 94.7 ms) |
| D-13 (S2) | Ruff: 2 lint errors, 12 files unformatted | Duplicate import, no format pass | Fixed; scripts linted too; CI now checks `../scripts` | **FIXED** |
| D-14 (S3) | OpenAPI: 400 vs 422, missing 403s, no error schemas, duplicate tag, untyped staff responses, PUT semantics | Hand-written response maps | `api/v1/responses.py` shared declarations with an `ErrorResponse` schema; 400 removed; 401/403/404/409/422/429/503 documented where real; `Health` tag unified; staff `GuardResult` model; PUT labelled "partial"; login documents the rate limit | **FIXED** |
| D-15 (S3) | SQLite-only tests, gaps | — | +56 SQLite/unit tests; new PostgreSQL + Redis + real-HTTP suite (23 tests), wired into CI | **FIXED** |
| D-16 (S3) | Checkpoint script overclaimed and was unsafe | — | Refuses DB names not ending in `_test`/`_audit`; [7] and [12] now query PostgreSQL; labelled in-process; lint-clean | **FIXED** |
| D-18 (S3) | `app/core/security/` leftover dir | — | Not removed: the tracked `.gitkeep` is foundation scaffolding, and deleting it is outside this task | OPEN (S3) |
| D-06 | No order history | Feature not built | — | **BLOCKED** (dependency) |
| D-07 (S2) | Staff endpoints are demos; permission matrix not enforced (sales can use `address:manage` endpoints); no staff provisioning | Matrix and features not approved | Staff routes relabelled `[Demo]` in code and OpenAPI, typed responses. Matrix enforcement **not changed** (needs RE-004 P1 approval) | OPEN — decision |
| D-11 (S3) | Invalid-token requests each write an audit row | — | Not changed (outside this task's list) | OPEN |
| D-12 | Schema created while ADR-002 is Proposed | Process | Auth security decisions recorded in ADR-006; ADR-002 approval still pending | OPEN — governance |
| D-17 (S3) | `allow_credentials=True` with bearer auth; client IP from direct peer | — | Not changed; trusted-proxy configuration is documented in code | OPEN |
| C6 (S3) | Phone (login identifier) change needs no re-auth; sessions kept | Policy | Not changed | OPEN — decision |

## 3. Files and migrations changed

**New migration:** `backend/alembic/versions/5c2f9a1d7e40_auth_integrity_constraints_audit_append_only.py` (revises `87668c54003d`). It contains the default-address data fix, the partial unique index, canonical-phone CHECKs on users and addresses, a role CHECK, and the append-only trigger function with row and TRUNCATE triggers. The downgrade reverses all of it.

**New modules:** `app/core/identifiers.py`, `app/core/request_context.py`, `app/core/rate_limit.py`, `app/db/transaction.py`, `app/api/v1/responses.py`, `scripts/provision_runtime_role.py`.

**Rewritten/updated:**
- `app/core/config.py` (Redis, HMAC key, limits, migration URL), `app/core/security.py`, `app/core/dependencies.py`
- all four repositories (flush-only, row lock), all four services (atomic units, IntegrityError handling)
- `schemas/auth.py`, `schemas/customer.py`, `schemas/address.py`
- endpoints `auth.py`, `customers.py`, `staff.py`, `audit.py`, `health.py`
- `models/user.py`, `models/address.py`, `main.py`, `alembic/env.py`

**Tests:**
- `tests/conftest.py` (fresh DB per test, in-memory limiter, management fixture)
- `tests/support/memory_rate_limit.py`
- `tests/unit/test_remediation_units.py`, `tests/integration/test_remediation_api.py`
- `tests/postgres/conftest.py`, `tests/postgres/test_pg_http.py`
- one assertion in `tests/unit/test_security.py` changed to the new pseudonymisation policy (intended behaviour change)

**Infra/config:**
- `docker-compose.yml` (Redis 7.4, localhost only, no persistence)
- `.github/workflows/ci.yml` (Postgres 18 + Redis services, PG suite, scripts linted)
- `pyproject.toml`/`uv.lock` (`redis` 6.4.0; dev `openapi-spec-validator` 0.7.2)
- env templates (root, backend, staging, production)
- `scripts/verify_postgres_live.py`; `scripts/check_database.py` (import order only, via `ruff --fix`)

**Docs:** `docs/architecture/ADR-006-authentication-security-controls.md`, this report.

**Local only (git-ignored):** `AUDIT_HMAC_KEY` (newly generated) and `REDIS_URL` were appended to `backend/.env`; existing values were untouched.

## 4. Regression tests added (79)

- **Unit (29, `test_remediation_units.py`):** UA truncation and control characters; IP validation (7 cases); request-context bounding; audit-detail bounding and list handling; keyed pseudonym; phone formats (5 valid, 6 invalid); email/password max length; rate-limit identifier threshold and reset, IP threshold, success reset.
- **SQLite API (27, `test_remediation_api.py`):**
  - oversized and malformed UA (4)
  - forced audit failure rolls back address create, profile update and registration
  - oversized email/password → 422
  - role/status ignored at registration
  - login in 3 phone formats; invalid identifier → 422
  - rate limit: threshold → 429 → allowed after window; unknown = known; formats share a bucket; success resets; 429 audited; Redis down → 503
  - pseudonymised failure audits
  - default rules: first, reject unset, replace, delete-promote, delete-last
  - management/ops denied; inactive account; logout atomic
- **PostgreSQL + Redis + real HTTP (23):** listed in §5.

## 5. Real PostgreSQL / HTTP results

Environment: PostgreSQL 18.6 (Docker), Redis 7.4.11 (Docker), Python 3.13.5. Disposable databases only: `rwanda_auth_test` (rebuilt by the suite) and `rwanda_acceptance_audit`. No production or dev customer records were modified (the dev DB was only read).

**PG suite (`pytest tests/postgres`): 23 passed, 0 failed.** The API ran as **two separate uvicorn processes** sharing Redis, connected as the least-privilege runtime role. Assertions queried PostgreSQL as the owner.

| Test | Proves |
| --- | --- |
| concurrent duplicate email registration across processes | 12 parallel → exactly `[201] + [409]×11`, 1 row |
| concurrent duplicate phone in mixed formats | 9 parallel, 3 formats → 1×201, 8×409 |
| oversized/invalid registration → 422 | no DB internals in responses |
| public registration creates customer only | role/is_active payload ignored (DB checked) |
| login with every approved phone format | 4 formats → 200 |
| DB rejects non-canonical phone | CHECK constraint |
| oversized UA persisted with audit | rows stored with 512-char UA |
| **audit failure rolls back** create/update/delete/profile/logout | each 500 with **nothing committed** (DB re-read; token still valid) |
| concurrent first addresses | 10 parallel → 10 rows, **1 default** |
| concurrent create-as-default | 10 parallel → **1 default** |
| concurrent set-default then concurrent deletes | 1 default after each phase |
| unset default rejected + DB backstop | 422; direct second default → UniqueViolation |
| cross-customer access | 4×404, row byte-identical; client `user_id` ignored |
| customer cannot change role | 422, DB role unchanged |
| session expiry and revocation | revoked_at set; reuse 401; expired 401 |
| audit append-only even for owner | UPDATE/DELETE/TRUNCATE blocked |
| runtime role cannot modify audit | UPDATE/DELETE/TRUNCATE/DISABLE TRIGGER denied; not superuser |
| user deletion keeps audit history | rows kept, actor_id nulled |
| failed-login audit pseudonymised | identifier_ref matches; raw email absent |
| identifier limit shared across processes, then resets | 5×401 → 429 on both processes → 200 after window |
| unknown identifier limited identically | `[401×5, 429]` for both |
| IP limit | 20 identifiers ×1 failure → 21st 429 |
| live OpenAPI valid/complete/accurate | see §6 |

**Original audit probes, re-run after fixes on a live server (`rwanda_acceptance_audit`):** 33 probes, **14 FAIL → 5 FAIL**. Server log: 0 errors/tracebacks. The audit-bypass probe now gives 201/200, with the change and its audit row both persisted.

| Still failing | Reason |
| --- | --- |
| B5 timing | Measurement artifact: the account had just been rate-limited. A fair re-test (fresh accounts, below threshold, 5 trials) gives 93.8 vs 94.7 ms → **resolved** |
| C5 invalid-token audit rows | Not in scope (D-11) |
| C6 phone change without re-auth | Decision pending |
| D3 order history | Blocked dependency |
| F3 permission matrix | Decision pending (D-07) |

**Migration evidence:**
- `upgrade head` and `alembic check` (no drift) pass on both databases; downgrade/upgrade round trip OK.
- Data-fix test: at the old revision I seeded one customer with 2 defaults and one with 0, then upgraded. Only the newest default remained for the first; the second customer's newest address became the default.

**Checkpoint script (in-process, not real HTTP):** guard refuses `rwanda_ecommerce`; 12/12 PASS on `rwanda_acceptance_audit`, including DB re-reads for [7] and [12].

## 6. Swagger verification

**Scripted (automated, live server, `test_live_openapi_is_valid_complete_and_accurate`):**
- `openapi-spec-validator` passes (OpenAPI 3.1).
- All 17 implemented operations are present, with no extras.
- No operation documents 400.
- Every protected operation uses `BearerAuth` and documents 401 with the `ErrorResponse` schema (403 everywhere except logout, which cannot return it).
- Login documents 401/403/422/429 (with `Retry-After`)/503.
- No `password_hash`/`token_hash` in any schema; every used tag is declared.

**Browser-based Swagger UI test (Claude in Chrome, real Chrome, `http://127.0.0.1:8765/docs`):**

| Step | How performed | Result |
| --- | --- | --- |
| Page renders; single "Health" tag | Screenshot | PASS |
| Register with example body (`"email":"string"`) | Clicked *Try it out* / *Execute* | 422 with field errors shown |
| Register test account (`0788 456 789`) | Typed body, clicked *Execute* | 201, phone shown as `+250788456789`, no internal fields |
| Authorize dialog | Opened via button | Shows `BearerAuth (http, Bearer)` + instructions; after entry shows "Authorized" and masks the value (token was entered from page memory by script, not typed by hand) |
| PUT `is_default:false` on default | Path ID and body typed with keystrokes | 422 "A default delivery address is required…" |
| POST …/default, DELETE default, list | ID typed; executed | 200; 200; list shows the other address promoted |
| Audit logs as customer | Executed | 403 "requires 'audit:read'" |
| Logout, then /auth/me | Executed | 200; then 401 "Session is invalid, expired, or revoked" |
| DB confirmation | psql | Canonical phone, role customer, 1 address (default), 1 revoked session, matching audit trail |

Caveat: some steps were driven by script-clicking Swagger's own buttons rather than by hand. A first scripted batch set the PUT path field programmatically; Swagger kept its previous internal value and sent one update to the other address (the request was correct for what Swagger sent, and the server behaved correctly). Results from that batch were discarded. Steps needing IDs were then redone with real keystrokes, and the request URL Swagger actually sent was checked each time.

## 7. Ruff / CI-equivalent results (final run, after all edits)

| Check | Result |
| --- | --- |
| `uv lock --check` | OK (55 packages) |
| `pytest --ignore=tests/postgres` | **98 passed** (42 original + 56 new); 1 warning (third-party Starlette TestClient deprecation) |
| `pytest tests/postgres` (PG 18 + Redis + HTTP) | **23 passed** |
| `ruff check . ../scripts` | All checks passed |
| `ruff format --check . ../scripts` | 63 files already formatted |
| `alembic check` | No drift |
| Frontend `lint` / `typecheck` / `build` | Pass (frontend unchanged) |
| GitHub Actions | **Not run.** The updated workflow (with Postgres/Redis services) has not executed on GitHub yet |

## 8. Unresolved blockers and deferred dependencies

**Blockers to marking the card Done:**
1. **PR-06 order history / TC-07 checkout:** order and checkout features don't exist (ADR-002 order schema not approved).
2. **TC-16:** only demo guards exist. Real sales/operations/admin functions are required to test "cannot access unauthorized admin functions", and the permission matrix (RE-004 P1) must be approved and enforced with `require_permission`. **Integration-test dependency:** re-run TC-16 when catalogue, stock, order and user-management endpoints exist.
3. **Governance:** ADR-002 is still *Proposed*. ADR-006 records only the auth security decisions approved here.

**Deployment actions before staging/production:**
- run `alembic upgrade head` as the owner role;
- run `scripts/provision_runtime_role.py`;
- point `DATABASE_URL` at the runtime role;
- set `REDIS_URL` and `AUDIT_HMAC_KEY` from a secret store;
- configure uvicorn `--proxy-headers --forwarded-allow-ips` behind the proxy, so the per-IP limit sees real client IPs.

The local dev database `rwanda_ecommerce` was **not** migrated or switched to the runtime role. Run `alembic upgrade head` there when ready; it is safe (0 conflicting rows).

**Decisions still needed:** password recovery; session policy; identifier verification and re-auth; frontend token storage; staff provisioning; audit retention; invalid-token audit throttling; Swagger exposure in production; Redis fail-closed vs fail-open; CORS credentials.

## 9. Requirements traceability

| Req | Expected | Evidence after remediation | Status |
| --- | --- | --- | --- |
| PR-06 register/login by email or phone | Approved formats work consistently | Login in all formats (SQLite ×3, PG ×4, browser); no 500s under races/oversized input | **PASS** |
| PR-06 saved addresses | CRUD, ownership, consistent default | PG concurrency tests; cross-customer 404s with DB unchanged; browser CRUD | **PASS** |
| PR-06 order history | Customer views orders | Not implemented | **BLOCKED** |
| PR-06 overall | — | — | **BLOCKED** (order history) |
| PR-15 protected access / least privilege (auth scope) | Backend authorization, least-privilege DB access | Role guards and ownership verified; runtime DB role cannot alter audit; permission matrix enforcement still pending approval | **PASS** for auth/account scope; staff matrix → TC-16 |
| PR-15 audit and security events | Complete, tamper-resistant, atomic | Rollback tests; append-only trigger; pseudonymised identifiers; rate-limit events audited | **PASS** |
| PR-15 brute-force protection | Login throttled | Shared Redis limits across processes; 429 + reset; no enumeration | **PASS** |
| PR-15 secrets / data minimisation | No secrets in source/logs | HMAC key and Redis URL from env; templates use placeholders; raw identifiers absent from audit | **PASS** |
| PR-15 HTTPS, backups, published policies | — | Outside this card | **DEFERRED** (ADR-004 / business) |
| TC-07 checkout with account | Login, saved address, order history in checkout | Login and addresses pass; checkout/orders absent | **BLOCKED** |
| TC-16 staff roles | Sales/ops cannot reach unauthorized admin functions | Demo guards and audit-log access matrix pass (admin/sales/ops/management/customer); no real admin functions exist | **DEFERRED** (integration dependency) |

## 10. Final recommendation

All S1/S2 security and data-integrity defects within this card's scope are corrected and verified on PostgreSQL over real HTTP:
- audit bypass
- login rate limiting
- default-address races
- registration 500s
- phone normalisation
- audit tampering and PII

**Recommendation: approve the remediation for code review/merge. Do NOT mark the Trello card Done:** PR-06 and TC-07 are BLOCKED (orders/checkout), TC-16 is DEFERRED (real staff functions and permission-matrix approval), and the open decisions in §8 remain.
