# Acceptance Audit — Authentication, Customer Accounts, Addresses, Staff Authorization, Audit

| Field | Value |
| --- | --- |
| Date | 2026-10-21 |
| Branch / state | `dev` @ `6489dac` + uncommitted working tree (all auth/account files untracked) |
| Requirements audited | PR-06, PR-15 (auth/account scope), TC-07, TC-16 (source: `docs/01_…PRD.docx` §5, `docs/03_…QA_UAT….docx` §2) |
| Trello card IDs | Not verified — `docs/requirements/README.md` records that board access failed. Requirement IDs above come from the source documents. |
| Auditor | Claude Code (independent re-verification; no application code changed) |
| **Recommendation** | **APPROVAL BLOCKED — CORRECTIONS REQUIRED** |

## 1. Inputs and limitations

- **Prior reports not available.** The "Phase 1: Repository and Requirements Inspection Report" and the "Backend Delivery Report" are not in the repository, the docs folder, or earlier local Claude sessions. This audit was done directly against the source documents, ADR-001/ADR-002, RE-004 and the code. Claims from those reports (42 tests, 12 checkpoints) were re-run independently.
- **Governance context.** ADR-002 status is still *Proposed* (line 3). RE-004 resolution plan says "No revision before ADR-002 approval" and lists *Staff permissions/authentication* as a P1 decision requiring a "reviewed permission matrix, authentication/session decision". ADR-001 lists "authentication/session/roles" as unresolved. No auth/session ADR exists. Even so, a migration (`87668c54003d`) and models were created.
- **Manual Swagger browser testing was not performed.** All HTTP evidence below is automated: in-process TestClient (pytest, checkpoint script) or real HTTP against a live uvicorn server (live probes).

## 2. Evidence runs (actual results)

| Run | Environment | Result |
| --- | --- | --- |
| pytest (42 reported tests) | `backend/.venv`, Python 3.13.5, **SQLite in-memory** (`tests/conftest.py:10`) | **42 passed**, 0 failed, 1 deprecation warning |
| Ruff lint `ruff check .` (backend, as CI runs it) | — | **FAIL — 2 errors**: `alembic/env.py:1` I001, `alembic/env.py:7` F811 (`app.models` imported twice) |
| Ruff format `ruff format --check .` (backend, as CI runs it) | — | **FAIL — 12 files would be reformatted** |
| Ruff on `scripts/` | — | 19 errors (E402, F401, F841, E501) in `verify_postgres_live.py`/`check_database.py` |
| Alembic | Dedicated DB `rwanda_acceptance_audit` on local PostgreSQL 18.6 | `upgrade head` OK; `alembic check`: no drift; `downgrade base` → `upgrade head` round trip OK |
| 12 PostgreSQL checkpoints (`scripts/verify_postgres_live.py`) | Same dedicated DB, run twice | **12/12 PASS** both runs. Caveats in §6. |
| Live HTTP probes (33 probes) | Real uvicorn `127.0.0.1:8765` + direct psycopg queries on the dedicated DB | **19 PASS / 14 FAIL** (detail in §4) |
| Audit-evasion probe | Same | Confirmed defect (§4, B7a) |
| Frontend ESLint / TypeScript / build | — | Not run: no frontend files changed in this delivery |

Probe scripts (not committed): `C:\Users\user\AppData\Local\Temp\claude\C--Users-user-Documents-tsonGroup-rwanda-electronics-ecommerce\0916a913-22a2-4582-9ee9-ba83718cf106\scratchpad\live_probe.py` and `C:\Users\user\AppData\Local\Temp\claude\C--Users-user-Documents-tsonGroup-rwanda-electronics-ecommerce\0916a913-22a2-4582-9ee9-ba83718cf106\scratchpad\ua_probe.py`; raw results in `C:\Users\user\AppData\Local\Temp\claude\C--Users-user-Documents-tsonGroup-rwanda-electronics-ecommerce\0916a913-22a2-4582-9ee9-ba83718cf106\scratchpad\live_probe_results.json`.

## 3. Requirement verdicts

Severity uses the QA checklist scale (S0 Critical … S3 Low).

| Req | Expected behaviour (source) | Actual implemented behaviour | Source refs | Test evidence | Status | Defect severity | Recommended correction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **PR-06** Accounts | "Customer can register/login by approved email or phone method and view order history and saved addresses." | Register/login by email or phone works; saved-address CRUD works with server-side ownership. **No order history** (no order module). Login with the local phone format `07XXXXXXXX` fails even though registration accepts it. Over-length email and concurrent duplicate registration return HTTP 500. "Approved method" is undefined: no email/phone verification exists. | `services/auth_service.py:24-158`; `schemas/auth.py:19-62`; `repositories/user_repository.py:23-32`; `api/v1/endpoints/customers.py` | pytest auth/profile/address (25 tests pass); live A1–A7, B1–B3, D1–D3, E1–E4 | **FAIL** (order history part: BLOCKED by order schema / ADR-002) | S2 | Fix D-04, D-05, D-03; get the identifier-verification decision approved; implement order history once the order schema is approved. |
| **PR-15** Security & privacy (auth/account scope) | HTTPS, protected admin access, least-privilege roles, secure secrets, data minimisation, backups, published policies. Tech plan §6: least privilege + audit important changes; no unnecessary personal data in logs. | Passwords use salted scrypt with constant-time compare. Only SHA-256 of 256-bit session tokens is stored. `.env` files are git-ignored and no secrets are committed. **But:** no login rate limiting or lockout; audit can be bypassed via a long User-Agent; audit rows can be changed at the DB level; failed-login audit stores raw email/phone; the declared permission matrix is not enforced. HTTPS, backups and policies are outside this delivery. | `core/security.py:12-79`; `services/auth_service.py:102-115`; `models/audit.py:30`; `repositories/audit_repository.py:37-38`; `core/roles.py:4-52` | pytest `test_security.py` (6 pass); live A1, B4–B7, C5, F3, G1, ua_probe | **FAIL** (HTTPS/backups/policies: NOT VERIFIED — out of scope) | S1 | Fix D-01, D-02, D-08, D-09, D-07. |
| **TC-07** Checkout with account | "Login, saved address and order history work as specified." | Login and saved addresses exist, with defects. **Checkout and order history do not exist.** The scenario cannot be executed. | — (no checkout/order code) | live D3: `GET /customers/me/orders` → 404 | **BLOCKED** | — (dependency) | Re-run after cart/checkout/order features are approved and built. The login and address parts must first clear D-03/D-05. |
| **TC-16** Staff roles | "Sales/operations cannot access unauthorized admin functions." | Only three **demonstration** endpoints exist (`/staff/admin-only`, `/sales-only`, `/operations-only`), each returning a static message, plus the admin audit-log list. The guards behave correctly on them. **No real admin functions exist** (catalogue, stock, orders, users, settings), so the test as written cannot be executed. `ROLE_PERMISSIONS` is defined but only used for `audit:read`. Customer endpoints do not check permissions (sales staff can create addresses without `address:manage`). There is no supported way to create staff accounts (tests and the script insert rows directly). Management role has no tests. The permission matrix is not approved (RE-004 P1). | `api/v1/endpoints/staff.py:11-90`; `core/dependencies.py:71-132`; `core/roles.py:4-52`; `api/v1/endpoints/audit.py:32` | pytest staff (5 pass), audit access (1 pass); live F1 (full matrix incl. management: as expected), F2 pass, F3 fail | **BLOCKED** (guard mechanism: PASS on demo endpoints) | S2 | Get the role/permission matrix approved. Replace demo routes with `require_permission` on real admin endpoints as they are built. Add an approved staff-provisioning path (e.g., an audited CLI). Re-run TC-16 on real functions. |

## 4. Verification topics requested

| Topic | Finding | Evidence | Status |
| --- | --- | --- | --- |
| Registration & auth security | scrypt N=16384,r=8,p=1, 16-byte salt, `compare_digest` (`core/security.py:12-50`). Password policy is ≥8 chars, upper, lower, digit/special (`:53-69`). Public registration ignores `role`/`is_active` in the payload (A2: db role=`customer`). Duplicate email (case-insensitive) and phone (any format) give 409 (A4/A5). **Defects:** email has no `max_length` → 265-char email gives HTTP 500 (A6, `StringDataRightTruncation varchar(255)`). Duplicate check then insert is not atomic → 10 parallel registrations give 1×201 + **9×500** (A7, `UniqueViolation ix_users_email`). Login timing reveals account existence (B5: 71.8 ms vs 14.5 ms, no dummy hash). | A1–A7, B1–B5 | PASS with defects D-04, D-10 |
| Public registration role restriction | `register_customer` hard-codes `UserRole.CUSTOMER` (`auth_service.py:65`). `RegisterRequest` has no role field. | A2; no pytest covers this | **PASS** (test gap) |
| Session expiry & revocation | Tokens are 32-byte `token_urlsafe`, SHA-256 at rest (`session.py:24`). Fixed 7-day absolute lifetime (`auth_service.py:19`). Lookup checks `is_active`, `revoked_at`, `expires_at` (`session_repository.py:37-46`). Logout sets `is_active=false`, `revoked_at` (C2 confirmed in DB). Reuse gives 401; expired gives 401 (C3); deactivated account gives 403 on existing token and login (C4). **Gaps (policy decisions):** no idle timeout, same lifetime for staff and customers, no logout-all (`revoke_all_user_sessions` at `session_repository.py:61` is never called), changing the phone identifier needs no password and keeps sessions (C6), no expired-session cleanup. | C1–C6 | PASS (mechanism); policy gaps → §7 |
| Server-side customer ownership | All address queries are scoped by `user_id` from the session (`address_repository.py:11-19`). Cross-customer GET/PUT/default/DELETE gives 404, DB row unchanged (D1). Client-supplied `user_id` is ignored on create/update (D2). Profile PATCH forbids extra fields (`schemas/customer.py:23`). | pytest isolation test; D1, D2 | **PASS** |
| Default address consistency | Sequential flows are correct: first address auto-default, switch, delete-promotion (E2, E4, pytest). **Defects:** (a) 10 concurrent "create as default" left **3 default rows** (E1). Count-then-insert and unset-then-insert are not serialised, and there is no partial unique index (`migration :36-53`). (b) `PUT {is_default:false}` on the only default leaves **0 defaults** (E3, `address_repository.py:87-88`). (c) Delete and promotion are two separate commits (`address_service.py:117-123`). | E1–E4 | **FAIL** — D-03 |
| Staff roles vs TC-16 | See TC-16 row. Live matrix: admin all 200; sales only sales-only; ops only ops-only; management and customer all 403; audit-logs admin only (F1). | F1–F3 | BLOCKED / partial |
| Staff endpoints: production or demo? | **Temporary authorization demonstrations.** They return static `{"status":"granted","message":…}` dicts, have no business behaviour, have untyped responses, and are not in any requirement or ADR. They count as undocumented features under AGENTS.md. | `staff.py:25-90` | Must be removed or replaced before approval |
| Security event auditing | Events: `auth.register`, `auth.login` (success/failure), `auth.logout`, `auth.session_invalid`, `auth.access_denied`, `user.profile.update`, `address.*` (G3). Sensitive keys are redacted (`audit_service.py:10-39`). **Defects:** (a) **Audit evasion:** a request with a 600-char User-Agent commits the change and then fails the audit insert (`varchar(512)`) → HTTP 500, **change persisted, 0 audit rows** (ua_probe, address create and profile update). The same input breaks login with a 500 (B7). (b) Audit is written in a separate commit after the business commit (`audit_repository.py:37-38`), against ADR-002 line 48 "commit atomically". (c) No DB-level append-only protection; the app role can UPDATE audit rows (G1). (d) Failed login stores the raw identifier (B6, `auth_service.py:110`); failed registration stores email/phone (`:37`, `:51`). (e) Unauthenticated garbage tokens add one audit row per request with no throttling (C5: +25 rows). | G1–G3, B6, B7, C5, ua_probe | **FAIL** — D-02, D-08, D-09, D-11 |
| Login rate limiting | **Not implemented anywhere** (no limiter, middleware or failed-attempt counter). 30 rapid wrong passwords all returned 401 (no 429); the correct password then succeeded (B4). | B4; grep of `app/` | **FAIL** — D-01 |
| Swagger/OpenAPI accuracy & usability | Live `/api/v1/openapi.json` (OpenAPI 3.1) documents **all 13 paths / 17 operations** in the source. `BearerAuth` HTTP bearer scheme is applied to every protected operation, so Swagger "Authorize" works with the raw `session_token` from login/register. **Inaccuracies:** 400 "Validation error" documented on register/address create/update, but validation actually returns 422 (A3). 403 (inactive account) undocumented on `/customers/*`. No error body schemas. Tag `health` vs metadata `Health` gives a duplicate, empty tag group (`health.py:8`, `main.py:13`). `PUT` address has partial (PATCH) semantics. Staff responses untyped. `/docs` and `/redoc` are exposed in every environment (`main.py:43-44`; `app_env` unused). | live OpenAPI dump | PASS (completeness) / FAIL (accuracy, S3) — D-14 |

## 5. Defect register

| ID | Severity | Defect | Location | Recommended correction |
| --- | --- | --- | --- | --- |
| D-01 | **S1** | No login (or registration) rate limiting / lockout. Brute force and credential stuffing are unthrottled. | `endpoints/auth.py:55-82`, `auth_service.py:102-115` | Add per-identifier and per-client throttling returning 429 + `Retry-After`, audited. Make it proxy-aware for the client IP. Thresholds need approval (§7). |
| D-02 | **S1** | Audit evasion and HTTP 500 via over-length User-Agent: change commits, audit insert fails. Login also returns 500. | `models/audit.py:30`, `models/session.py:26`, `audit_repository.py:37-38`, all `log_event` callers | Truncate/normalise UA (and other header-derived values) before persistence. Write the audit record in the same transaction as the change. Add a regression test on PostgreSQL. |
| D-03 | S2 | Default address not guaranteed unique under concurrency (3 defaults observed). Zero defaults possible via PUT. Delete+promote not atomic. | `address_repository.py:36-122`, `address_service.py:22-24,117-123`, migration | Add a partial unique index `ON addresses(user_id) WHERE is_default`. Lock the user's address set (`SELECT … FOR UPDATE`) inside one transaction. Decide whether "≥1 default when addresses exist" is required. |
| D-04 | S2 | Unhandled DB errors → 500: concurrent duplicate registration; email > 255 chars. | `auth_service.py:30-66`, `schemas/auth.py:34` | Catch `IntegrityError` → 409. Add `max_length=254` to email (and bound `identifier`/`password` lengths). |
| D-05 | S2 | Phone login fails for the `07XXXXXXXX` format accepted at registration. | `schemas/auth.py:60-62`, `user_repository.py:23-32` | Normalise phone-like identifiers with `validate_rwanda_phone` before lookup. Add a test. |
| D-06 | S2 (dependency) | Order history missing (PR-06, TC-07). | — | Implement after order schema approval (ADR-002/RE-004 P0). |
| D-07 | S2 | Staff endpoints are demo stubs. Permission matrix is defined but not enforced (sales can use `address:manage` endpoints). Two parallel mechanisms (`require_role` vs `require_permission`). No staff provisioning path. Matrix not approved. | `staff.py`, `core/roles.py`, `core/dependencies.py:71-132`, `customers.py` | Remove the demo routes before merge (or mark them dev-only with approval). Standardise on `require_permission`. Get the matrix approved. Add an audited staff-provisioning mechanism. |
| D-08 | S2 | Audit not append-only at DB level. Audit commits are separate from business commits. | migration `:54-74`, `audit_repository.py` | Revoke UPDATE/DELETE from the app role or add a trigger. Write the audit in the same transaction (ADR-002 l.48). |
| D-09 | S2 | Personal data in audit details: raw login identifier on every failed login, email/phone on failed registration. | `auth_service.py:37,51,110` | Store a keyed hash or masked identifier. Retention/redaction policy needs approval (ADR-002 l.39). |
| D-10 | S3 | Account enumeration: login timing (B5) and explicit 409 on registration. | `auth_service.py:39-56,103` | Verify against a dummy hash when the user is not found. The registration-enumeration stance is a product decision. |
| D-11 | S3 | Unauthenticated requests with invalid tokens each write an audit row, unthrottled (storage flooding). | `core/dependencies.py:39-47` | Throttle or aggregate invalid-token events, or log them to the application log instead. |
| D-12 | S2 (process) | Models/migration created while ADR-002 is *Proposed*, and no auth/session ADR exists, contrary to RE-004 ("No revision before ADR-002 approval") and AGENTS.md (review data design first; document architectural decisions). `docs/api/` is empty. | `alembic/versions/87668c54003d_…py`; `docs/architecture/` | Record approval of the user/session/address/audit schema subset and an auth/session ADR, or explicitly accept the deviation. |
| D-13 | S2 (process) | CI would fail: `ruff check` 2 errors, `ruff format --check` 12 files. | `alembic/env.py:3,7` + 12 files | Remove the duplicate import and run `ruff format`. Lint the scripts too. |
| D-14 | S3 | OpenAPI inaccuracies (400 vs 422, missing 403s, no error schemas, duplicate `health` tag, PUT semantics, untyped staff responses). Docs exposed in production. | `auth.py:33`, `customers.py:84,156`, `health.py:8`, `main.py:43-44` | Correct the response declarations. Use PATCH or full-replace PUT. Gate `/docs` by `APP_ENV` (decision). |
| D-15 | S3 | Test coverage too thin to support approval: SQLite-only (misses PG length limits, concurrency, locking). No tests for role escalation at registration, rate limiting, management role, ops→audit-logs, inactive accounts, failed-login audit content, phone-format login, concurrency, or delete-promotion. `test_expired_session_rejected` asserts "expired", which the generic message always contains. | `tests/conftest.py:10-28`, `tests/integration/test_auth_api.py:179` | Run integration tests on PostgreSQL (dedicated test DB). Add the missing negative and concurrency tests. |
| D-16 | S3 | Checkpoint script overclaims and is unsafe: [7] says "persisted in DB" and [12] says "revoked in PostgreSQL" but never query the DB. It uses in-process TestClient, not live HTTP. It deletes users from whatever `DATABASE_URL` points to (default: dev DB). It leaves staff rows behind. | `scripts/verify_postgres_live.py:31,69,135,308` | Add DB assertions. Refuse to run unless the DB name is a dedicated test DB. Clean up created rows. |
| D-17 | S3 | `allow_credentials` changed to `True` though auth uses bearer headers, not cookies. Client IP taken from `request.client` (wrong behind a proxy). | `main.py:50`, endpoints | Revert to `False` unless cookie sessions are approved. Configure trusted-proxy handling. |
| D-18 | S3 | Leftover `backend/app/core/security/.gitkeep` directory next to `core/security.py` (confusing package/module shadowing). | `backend/app/core/security/` | Remove the empty directory. |

## 6. Checkpoint script results (12/12) — how much they prove

| # | Checkpoint | Result | Independent assessment |
| --- | --- | --- | --- |
| 1 | PostgreSQL connectivity | PASS | Valid |
| 2 | Swagger `/docs` HTTP 200 | PASS | Only shows the HTML loads, not usability |
| 3 | OpenAPI inventory (13 paths) | PASS | Confirmed independently against the live server |
| 4–5 | Register Alice/Bob | PASS | Valid; persistence queried |
| 6 | Login | PASS | Valid |
| 7 | Profile retrieve/update "persisted in DB" | PASS | **DB not queried** — claim unsupported (independently confirmed by live probes) |
| 8 | Cross-customer isolation | PASS | Valid (HTTP only); live D1 also verified the DB row was unchanged |
| 9 | Delete default → promotion | PASS | Valid; DB queried |
| 10 | Staff guards (TC-16) | PASS | Demo endpoints only; management role not covered |
| 11 | Audit logging | PASS | Only checks count > 0 |
| 12 | Logout "revoked in PostgreSQL" | PASS | **DB not queried** (live C2 confirmed `is_active=false`, `revoked_at` set) |

All 12 run in-process via TestClient. Real-HTTP verification is only in the live probes (§4).

## 7. Decisions requiring approval (not implemented, per instructions)

1. **Password recovery / reset** — not implemented. Needs channel (email/SMS), provider (ADR-005 pending), token lifetime, and session revocation on reset.
2. **Session policy** — current: 7-day absolute, no idle timeout, unlimited concurrent sessions, same for staff and customers, no logout-all, no revocation on identifier/password change. Approve lifetimes (possibly shorter for staff), idle timeout, logout-all and revocation triggers.
3. **Token transport/storage for the frontend** — bearer token in a JSON body (frontend would hold it in JS) vs httpOnly secure cookie with CSRF protection. Affects D-17.
4. **"Approved email or phone method" (PR-06)** — whether email/phone must be verified (OTP/link) before use, and whether a phone change needs re-authentication.
5. **Rate-limit and lockout thresholds** and the handling of enumeration responses.
6. **Staff permission matrix** (admin/sales/operations/management) and **staff provisioning** authority (RE-004 P1).
7. **Audit scope, retention, PII handling and access** (ADR-002 l.39).
8. **Default-address invariant** — must a customer with addresses always have exactly one default?
9. **Swagger/ReDoc exposure** in staging/production.
10. **Formal approval** of the user/session/address/audit schema subset of ADR-002, or acceptance of the deviation (D-12).

## 8. Conclusion

What works (verified on PostgreSQL over real HTTP): password hashing, token handling, logout/expiry revocation, server-side address ownership, public registration locked to the customer role, and the role guards on the demo endpoints.

Approval is not supported because:

- there are two S1 security defects (no login rate limiting; audit bypass / 500 via long User-Agent);
- default-address consistency fails under concurrency;
- PR-06 order history and all of TC-07 are blocked by missing order/checkout features;
- TC-16 cannot be executed because staff endpoints are demonstrations, not admin functions;
- CI lint/format checks would fail;
- the schema and auth design were implemented without the approvals RE-004 requires.

**APPROVAL BLOCKED — CORRECTIONS REQUIRED.** Do not mark PR-06, PR-15, TC-07 or TC-16 complete.

Minimum to re-audit: fix D-01, D-02, D-03, D-04, D-05, D-07 (remove or replace demo routes), D-08, D-09, D-13. Add PostgreSQL-backed tests for each (D-15). Record decisions §7.2, §7.4, §7.5, §7.6 and §7.10. PR-06 order history and TC-07 stay BLOCKED until orders/checkout exist.

The dedicated audit database `rwanda_acceptance_audit` was left in place as evidence. Drop it with `docker exec rwanda-electronics-ecommerce-db-1 psql -U rwanda_dev -d rwanda_ecommerce -c "DROP DATABASE rwanda_acceptance_audit;"`.
