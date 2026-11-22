# FurniHub — multi-vendor furniture marketplace
FurniHub (provisional name) is being built from a working single-store electronics platform, cloned from `tsonGroup/rwanda-electronics-ecommerce`. Currency: RWF. Languages: English and Kinyarwanda.

**Transformation in progress (SC-04, ADR-014).** The marketplace has customers, sellers (who apply, are approved and run their own store, products, stock and orders) and platform administrators. The work is done in approved phases; see the phase table in [ADR-014](docs/architecture/ADR-014-multi-vendor-marketplace.md). Commit `03bb5cc` is the unmodified electronics baseline. **Until those phases are done, the code still behaves as the single-vendor electronics store this README describes:** seller features, stores and the furniture catalogue do not exist yet.

The original requirement documents (electronics) and every approved scope change are listed in docs/requirements/README.md.

Quick links: [First-time setup](#first-time-setup) · [After pulling changes](#after-pulling-changes) · [Start the project](#start-the-project) · [Checks](#checks)

## Prerequisites
- Node.js 22.13+ (ESLint 10 requirement) and npm
- Python 3.12–3.14 and [uv](https://docs.astral.sh/uv/) (`python -m pip install uv` if it is missing)
- Docker Desktop with Linux containers running

Commands below are PowerShell and start at the repository root unless a step says otherwise. If `uv` is not on PATH, use `backend\.venv\Scripts\uv.exe` (from root) or `.venv\Scripts\uv.exe` (from backend) instead.

## First-time setup
Do this once after cloning.

**1. Create your local settings files** by copying the examples. They are git-ignored; never commit them:
```powershell
Copy-Item .env.example .env
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env.local
```
Open each new file and replace every `REPLACE_WITH_...` placeholder. The comments in each `.env.example` explain every setting: which passwords must match between the root `.env` and `backend/.env`, which port to change if yours is taken, and how to generate the secret key. Never put real values in README, code or `.env.example`.

**2. Install dependencies:**
```powershell
cd backend;  uv sync --frozen;  cd ..
cd frontend; npm ci;            cd ..
```

**3. Start PostgreSQL and Redis, then create the database tables:**
```powershell
docker compose up -d --wait db redis
cd backend
uv run alembic upgrade head
```

**4. Create the app's least-privilege database account** (still in `backend`). `--dotenv` makes the script read `backend/.env`, so there is nothing else to type:
```powershell
uv run python ../scripts/provision_runtime_role.py --dotenv
```

**5. Create the first administrator** (still in `backend`). It asks for the password twice at a hidden prompt; the password needs 8+ characters with upper and lower case and a digit or symbol:
```powershell
uv run python ../scripts/bootstrap_admin.py --email admin@example.rw --full-name "First Admin"
```
You can use `--phone 0788123456` instead of, or as well as, `--email`. Success prints `Administrator created: <id>`. See [Staff accounts](#staff-accounts) for what happens next.

Then [start the project](#start-the-project).

## After pulling changes
Run these whenever you pull, from the repository root:
```powershell
docker compose up -d --wait db redis
cd backend
uv sync --frozen                  # new or updated Python packages
uv run alembic upgrade head       # new database migrations
uv run alembic current            # must end with "(head)"
cd ..\frontend
npm ci                            # new or updated npm packages
cd ..
```
Also check what changed in the pull:
- **An `.env.example` file changed** (root, `backend` or `frontend`): copy the new or changed settings from it into your own `.env` / `.env.local` and fill in the values.
- **`scripts/provision_runtime_role.py` changed** (new database permissions for the app): from `backend`, run `uv run python ../scripts/provision_runtime_role.py --dotenv` again. The app may return errors until you do.
- **A migration fails with a message about existing data** (for example a user holding more than one staff role): fix the data as the message says, then run `uv run alembic upgrade head` again.

## Start the project
Use separate terminals:
1. Root: `docker compose up -d --wait db redis` (if not already running)
2. Backend: `cd backend`, then `uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log`
3. Frontend: `cd frontend`, then `npm run dev -- --hostname localhost --port 3000`

| What | URL |
| --- | --- |
| Frontend | http://localhost:3000 (public admin placeholder: http://localhost:3000/admin) |
| API docs (Swagger) | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |

Redis is required: login returns 503 if it is not running. The development homepage requests health directly from the browser and reports failures; it is excluded from production UI. Health checks the process and the database (`SELECT 1`, 2-second limit) and returns 503 `database_unavailable` when PostgreSQL is unreachable.

Stop services with `docker compose stop db redis`. Database data persists in the named volume; do not remove the volume unless you intend to destroy local data.

## Checks
Run before opening a pull request.

From backend:
- `uv run ruff check . ../scripts`
- `uv run ruff format --check . ../scripts`
- `uv run pytest -q --ignore=tests/postgres` (unit and integration tests)
- `uv run pytest -q tests/postgres` (real HTTP against PostgreSQL and Redis)
- `uv run alembic heads` and `uv run alembic current` (requires running PostgreSQL)
- `uv run python ../scripts/check_database.py` (requires running PostgreSQL)

Database tests use a **separate, disposable** database named `rwanda_ecommerce_test`, never your development data:
1. Create it once: `docker compose exec db createdb -U <owner user from your root .env> rwanda_ecommerce_test`
2. Copy the "Tests only" lines from `backend/.env.example` into your `backend/.env`, uncomment them and fill in the values. Tests read them from there.

The `tests/postgres` suite drops and rebuilds that database's `public` schema and flushes its Redis test database. Without the test settings, database tests are skipped or fail with a clear message.

Optional smoke checks (`uv run python ../scripts/verify_postgres_live.py`) need their own disposable database, never your development one. Copy the "Smoke checks only" lines from `backend/.env.example` into your shell or `backend/.env` and fill them in. The script refuses to run unless the target is confirmed as disposable. It uses random passwords on every run and deletes only the accounts it created.

From frontend:
- `npm run lint`
- `npm run typecheck`
- `npm run build`

From root: `git check-ignore .env backend/.env frontend/.env.local` (all three must be listed).

## Configuration
All settings live in the git-ignored `.env` files, documented by the comments in the matching `.env.example` (root: Docker; `backend`: API, database, Redis, secrets, tests; `frontend`: public API URL). The backend reads `backend/.env` through Pydantic Settings, and shell environment overrides it. The API connects with a least-privilege database account; the schema-owner account is used only by Alembic and the operator scripts. No application SQL or credentials are logged; use Uvicorn `--no-access-log` to avoid query-string logging. The frontend's public API URL is exposed to the browser, so changing it requires restarting development or rebuilding production.
PostgreSQL 18 is configured with persistent storage at /var/lib/postgresql, localhost binding and pg_isready health checks. The image major tag receives patch updates; hosted image digest/version pinning is a release decision.
Staging/production templates live in infrastructure/. They require distinct databases, origins, credentials and approved hosting; see docs/deployment/README.md. Each environment runs the same order once: `alembic upgrade head`, `provision_runtime_role.py`, `bootstrap_admin.py`.

## Staff accounts
Staff and customers share one login (`POST /api/v1/auth/login`). SC-05 (2026-11-21): the only staff role is the **Marketplace Administrator** (stored as `administrator`), which holds every permission in `backend/app/core/roles.py`. Each staff route still requires its own fine-grained permission (for example `catalog:manage`, `orders:fulfil`, `sellers:manage`; table in `docs/IMPLEMENTATION_PLAN.md` §3), so adding a role later needs no route changes. Sellers are store owners, not staff, and hold no staff permission (ADR-014).

Administrators create, edit, disable and re-enable other administrators under `/api/v1/staff`; disabling revokes all of that user's sessions, and the last active administrator cannot be disabled. Public registration never creates staff.

**First administrator:** `scripts/bootstrap_admin.py` (first-time setup, step 5). It refuses while an active administrator exists (`Refused: An active administrator already exists`). In that case, log in as the existing administrator and create staff with `POST /api/v1/staff`. If every administrator has been disabled, the script can be run again to recover access. For automation, `--password-stdin` reads the password as one line from stdin; it is never accepted as an argument.

**Try it in Swagger:** open http://localhost:8000/docs, call `POST /api/v1/auth/login` with the administrator's email and password, copy `session_token`, click **Authorize** and paste it, then call `GET /api/v1/staff/me`.

For the complete route-by-route inventory, including authentication and authorization, implementation status, source files, test references, and known API gaps, see [API endpoint inventory](docs/api/endpoint-inventory.md). The inventory reflects routes registered in the current backend source; Swagger/OpenAPI is generated at `/api/v1/openapi.json`.

## Marketplace sellers (ADR-014)
A signed-in customer with a verified email applies with `POST /api/v1/seller/application`; the store starts `pending`. Administrators approve, reject (with a reason), suspend (with a reason) and reinstate it under `/api/v1/staff/sellers`, and may override its commission (whole basis points; unset inherits `marketplace.default_commission_bps`, 1,000 = 10% while unset). Every submission and decision is kept in the store's status history, audited, and emailed to the owner's verified account email. Seller routes (`/api/v1/seller/store`, and more in later phases) need an approved store, checked on every request, so a suspension applies at once. One store per account, store names unique regardless of letter case. Routes: [API endpoint inventory](docs/api/endpoint-inventory.md#marketplace-sellers-adr-014-phase-1).

**Store catalogues (ADR-014 phase 2).** Every product belongs to a store (`products.store_id`, migration `b2d4f6a8c0e1`). Approved sellers manage their own products, variants, images and stock under `/api/v1/seller/products`, `/api/v1/seller/images` and `/api/v1/seller/inventory`, and their logo and cover under `/api/v1/seller/store/logo` and `/cover`; another store's resources answer 404. Administrators moderate products of every store (view, edit, hide, archive, feature) but do not create them: `POST /api/v1/staff/products` answers 409 and the catalogue import refuses rows for unknown products (SC-05). Only products of approved stores are public or sellable; product responses name their store, `GET /api/v1/catalog/products?store=<slug>` lists one store, and `GET /api/v1/stores` and `/stores/{slug}` show approved stores. Routes: [API endpoint inventory](docs/api/endpoint-inventory.md#marketplace-seller-catalogue-and-stores-adr-014-phase-2).

**Seller orders (ADR-014 phase 3).** A checkout still makes one order and one payment, split into one seller order per store (migration `c6e8a0b2d4f7`) with the store's commission snapshot (charged on its merchandise after its share of any discount). Each store's seller confirms, processes, dispatches and delivers its own part under `/api/v1/seller/orders`; the order's status follows the stores, each store's stock leaves inventory when it dispatches, and a cash-on-delivery payment is recorded when the last store delivers. Administrators see every store's part read-only and can only cancel an order; earnings are at `/api/v1/seller/earnings` (payouts are not built). The development seed moves its orders as the stores' owners. Routes: [API endpoint inventory](docs/api/endpoint-inventory.md#marketplace-seller-orders-and-earnings-adr-014-phase-3).

**Seller dashboard (ADR-014 phase 4).** Customers apply to sell, and follow or resubmit their application, at `/account/seller` ("Sell with us" in the Account menu). The owner of an approved store manages it at http://localhost:3000/seller: dashboard and earnings, orders (one step at a time), products, inventory and the store profile. The dashboard reuses the admin's frame and its product, editor and stock screens, pointed at the seller's own `/api/v1/seller/*` routes. The layout checks the session on the server: staff accounts, customers without a store and stores that are not approved see a notice instead. Its language is chosen in its top bar like the admin's. Details: ADR-014 "Phase 4 as built".

## Public catalogue API
Read-only catalogue endpoints are available under `/api/v1/catalog`: `GET /categories`, `GET /brands`, `GET /products`, and `GET /products/{slug}`. Product listing accepts `page` (default 1), `size` (default 20, maximum 100), `category` and `brand` slugs, `q` (PostgreSQL full-text search in product name, model and brand name, module 9: every word matches as a prefix, so `iph` finds iPhone and `gx-1`, `gx10` or `GX 10` find model GX-10; web-search syntax `"phrase"`, `or` and `-word` is supported; input without letters or digits matches nothing), inclusive `min_price` and `max_price` (whole RWF integers), `in_stock` and `featured`. `sort_by` is `name`, `price` (lowest active variant price; products without an active variant last), `newest` (creation time) or `bestselling` (units in orders delivered in the last 90 days; ties go featured first, then newest); `sort_direction` is `asc` or `desc` and defaults to `asc` for name and price and `desc` for newest and bestselling. Without `sort_by`, a search is ordered by relevance (best match first, then name) and a listing by name. Product ID is always the ascending tie-breaker. The search uses `products.search_vector`, kept current by database triggers (also on brand renames) and a GIN index (migration `a3b4d2f1d8e6`). `in_stock=true` requires at least one matching active variant with available inventory; `false` requires that none of the matching active variants have available inventory. Results omit products whose status is not active, whose category is inactive, or whose assigned brand is inactive; inactive variants are omitted. Availability is `max(on_hand - unavailable_quantity - active_or_committed_reservations, 0)`, and missing inventory records report zero. Prices are returned as whole-RWF JSON integers (VAT-inclusive) with currency `RWF`. Empty results return HTTP 200 with `items: []` and `total: 0`. Every image is `{url, width, height, alt, position}` (ADR-009): `url` is the public source in its original format, and resizing for display happens at delivery (the Next.js image optimizer). Products have `images`, categories an `image` and brands a `logo`. With `APP_ENV=development` the API serves public images itself at `/media`; exact originals are kept privately and never served. Storage settings are in `backend/.env.example`. Serving images on staging or production is not configured yet (ADR-004); what a host must provide is in `docs/deployment/media.md`.

**Background worker** (ADR-010). Run it next to the API, in a second terminal, from `backend/`: `uv run python -m app.worker` (Ctrl+C stops it; `--once` runs one pass). It processes queued jobs (bulk image upload), deletes image files the API has retired (replaced or deleted images), sweeps files of failed uploads, marks catalogue imports left unfinished by a stopped API process as failed, and logs weekly how many stored files have no registry row (`uv run python -m app.worker reconcile` lists them; nothing is deleted). Without it the API still works, but jobs wait and retired files stay on disk.

**Development catalogue** (checkpoint 2). With the API database migrated, the runtime role provisioned, `seed_dev.py` run and the worker running, from `backend/`: `uv run python ../scripts/seed_development_catalogue.py --confirm` loads categories, brands, three approved demo seller stores, about 40 products with images (shared out over those stores and created by their owners), homepage banners, the seed administrator, five customers and 15 orders, all through the real services (rerunnable; it only adds what is missing). `--cleanup --confirm` removes it again (categories and brands stay). Both refuse unless `APP_ENV=development` and the database is local. Product photos named `<slug>.jpg` or `<slug>__2.jpg` in `backend/seed/photos/` replace the generated placeholders. Passwords: see `backend/.env.example`; otherwise they are printed once.

**Upgrading a development database with images from before 2026-10-26:** the media registry migration refuses while such images exist. From `backend/`, run `uv run python ../scripts/reset_dev_images.py --confirm` (development and a local database only; it deletes image rows and image files, nothing else), then `uv run alembic upgrade head`, `uv run python ../scripts/provision_runtime_role.py`, and re-seed.

## Inventory
Stock rules follow the approved lifecycle in docs/architecture/ADR-002-database-schema-and-inventory-policy.md: holds are reserved at order creation (all lines or none), committed on payment success, released on cancellation or payment failure, and expired by a job. Committed stock is never released automatically.
- `GET /api/v1/inventory?low_stock=&q=&page=&size=` (module 10: one row per SKU with on-hand, unavailable, reserved, committed and available units, low-stock threshold and `is_low_stock`; `low_stock=true` is the low-stock alert: available at or below a threshold above 0), `GET /api/v1/inventory/{sku}` (`inventory:read`: administrator) and `POST /api/v1/inventory/{sku}/adjustments` (`inventory:adjust`: administrator). The list and the single-SKU read use one stock calculation. The POST requires an `Idempotency-Key` header; retrying with the same key never applies a change twice.
- Reserve, commit and release are internal services for the future checkout and payment features. They have no HTTP endpoints.
- **Expiry job:** from `backend`, `uv run python ../scripts/expire_reservations.py`. Schedule it (for example every minute) in each environment. It is safe to run several copies at once or to rerun it.

## Notifications (module 17)
An order moving to confirmed, dispatched, delivered or cancelled gets one SMS (or email when the order has no usable phone), recorded with the order change and sent after it commits. Providers are a mock (delivers nothing), the development console or, for development and staging tests, SMTP email (for example a Gmail app password; orders then notify by email only) until ADR-005 chooses a production SMS/email provider (§7 Q22). The Render test deployment may temporarily use Gmail with `TEMPORARY_GMAIL_SMTP_ENABLED=true` until Resend replaces it (`docs/deployment/README.md`); `NOTIFICATION_PROVIDER` and `SMTP_*` in `backend/.env.example`. Administrators see the log at `GET /api/v1/staff/notifications` and retry at `POST /api/v1/staff/notifications/{id}/retry`.
- **Retry job:** from `backend`, `uv run python ../scripts/retry_notifications.py`. Schedule it (for example every minute) in each environment where notifications are on: it sends notifications the API did not send (including the expiry job's cancellations) and retries failures (at most 3 attempts). Several copies may run at once. Details: `docs/qa/module-17-notifications-acceptance.md`.

## Reports (module 18)
Staff with `reports:read` (administrator) read `GET /api/v1/staff/reports/sales?from=&to=&group_by=day|week`, `/top-products?from=&to=&limit=` and `/stock`, and download each as Excel from `/staff/reports/{sales|top-products|stock}/export` with the same parameters. Sales count only paid orders and delivered cash-on-delivery orders (orders with a succeeded payment), each once, in Africa/Kigali days with weeks from Monday; amounts are whole RWF. The sale date, the top-products ranking and limit, the range limit and the empty-period presentation are engineering defaults awaiting approval (R-1 to R-4); the exported columns need the product owner's sign-off as the approved data for export (R-7); whether exports should be audited is an open policy choice for the security owner (R-6). See docs/qa/module-18-reports-acceptance.md.

## Settings and content pages (module 19)
`GET /api/v1/settings` (public) shows the store's name, contact details (phone, WhatsApp number, email, address, opening hours) and the announcement bar while it is switched on; each is null until an administrator sets it with `PATCH /api/v1/staff/settings` (`settings:manage`). The six policy pages are read at `GET /api/v1/pages/{slug}?lang=en|rw` (published only; a missing translation is 404, never another language), listed at `GET /api/v1/staff/pages` and written at `PUT /api/v1/staff/pages/{slug}?lang=en|rw` (`content:manage`: administrator). Bodies are Markdown, rendered and sanitised by the frontend. Business quote requests from the Contact page are sent to `POST /api/v1/quote-requests` and followed up at `/api/v1/staff/quote-requests` (`quotes:manage`: administrator). The development seed adds draft pages and sample contact details; production has no page text until the business approves it (PR-15, TC-20). Details: `docs/IMPLEMENTATION_PLAN.md`, module 19.

## Architecture and roadmap
Read AGENTS.md and docs/architecture/ADR-001-nextjs-fastapi-postgresql.md. Authentication and staff decisions are in docs/architecture/ADR-006-authentication-security-controls.md.
Commerce models and Alembic revisions provide the current catalogue, inventory, cart, order, and payment schema foundation. The public catalogue APIs are read-only; staff catalogue management (modules 5–8), the staff stock list and adjustments, the reservation services and the cart (module 11) exist; checkout, payment integration and customer order creation/history remain unimplemented.

Cart (module 11): `GET /api/v1/cart`, `POST /api/v1/cart/items`, `PATCH|DELETE /api/v1/cart/items/{item_id}` and `POST /api/v1/cart/merge`. A signed-in customer (bearer session) uses their one cart; staff accounts get 403. A guest's first `POST /cart/items` creates a cart and returns `cart_token` once; later requests send it in `X-Cart-Token`. Only its SHA-256 is stored, and a guest cart expires 30 days after its last change. Lines hold 1–99 units and never more than is available (409 `insufficient_stock`). Lines whose product is no longer sold, or that ask for more than is available, are flagged and left out of the totals. Totals come from the pricing service, never from the client. `zone` (a code from `GET /api/v1/delivery/zones`) adds the delivery quote and the grand total (module 12). Details: `docs/api/endpoint-inventory.md` and `docs/qa/module-11-cart-acceptance.md`.

Delivery (module 12): `GET /api/v1/delivery/zones` (public) lists the active zones (Gasabo, Kicukiro, Nyarugenge) with their VAT-inclusive fee, cash-on-delivery availability and the free-delivery threshold. Staff manage zones at `/api/v1/staff/delivery/zones` and the threshold at `/api/v1/staff/settings`: administrators only (RE-026 B6; SC-05). A fee change keeps the fee history. Development placeholder values: `uv run python ../scripts/seed_dev.py` from `backend/` (refuses unless `APP_ENV=development`; threshold 50 000 RWF). Details: `docs/qa/module-12-delivery-acceptance.md`.

Promotions (module 13): customers apply one code per cart with `POST /api/v1/cart/apply-code` and remove it with `DELETE /api/v1/cart/code`; the cart shows the discount, the subtotal after discount (which drives free delivery) and each line's share. Staff manage codes at `/api/v1/staff/promotions`: administrators only (RE-026 B6; SC-05). Start and end dates are Africa/Kigali time (the `tzdata` package provides the zone on Windows). Refused codes are limited to 20 per 15 minutes per network and per cart (429 with `Retry-After`; ADR-008 S5), and a code's minimum compares the whole merchandise subtotal before discount. Uses are recorded at checkout (module 14). Details: `docs/qa/module-13-promotions-acceptance.md`. Order fulfilment status/assignment APIs are implemented as described below. Do not call create_all at startup.

## Payments (module 15)
`POST /api/v1/payments/{order_number}/initiate` and `GET /api/v1/payments/{order_number}/status` (the customer's own order, or a guest with the order's phone). Mobile money uses the **mock** provider until ADR-003 (§7 Q21): it moves no money; set `PAYMENT_MOCK_WEBHOOK_SECRET` (32+ characters, never in production) and send signed callbacks to `POST /api/v1/webhooks/mock`. Cash on delivery stays pending until delivery; card is disabled. Staff with `payments:read` see `/api/v1/staff/payments`. Details: `docs/qa/module-15-payments-acceptance.md`.

## Checkout (module 14)
`POST /api/v1/checkout` (with an `Idempotency-Key` header) turns the caller's cart into an order: prices, the promotion discount, the delivery fee and the VAT (18%, extracted) are all computed on the server, and stock is held (mobile money 15 minutes, cash on delivery 24 hours). Customers read their orders at `GET /api/v1/customers/me/orders`; guests look an order up with `POST /api/v1/orders/lookup` (order number + phone; failed lookups are limited to 5 per order number and 20 per IP per 15 minutes, ADR-008 S6). Staff with `orders:read` list and read orders at `/api/v1/staff/orders`. Payments are module 15. Details: `docs/qa/module-14-checkout-acceptance.md`.

## Order status and fulfilment API
Authenticated customers read an order they own, with its lines and totals, at `GET /api/v1/customers/me/orders/{order_id}`; another customer's order returns 404. `PATCH /api/v1/staff/orders/{order_id}/status` advances status, and `PATCH /api/v1/staff/orders/{order_id}/assignment` assigns an active staff account. Both staff actions require `orders:fulfil` (administrator). Status history and audit events are committed atomically with the order update. Dispatch also consumes committed stock; cancellation releases active holds. Committed (paid) stock is never released by cancellation (ADR-002), so cancelling such an order returns 409 until a compensating refund/cancellation workflow is approved.

The current centralized policy allows `received -> confirmed|cancelled`, `confirmed -> processing|cancelled`, `processing -> dispatched|cancelled`, and `dispatched -> delivered`; `delivered` and `cancelled` are terminal. PR-07 lists statuses but does not specify this transition graph, cancellation cutoff, or staff role split. These implementation rules are isolated for review and remain subject to Product Owner and Operations approval; the endpoints must not be treated as final business policy until that review is recorded. Assignment targets must be active staff with a repository-defined role; which roles may assign or receive orders remains to be approved.
Roadmap: https://trello.com/b/yjoXwPEK/rwanda-electronics-e-commerce-mvp-development-roadmap
The board was unavailable during setup; card IDs, current ordering and RE-002/RE-016 status have not been verified. Although this repository now contains the commerce schema and public read-only catalogue APIs, that is not evidence that the RE-018 prerequisites are cleared. Confirm prerequisite status and remaining acceptance criteria on the board before marking RE-018 ready. Payment implementation requires its design approval. No Trello cards were modified.
Delivery, discount and tax pricing (RE-026) is blocked; its blocker register and readiness checklist are in docs/architecture/RE-026-pricing-blockers-and-readiness.md.
Open decisions include brand/domain/catalogue, translation owner/default, delivery policy, VAT/invoice/EBM, hosting/backups, password recovery, session policy, payment gateway and notification provider.
See docs/deployment/verification.md for actual setup results and blockers.
