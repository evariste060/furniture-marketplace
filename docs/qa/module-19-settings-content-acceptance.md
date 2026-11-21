# Module 19 (settings & content) — acceptance record

> **Replaced (owner decision 2026-10-29).** This records the module 19 first merged into `dev` (PR #32). When `dev` was merged into `feat/frontend-phase-1`, the module 19 built there was kept instead, as the storefront and admin use its API; see `docs/IMPLEMENTATION_PLAN.md`, module 19. The migration `edebaf558c2d` described here stays in the history and is reshaped by `b2f6d8e4a1c9`. The business-content points below (TC-20) still apply.

| Field | Value |
| --- | --- |
| Module | 19 — settings & content (`docs/IMPLEMENTATION_PLAN.md` §5, "19 — settings & content"; §3 final staff matrix) |
| Requirements | Plan §5 module 19 (endpoints, `pages` table, tests); PRD PR-15 ("… published privacy/returns/warranty policies are in place"); PRD PR-01 (home page: "contact and trust information display correctly") and PR-04 (search: "empty results provide a helpful message and contact route"), served by the public contact details; PRD scope "English and Kinyarwanda baseline as stated in project scope; language implementation approach to be confirmed" and "WhatsApp/call links"; QA checklist TC-20 ("Privacy, return, warranty and contact pages: published pages match business-approved policies and links work"); PRD administrator role "Control … store configuration" |
| Linked tests | TC-20. QA checklist status: Not run |
| Branch | `feat/module-19-settings-content`, from `dev` at `b61ec96` (module 18); commit and push state: see the Git history |
| Trello card | None recorded in the repository; no card ID is used |
| Recorded by | Backend engineering, 2026-10-28 |
| Recommendation | **Not Done; ready for human review.** Implemented as specified; page texts and contact details are business content still to be supplied and approved (TC-20), and the engineering defaults below await approval. |

## Data design (reviewed before the model and migration, AGENTS.md)

- **Settings:** no schema change. The existing `settings` key-value table (module 12) and its registry (`app.services.settings_service.SETTINGS`) take four keys: `contact.phone`, `contact.email`, `contact.whatsapp`, `contact.address`. Every key is validated on write (request schema) and again on read (a stored value that breaks its rule is treated as unset and logged).
- **Public settings response:** a typed `{phone, email, whatsapp, address}` built from the four public keys only (`PUBLIC_KEYS`). It never lists keys dynamically, so a new private key, an unregistered stored key or the `updated_by_user_id`/`updated_at` metadata cannot leak.
- **`pages` table** (revision `edebaf558c2d`): `id`, `slug` (≤ 80, catalogue slug format, CHECK), `locale` (`en` | `rw`, CHECK), `title` (≤ 200, not blank, CHECK), `body` (Markdown, ≤ 50,000 characters, CHECK), `is_published` (default false), `updated_by_user_id` (FK users, `ON DELETE SET NULL`: removing an editor keeps the page), `created_at`, `updated_at`; unique (`slug`, `locale`) as `uq_pages_slug_locale` (a schema-unique index name). One row per language: a missing translation is a missing row.
- **Runtime grants:** `pages` SELECT, INSERT, UPDATE; no DELETE (no route deletes a page).

## Rules and their sources

| Rule | Source | Implementation |
| --- | --- | --- |
| `GET /settings` shows only contact phone, email, WhatsApp number, address | Plan §5 module 19; PRD PR-01, PR-04 (contact information) and scope ("WhatsApp/call links") | Typed allow-list response; public, cached 60 s (as `GET /banners`) |
| `PATCH /staff/settings` manages all keys with `settings:manage` | Plan §5 module 19; §3 matrix (administrator) | Existing endpoint; four keys registered; audited `settings.update` (old and new values) |
| `GET /pages/{slug}?lang=en\|rw`; a missing translation is 404, not another language | Plan §5 module 19; PRD English and Kinyarwanda baseline | Query on (`slug`, `locale`, published); otherwise 404 `page_not_found` |
| `PUT /staff/pages/{slug}` with `content:manage` | Plan §5 module 19; §3 matrix (administrator, management) | Create or replace one language version, race-free; audited |
| Body is Markdown, rendered and sanitised by the frontend | Plan §5 module 19 | Stored exactly as written (HTML included); the API never renders it |
| Only published pages are public | Plan §5 module 19 (`is_published`) | Unpublished pages are the same 404 as missing ones, so drafts are not disclosed |
| Audit important changes | Technical plan (role-based access); ADR-006 | Settings and page changes audited in the same transaction; page audits hold the body's length and SHA-256 (audit strings are bounded at 256 characters) |

## Engineering defaults and open items

No approval is recorded below unless the repository contains it.

| # | Item | Needed from | Status |
| --- | --- | --- | --- |
| S-1 | **Page content.** No page text is supplied. PR-15 requires published privacy, returns and warranty policies, and TC-20 published privacy, return, warranty and contact pages that match business-approved policies, in English and Kinyarwanda (PRD baseline). The PRD lists "Return, refund, cancellation, warranty and privacy policies" as an open decision owned by the Business + finance/legal adviser (TBD), and "Language default and translation owner" as an open decision owned by the Business owner (TBD) | Business + finance/legal adviser (policies); Business owner (language default and translation owner) | Open: business content |
| S-2 | **Contact details.** The values of `contact.*` are business data to set in each environment | Product owner / Operations | Open: business content |
| S-3 | `contact.phone` and `contact.whatsapp` accept only Rwandan mobile numbers (the project's canonical phone format, as for customers); a landline is refused | Product owner | Engineering default, not approved |
| S-4 | `lang` is required on both page routes (no default language); slugs at most 80, titles at most 200, bodies at most 50,000 characters | Product owner | Engineering default, not approved |
| S-5 | No staff route lists pages or reads a draft, and none deletes a page: the plan lists none, and AGENTS.md forbids unapproved features. A draft is only seen in the PUT response | Product owner | Recorded; add only with approval |
| S-6 | Public reads are cached for 60 seconds (as banners): a change may take up to a minute to appear | Product owner | Engineering default, not approved |

## Acceptance criteria

PASS means verified by automated tests on the isolated PostgreSQL test database (`rwanda_ecommerce_test`); it is not UAT, staging or business approval. Tests are in `backend/tests/integration/test_settings_content_api.py` unless a path is given.

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Public versus private settings: only the four contact details are public (the contact information for PR-01 and PR-04); private keys, unregistered stored keys and change metadata never appear | PASS | `test_only_the_contact_details_are_public`, `test_public_settings_start_unset_and_are_cached` |
| 2 | Contact values validated and stored canonically; invalid values 422 | PASS | `test_invalid_contact_values_are_422` (12 cases), `test_only_the_contact_details_are_public` |
| 3 | A corrupt stored value is never shown | PASS | `test_a_corrupt_stored_contact_value_is_never_shown` |
| 4 | Settings changes audited; unchanged values not audited | PASS | `test_contact_changes_are_audited_with_old_and_new_values` |
| 5 | A missing translation is 404 rather than another language; unpublished is 404 | PASS | `test_a_missing_translation_is_404_rather_than_another_language`, `test_unpublishing_hides_a_page_and_unknown_pages_are_404` |
| 6 | PUT creates (201) then replaces (200); unchanged PUT writes and audits nothing; audits hold real changes, not the body | PASS | `test_put_creates_then_replaces_a_page_and_audits_real_changes` |
| 7 | Concurrent first PUTs create one page and one create audit | PASS | `test_concurrent_first_puts_create_one_page_and_one_create_audit` |
| 8 | Permission matrix: settings changes by `settings:manage` only; page writes by `content:manage` only; public reads anonymous | PASS | `test_only_settings_manage_changes_contact_details`, `test_only_content_manage_writes_pages`, `test_management_can_manage_pages`, `test_anonymous_callers_*`; finance is also covered by `test_staff_authorization_api.py::test_finance_gets_403_on_every_permission_protected_mutation` |
| 9 | Input validation: slugs, `lang`, title, body control characters and size, strict types, extra fields | PASS | `test_invalid_public_page_requests_are_422`, `test_invalid_page_writes_are_422_and_store_nothing` |
| 10 | Markdown stored as written | PASS | `test_markdown_bodies_keep_line_breaks_tabs_and_html_as_written` |
| 11 | Database constraints | PASS | `test_the_database_refuses_invalid_pages`, `test_one_row_per_slug_and_language` |
| 12 | Migration round trip and no drift | PASS | `integration/test_pages_migration.py` |
| 13 | Runtime role grants; two API processes | PASS | `unit/test_runtime_role_grants.py::test_pages_have_exactly_the_privileges_module_19_uses`; `postgres/test_pg_settings_content.py` |
| 14 | OpenAPI inventory and public-route list updated | PASS | `postgres/test_pg_http.py` (`EXPECTED_OPERATIONS` +3, `PUBLIC` +2) |
| 15 | Full CI test commands | PASS | `uv run pytest -q --ignore=tests/postgres`: 1,829 passed (exit 0); `uv run pytest -q tests/postgres`: 104 passed (exit 0). No code changed after the run started |
| 16 | S-1 to S-6 decided; PR-15 and TC-20 met on staging with approved content; PR review, CI | **BLOCKED** | See above |

## Verification

All tests used `rwanda_ecommerce_test` (disposable per-test schemas; the PostgreSQL HTTP suite rebuilds that database's `public` schema). The development database `rwanda_ecommerce` was not migrated, seeded or read. Commands from `backend/`, 2026-10-28/29; each run started only with the database container healthy and no other test suite running.

| Command | Result |
| --- | --- |
| `uv run pytest -q tests/unit` | 514 passed (includes `test_pages_have_exactly_the_privileges_module_19_uses`) |
| `uv run pytest -q tests/integration/test_settings_content_api.py tests/integration/test_pages_migration.py` | First run: 1 failed, 58 passed: a test bug (the test client's response has no `.ok`); fixed in the test |
| Affected suites, first run: the two files above, `test_delivery_api.py`, `test_invoices_api.py`, `test_staff_authorization_api.py`, `test_notification_migration.py`, `test_payment_migration.py`, `unit/test_roles.py`, `unit/test_runtime_role_grants.py`, `postgres/test_pg_settings_content.py`, `test_pg_http.py`, `test_pg_delivery.py`, `test_pg_invoices.py` | 3 failed, 347 passed (exit 1). (1) The new audit test ordered audit records by their random UUID: now by `created_at`. (2) `test_delivery_api.py::test_settings_read_and_write_with_audit` read the first settings item as the threshold; the sorted registry now starts with `contact.address`: now looked up by key. (3) `test_settings_reject_unknown_keys_and_malformed_values` used `contact.phone` as an unknown key; it is registered now: replaced by `contact.fax`. All three were test assumptions; no application code changed |
| Affected suites, second run (same command) | **350 passed (exit 0)** |
| `uv run ruff check . ../scripts` | All checks passed (exit 0) |
| `uv run ruff format --check . ../scripts` | 305 files already formatted (exit 0) |
| `uv run mypy` | Success: no issues found in 267 source files (exit 0) |
| `git diff --check` | Clean (exit 0) |
| Alembic graph | One head, `edebaf558c2d` (26 revisions) |
| Full suite, attempt 1 (2026-10-29 00:04) | **Not completed:** the run ended with the session at about 15% (346 passed, none failed or errored); no exit code |
| **`uv run pytest -q --ignore=tests/postgres`** (2026-10-29 10:49–12:15, machine kept awake, database healthy throughout) | **1,829 passed (exit 0)**, 1 h 25 min |
| **`uv run pytest -q tests/postgres`** (12:15–12:17) | **104 passed (exit 0)** (102 earlier tests plus the 2 in `test_pg_settings_content.py`) |

Noted, not changed (module 12, outside this change): `test_delivery_api.py`'s `audits()` helper has no ORDER BY, so its ordered comparison relies on PostgreSQL returning rows in insertion order.
