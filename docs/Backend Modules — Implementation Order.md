# Backend Modules — Implementation Order

Oct 23, 2026 · @Evariste Nkurunziza

The API is built as 19 modules, one at a time in dependency order, each finished, tested and demoed before the next starts. Stack: Python + FastAPI, PostgreSQL, SQLAlchemy 2.0 + Alembic, Pydantic.

This document was aligned with the existing code on 2026-10-23 (owner decision): paths, table names, layout and conventions below are the ones the code uses. Where this differs from the first version of the plan, see **Deviations** at the end. Paths for endpoints that are not built yet follow the same conventions and are proposals until `docs/IMPLEMENTATION_PLAN.md` is approved. Build status and the detailed per-module plan are in that file.

## Module map

Build in the order shown: each module depends only on modules above it, so nothing waits on unfinished code.

| # | Module | Owns | Main tables | Depends on | Build day |
| --- | --- | --- | --- | --- | --- |
| 1 | core | Config, DB session, logging, exception handlers, auth dependencies, health check | — | — | Day 2 |
| 2 | auth | Register, login, database sessions, logout, password reset | users, user\_sessions, password\_reset\_codes | core | Day 4 |
| 3 | users | Profiles, addresses, staff accounts and roles | users, addresses, staff\_role\_assignments | auth | Day 4 |
| 4 | audit | Record who changed what on admin actions | audit\_records | auth | Day 4 |
| 5 | categories & brands | Taxonomy for browsing and filters | categories, brands | auth | Day 6 |
| 6 | products | Products, variants, specs, prices, warranty, status | products, product\_variants | categories & brands | Day 6 |
| 7 | media | Image upload, resize, ordering | product\_images | products | Day 6 |
| 8 | import | CSV/Excel catalogue import with row-level error report | import\_jobs | products, media | Day 7 |
| 9 | search | Listing with filters, sort, pagination; text search on name/brand/model | (indexes on products) | products | Day 8–9 |
| 10 | inventory | Stock levels, reservations, releases, low-stock alerts | inventory\_balances, stock\_movements, stock\_reservations | products | Day 9 |
| 11 | cart | Guest and customer carts, totals | carts, cart\_items | products, inventory | Day 9 |
| 12 | delivery | Zones, fees, free-delivery threshold, fee quote | delivery\_zones, delivery\_fee\_rules, settings (threshold only) | core | Day 10 |
| 13 | promotions | Discount codes, targets, usage limits, validation | discounts, discount\_targets, discount\_redemptions | products | Day 10 (stub), Day 14 (full) |
| 14 | orders & checkout | Create order from cart, order states, staff order handling and assignment | orders, order\_items, order\_status\_history | cart, inventory, delivery, promotions | Day 10, 13 |
| 15 | payments | MoMo, Airtel, card, COD; webhooks, idempotency, reconciliation | payment\_attempts, payment\_events | orders | Day 10–12 |
| 16 | invoices | Invoice and delivery note PDFs | invoices, invoice\_counters | orders, payments | Day 13 |
| 17 | notifications | SMS/email on order events, retries, logs | notification\_logs | orders | Day 14 |
| 18 | reports | Sales, top products, stock reports, Excel export | (reads orders, stock) | orders, inventory | Day 15 |
| 19 | settings & content | Store settings, policy pages, translations | settings, pages | core | Day 15 |

## Project structure and conventions

The code is organised by layer; each module adds one file per layer, named after the module.

```
backend/
  alembic/
    versions/                  # migrations
  alembic.ini
  pyproject.toml               # dependencies (uv)
  app/
    main.py                    # FastAPI app, middleware, exception handlers, router mounting
    core/
      config.py                # settings from env (pydantic-settings, SecretStr)
      dependencies.py          # get_current_session, get_current_user, require_permission
      roles.py                 # code-defined role -> permission mapping
      security.py              # scrypt passwords, session tokens, HMAC pseudonyms
      rate_limit.py            # Redis login rate limit
      request_context.py       # validated client IP / user agent
      identifiers.py           # email and Rwandan phone normalisation
    db/
      session.py               # sync SQLAlchemy engine + get_db
      transaction.py           # atomic(): single commit point with the audit record
      base.py                  # declarative base and naming convention
    api/v1/
      router.py                # mounts every endpoint router under /api/v1
      responses.py             # shared OpenAPI error declarations
      endpoints/<module>.py    # routers only
    schemas/<module>.py        # Pydantic request/response models
    models/<area>.py           # SQLAlchemy tables
    repositories/<module>.py   # queries; flush only, never commit
    services/<module>.py       # business rules, transactions
    integrations/
      payments/                # provider interface + momo, airtel, card, cod, mock
      notifications/           # provider interface + mock
  tests/                       # pytest: unit/, integration/ (per-test schema), postgres/ (real HTTP)
scripts/                       # operator scripts (bootstrap_admin, provision_runtime_role, expiry job, seed)
```

- **Layers:** router → service → repository → SQLAlchemy models. Routers stay thin; business rules live only in services.
- **Validation:** Pydantic schemas for every request body, query and path parameter, and `response_model` on every endpoint so internal fields never leak.
- **Dependencies:** `get_db` for the session, `get_current_user` for authenticated callers, `require_permission(Permission.X)` on every staff endpoint. Permissions come only from `app/core/roles.py`.
- **URLs:** everything under `/api/v1`. Public resources by name (`/catalog/...`, `/delivery/...`, `/cart`, `/checkout`), the caller's own data under `/customers/me/...`, staff features under `/staff/...` (existing exceptions: `/inventory`, `/audit-logs`).
- **Responses:** success responses are plain bodies; every paginated list is `{ items, total, page, size }`. Every error is `{ error: { code, message, details } }`, produced by the handlers in `app/main.py` from `AppError` subclasses (`NotFound`, `Forbidden`, `Conflict`, ...) in `app/core`.
- **Database access:** synchronous SQLAlchemy 2.0 with psycopg 3; schema changes only through Alembic migrations.
- **Money:** whole RWF as integers (`BIGINT`), all totals calculated on the server, never trusted from the client (ADR-007).
- **Transactions:** any change touching stock, orders or payments runs inside `atomic(db)` together with its audit record, with `with_for_update()` on stock rows (inventory rows locked in variant-ID order).
- **Background work:** FastAPI `BackgroundTasks` for notifications after commit; operator jobs run by cron (e.g. `scripts/expire_reservations.py`) for expiring unpaid orders.
- **Config:** secrets only in environment variables; `.env.example` lists every key with placeholders.

## Platform modules (1–4)

These give every later module a database, logged-in users, roles and an audit trail.

| Module | Method & path | Access | Purpose |
| --- | --- | --- | --- |
| core | GET /health | Public | Uptime and DB check |
| auth | POST /auth/register | Public | Create customer (email or phone + password) |
| auth | POST /auth/login | Public | Return a session token |
| auth | POST /auth/logout | Customer, staff | Revoke the session |
| auth | GET /auth/me | Customer, staff | Current identity |
| auth | POST /auth/forgot-password, /auth/reset-password | Public | Reset by email/SMS code |
| users | GET, PATCH /customers/me | Customer | View and edit own profile |
| users | GET, POST, PUT, DELETE /customers/me/addresses, POST /customers/me/addresses/:id/default | Customer | Saved addresses |
| users | GET /staff/me, /staff/me/permissions | Staff | Own staff identity and permissions |
| users | GET, POST /staff; GET, PATCH /staff/:id; PATCH /staff/:id/role, /staff/:id/status | Admin | Create staff, set role, deactivate |
| audit | GET /audit-logs | Admin | Filter by action, status, actor, entity, date |

Rules:

- Passwords hashed with scrypt; login rate-limited (ADR-006).
- Roles: `customer`, `administrator`, `sales`, `operations`, `management`. Access is checked with `require_permission(...)` on every staff route; the role → permission matrix is in `app/core/roles.py` and `docs/IMPLEMENTATION_PLAN.md`.
- Audit records product price/stock edits, order status changes, refunds and role changes.

## Catalogue modules (5–9)

These let staff load the catalogue and let customers browse and search it.

| Module | Method & path | Access | Purpose |
| --- | --- | --- | --- |
| categories & brands | GET /catalog/categories, /catalog/brands | Public | Tree of categories, brand list with counts |
| categories & brands | POST, PATCH, DELETE /staff/categories, /staff/brands | Admin, sales | Manage taxonomy |
| products | GET /catalog/products/:slug | Public | Product detail with variants, specs, stock status |
| products | POST, PATCH /staff/products | Admin, sales | Create/edit product, hide/show |
| products | POST, PATCH, DELETE /staff/products/:id/variants | Admin, sales | Colour/storage/RAM variants with price |
| media | POST /staff/products/:id/images | Admin, sales | Upload, resize, store, return URL |
| media | PATCH, DELETE /staff/images/:id | Admin, sales | Reorder or remove |
| import | POST /staff/imports | Admin, sales | Upload CSV/XLSX, validate, create job |
| import | GET /staff/imports/:id | Admin, sales | Job status, imported count, row/field errors |
| import | GET /staff/imports/template | Admin, sales | Download the template file |
| search | GET /catalog/products?category=&brand=&min\_price=&max\_price=&in\_stock=&sort\_by=&sort\_direction=&q=&page=&size= | Public | Listing, filters, sort, search, pagination |

Rules:

- Slugs are unique and generated from the name; only `active` products appear publicly.
- Import validates every row first, imports valid rows, and reports invalid ones by row number and field (TC-15).
- Start search with PostgreSQL full-text search on name, brand and model; a separate search engine is not needed for 100–200 products.
- Public product responses show stock status (`in_stock`, `low_stock`, `out_of_stock`), never exact quantities, cost price or internal notes.

## Commerce modules (10–15)

This is the purchase path; every rule here maps to a launch-blocking test.

| Module | Method & path | Access | Purpose |
| --- | --- | --- | --- |
| inventory | GET /inventory?low\_stock=true, GET /inventory/:sku | Admin, sales, ops | Stock list and low-stock items |
| inventory | POST /inventory/:sku/adjustments | Admin, sales | Manual adjustment with reason |
| cart | GET /cart | Guest (cart token), customer | Cart with server-calculated totals |
| cart | POST /cart/items, PATCH/DELETE /cart/items/:id | Guest, customer | Add, change quantity, remove |
| cart | POST /cart/merge | Customer | Merge guest cart after login |
| delivery | GET /delivery/zones | Public | Zones, fees and free-delivery threshold for checkout |
| delivery | POST, PATCH /staff/delivery/zones; PATCH /staff/settings (threshold) | Admin (management: view) | Manage zones, fees and threshold |
| promotions | POST /cart/apply-code, DELETE /cart/code | Guest, customer | Validate and apply or remove a discount code |
| promotions | GET, POST, PATCH /staff/promotions | Admin (management: view) | Create, edit, disable codes |
| orders | POST /checkout | Guest, customer | Create order from cart, reserve stock, return payment options |
| orders | GET /customers/me/orders, /customers/me/orders/:id | Customer (own) | History and tracking |
| orders | POST /orders/lookup | Guest (order number + phone) | Tracking |
| orders | GET /staff/orders | Admin, sales, ops | Filter by status, date, payment |
| orders | PATCH /staff/orders/:id/status | Admin, ops | Move to next allowed state; `cancelled` releases stock |
| orders | PATCH /staff/orders/:id/assignment | Admin, ops | Assign fulfilment to a staff member |
| payments | POST /payments/:orderNumber/initiate | Guest, customer | Start MoMo/Airtel push or card redirect |
| payments | GET /payments/:orderNumber/status | Guest, customer | Poll result after mobile prompt |
| payments | POST /webhooks/:provider | Provider only | Callback: verify, record, update order |
| payments | GET /staff/payments | Admin, management | Reconciliation: reference, amount, status |

Rules:

1. Checkout recalculates every price, discount and delivery fee on the server, then creates the order and reserves stock in one transaction with `SELECT … FOR UPDATE` on inventory rows (TC-13).
2. Order states are a fixed transition map in `services/order_service.py` (`received → confirmed|cancelled`, `confirmed → processing|cancelled`, `processing → dispatched|cancelled`, `dispatched → delivered`); any other move returns 409 Conflict.
3. Payment providers implement one interface: `initiate(order)`, `verify_webhook(request)`, `parse_event(request)`, `check_status(ref)`. A `mock` provider lets you build before sandbox access arrives.
4. Webhooks: verify signature → store the event (digest and sanitised metadata) → skip if `provider_ref` already processed → update payment and order in one transaction → return 200 quickly (TC-11).
5. Unpaid mobile-money orders expire after the agreed timeout; a scheduled job releases their stock and their discount code.
6. Payment state is kept separate from order state. A COD order starts as `received` with a `pending` cash-on-delivery payment attempt; it is never marked paid at order time (TC-12).

## Operations modules (16–19)

These let staff run the store without developers: paperwork, messages, reports and content.

| Module | Method & path | Access | Purpose |
| --- | --- | --- | --- |
| invoices | GET /customers/me/orders/:id/invoice, GET /staff/orders/:id/invoice | Customer (own), staff | Invoice PDF with finance-approved tax display |
| invoices | GET /staff/orders/:id/delivery-note | Admin, ops | Delivery note PDF |
| notifications | (internal) `notify(event, order)` | Called by orders/payments | SMS/email on confirmed, dispatched, delivered, cancelled |
| notifications | GET /staff/notifications, POST /staff/notifications/:id/retry | Admin | Sent/failed log, retry |
| reports | GET /staff/reports/sales?from=&to=&group\_by=day or week | Admin, management | Sales totals and order counts |
| reports | GET /staff/reports/top-products, /staff/reports/stock | Admin, management | Bestsellers and stock levels |
| reports | GET /staff/reports/:type/export | Admin, management | Same data as Excel |
| settings & content | GET /settings, /pages/:slug | Public | Store contact, WhatsApp number, policy pages (EN/RW) |
| settings & content | PATCH /staff/settings, PUT /staff/pages/:slug | Admin | Edit settings and policy text |

Rules:

- Notifications run after the order transaction commits, are retried on failure and never block checkout.
- Invoice numbering is sequential and never reused; prices are VAT-inclusive and invoices show 18% VAT as an extracted component (ADR-007), with no EBM claim until verified.
- Reports count only paid or COD-delivered orders, so totals match finance (UAT scenario 7).

## Module done checklist

A module is finished only when every box is ticked; then the next module in the map starts.

- [ ] SQLAlchemy models and Alembic migration added; seed data for local testing
- [ ] Pydantic schemas for every request and response
- [ ] Router and service written; business rules only in the service
- [ ] Permission checks on every staff endpoint, checked with a forbidden-role test
- [ ] pytest unit tests for service rules; integration test for the main endpoint
- [ ] Errors use the standard error shape; nothing sensitive in logs
- [ ] Endpoints correct in FastAPI's auto-generated /docs (OpenAPI), with examples
- [ ] Pull request reviewed, CI green, deployed to staging
- [ ] Linked TC tests run and recorded in the QA checklist

## Deviations

Differences from the first version of this plan, kept on purpose (owner decision, 2026-10-23):

| Topic | First plan | Code and this document | Why |
| --- | --- | --- | --- |
| Layout | `app/modules/<name>/{router,schemas,models,service}.py` | Layered: `api/v1/endpoints`, `schemas`, `models`, `repositories`, `services` | Existing code and tests use it |
| Database access | Async SQLAlchemy + asyncpg, `async with session.begin()` | Sync SQLAlchemy + psycopg 3, `atomic(db)` | Existing code; concurrency is handled by row/advisory locks |
| Auth tokens | JWT access + refresh tokens (`refresh_tokens`) | Opaque database sessions (`user_sessions`), 7 days, no refresh endpoint | ADR-006 |
| Password hashing | bcrypt or argon2 | scrypt | ADR-006 |
| Roles | `customer`, `sales`, `operations`, `admin` (+ `finance`); `require_role(...)` | `customer`, `administrator`, `sales`, `operations`, `management`; no finance role (management views payments and reports, only administrators change payment data); `require_permission(...)` | ADR-006; owner decision |
| Delivery admin | Admin, ops | Administrators edit; management views | RE-026 B6 |
| URLs | `/admin/...`, `/me`, `/products`, `/orders` | `/staff/...`, `/customers/me`, `/catalog/...`, existing `/inventory` and `/audit-logs` | Existing code |
| Success responses | `{ data, meta }` | Plain bodies; paginated lists `{ items, total, page, size }` | Owner decision |
| Table names | `refresh_tokens`, `audit_log`, `promotions`, `promotion_usages`, `payments`, `stock_movements` only | `user_sessions`, `audit_records`, `discounts`, `discount_targets`, `discount_redemptions`, `payment_attempts`, plus `inventory_balances` and `stock_reservations` | Existing schema (ADR-002) |
| Money | Integers in RWF | Integers in RWF (`BIGINT`), after migrating the original `Numeric(14,2)` columns | ADR-007 |
| COD state | COD orders created as `payment_due` | Order `received` + pending COD payment attempt | Payment state separate from order state (ADR-002) |
| Order handling | Separate `POST /admin/orders/:id/cancel` | Cancellation is the `cancelled` transition of `PATCH /staff/orders/:id/status`; extra assignment endpoint | Existing code (PR #9); no separate cancel endpoint is proposed in `docs/IMPLEMENTATION_PLAN.md` (pending approval) |
| Public stock | "stock status" | `in_stock` / `low_stock` / `out_of_stock` only | Owner decision |
