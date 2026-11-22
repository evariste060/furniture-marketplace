# ADR-014: Multi-vendor furniture marketplace

Status: **Accepted** by the project owner on 2026-11-21 (scope change SC-04). Trello card: none (no furniture board exists; card IDs are not invented). Scope: turning the single-store electronics platform into a multi-vendor furniture marketplace, provisionally named **FurniHub**. Baseline before any change: commit `03bb5cc`.

This ADR records the approved architecture. Each implementation phase (see "Phases") updates it with what was built, the migrations and the tests, and is reviewed by the owner before the next phase starts.

## Context

The codebase is a working single-vendor store: every product belongs to "the shop", staff are platform employees with one global role each (ADR-006), and checkout creates one `Order` with one payment (modules 14 and 15). Nothing in the schema records a product's owner, a store, or the seller of an order line. The marketplace has three actors: **customers** (unchanged), **sellers** (apply, are approved, run their own store, products, stock and orders) and **platform administrators and staff** (review sellers, moderate the catalogue, oversee orders). A seller is not a platform administrator, and no seller may read or change another seller's data.

## Decisions

1. **Sellers are store owners, not staff.** A seller stays a customer account (`users.is_staff` false, no `staff_role_assignments` row). Seller rights come only from owning a store whose status is `approved`. The global staff permission matrix (`app/core/roles.py`) is not used for sellers: seller access is *scoped to one store*, global permissions are not.
2. **`stores` table** (one store per user, `owner_user_id` unique): name, unique slug, description, logo and cover image in the media registry (ADR-009, like category images), contact email and Rwandan phone (canonical `+2507XXXXXXXX`), district, sector and street, `status`, `rejection_reason`, `reviewed_by_user_id`, `reviewed_at`, and an optional `commission_rate_bps` that falls back to a platform setting.
3. **Application lifecycle.** Statuses `pending`, `approved`, `rejected`, `suspended`. A signed-in customer with a verified email applies (creates the store as `pending`); a rejected applicant edits and resubmits (back to `pending`); administrators approve, reject (reason required), suspend and reinstate. Every decision is audited (`AuditService`) and the applicant is emailed through the notification outbox (module 17). The application *is* the store row; history lives in the audit trail, not a separate table.
4. **Seller authorization.** A new dependency `require_approved_seller` resolves the caller's store from the database on every request and refuses with 403 `seller_not_approved` unless it is `approved`, so a suspension applies immediately, as role changes do today. Seller routes live under `/api/v1/seller/*`, separate from `/api/v1/staff/*`. New staff permissions `sellers:read` and `sellers:manage` (administrator only unless the owner approves more) cover `/api/v1/staff/sellers`.
5. **Product ownership.** `products.store_id` (FK, NOT NULL after the development reseed). Variants, images and stock belong to a store through their product. The existing product, image and inventory services gain a **required** scope argument (a store, or "platform staff"); every seller query filters by `store_id`, and another store's resource answers **404** (not 403) so its existence is not revealed. `store_id`, `status` of the store, `is_featured` and merchandising fields are never accepted from seller request bodies.
6. **Staff role in the catalogue.** Staff manage and moderate: review, hide, archive and otherwise manage products according to their permissions. Sellers create and own products. Staff product creation on a seller's behalf is not built in V1; any existing workflow that depends on it (for example the staff catalogue import) is reported to the owner before it is changed.
7. **Public catalogue.** Only products of `approved` stores are listed or shown (suspending a store hides its products). New public `GET /stores` and `GET /stores/{slug}`, a `store` filter on product listing and search, and a store summary ("Sold by") in product responses.
8. **Orders: one parent order, one group per seller (option A).** Checkout stays one transaction and one payment. It additionally writes `order_items.store_id` with a store-name snapshot, and one `seller_orders` row per store in the order with that store's subtotal, discount (the sum of the existing per-line allocation), a commission-rate snapshot, the commission amount and the seller's net amount. Checkout, payment, idempotency, stock reservation and cancellation logic are kept as they are.
9. **Parent order lifecycle.** The parent `orders.status` keeps its existing machine and remains what the customer sees. Payment, the `received → confirmed` step (which commits stock and applies the cash-on-delivery rules) and whole-order cancellation stay at the parent. Each seller moves its own group through processing, dispatched and delivered; the parent becomes `dispatched` when every group is dispatched and `delivered` when every group is delivered, which keeps the existing cash-on-delivery "delivered marks the payment succeeded" and invoice rules on the parent. Exact rollup rules and their edge cases are specified and approved in phase 3 before they are built. *Amended by the owner on 2026-11-21 (see "Phase 3 as built"): sellers also confirm their own seller orders, so `received → confirmed` follows the stores and staff keep only whole-order cancellation.*
10. **Customer data shown to sellers.** For its own group only: the lines, the recipient's name, phone and delivery address, and the statuses. Not the customer's email, other sellers' lines or the order's total. Seller reads of order data are audited.
11. **Commission and earnings.** A rate in basis points (platform setting, optionally overridden per store) is snapshotted on each seller group at checkout and never taken from the client. Earnings summaries are computed from groups; **payouts are not built**.
12. **Invoices (configurable; not a verified legal or tax decision).** For the class-project V1 the platform remains the invoice issuer, using the issuer details already held in admin settings (`settings_service.seller_details`), and each line shows its store. The issuer choice is kept configurable so per-seller invoicing can replace it; this ADR does not claim the arrangement is legally or fiscally correct.
13. **Delivery.** The existing platform delivery fee by district (module 12) is kept for the whole order. Per-seller delivery fees are not built.
14. **Furniture domain.** Categories come from a furniture taxonomy loaded as data (no schema change). Product attributes stay in the existing `specifications` JSONB, guided by a code-defined attribute set per category (dimensions, material, color, style, finish, weight, condition, assembly required; warranty keeps its own field), so no attribute is forced on every product. Brands stay optional ("manufacturer").
15. **Repurposed features.** Technical services (ADR-013) are reused for furniture services (assembly, installation and related work) with the same tables, endpoints and UI. Quote requests (module 19) are reused for bulk furniture purchasing by offices, hotels, schools and other organizations, without widening the existing implementation.
16. **Branding.** The provisional name FurniHub is held in one place per layer (frontend configuration and messages, backend settings) so a later rename touches configuration, not components. English and Kinyarwanda messages change together.
17. **Development data.** The development catalogue is reseeded with furniture products across several demo stores, and the electronics demo data is removed by the existing development-only tooling, which refuses unless `APP_ENV=development` and the database is local. No production or staging data is touched, and no destructive database action runs without confirming the environment.

## Not built in V1

Seller payouts; partial cancellations or refunds by a seller; per-seller delivery fees; per-seller invoicing; seller-specific promotion codes; staff creating products for a seller.

## Phases

Each phase is implemented separately, runs the backend and frontend checks listed in the README, and is reported to the owner before the next begins.

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Baseline commit `03bb5cc`; this ADR, SC-04, AGENTS.md and README updates | Done (2026-11-21); approved |
| 1 | `stores`, seller application and admin review APIs, `require_approved_seller`, `sellers:*` permissions, runtime-role grants | Implemented (2026-11-21); see "Phase 1 as built" |
| 2 | `products.store_id`, store-scoped seller product, image and inventory APIs, approved-store catalogue filter, public store endpoints, cross-store isolation tests | Implemented (2026-11-21); see "Phase 2 as built" |
| 3 | `order_items.store_id`, `seller_orders`, checkout grouping, seller order API, parent status rollup, admin group view, commission and earnings | Built (2026-11-22, owner decisions 2026-11-21); see "Phase 3 as built" |
| 4 | Frontend: "Become a seller" and application status in Account; `/seller` dashboard reusing the admin shell and components | Built (2026-11-22); see "Phase 4 as built" |
| 5 | Frontend: `/store/[slug]`, "Sold by" on cards, product page and cart; admin Sellers page | Built (2026-11-22); see "Phase 5 as built" |
| 6 | Furniture taxonomy, attribute sets, filters, services and quotes adaptation, FurniHub branding (English and Kinyarwanda), furniture seed data | Built (2026-11-22); see "Phase 6 as built" |

## Staff roles: SC-05 (2026-11-21)

Between phases 1 and 2 the owner approved SC-05: the Marketplace Administrator (`administrator`) is the only staff role, holding every permission; sales, operations, management and finance are removed (migration `a9d3f5b7c1e2`, which refuses to run while another role is assigned and changes no account). Permissions and their per-route checks are unchanged. The phase 1 decision "only administrators hold `sellers:read` and `sellers:manage`" is now true of every staff permission. Staff product creation becomes moderation only, built in phase 2. Details: `docs/requirements/scope-changes.md`.

## Phase 1 as built (2026-11-21)

Owner decisions for phase 1 (2026-11-21): a verified account email is required to apply; only administrators hold `sellers:read` and `sellers:manage`; store names are unique regardless of letter case; the default commission is 1,000 basis points.

- **Migration `f4c8a2e6b9d3`** (after `e5a1c7d9b3f2`): `stores` and `store_status_history`; `media_objects.owner_type` also allows `stores`; `notification_logs` allows the five store events about a `store_status` subject, and `notification_logs.event` is widened from 24 to 32 characters (`store_application_received` has 26). It inserts no rows (no migration does; `test_migrations_have_no_sample_data.py`). The downgrade refuses while stores, store notifications or store media exist.
- **`stores`**: `owner_user_id` unique (`uq_stores_owner_user_id`, one store per user for life), slug unique and lower-case hyphenated, `uq_stores_name_lower` on `lower(name)`, canonical phone and lower-case email checks, `status_reason` present exactly while rejected or suspended, `reviewed_at` set once decided, `approved_at` set at the first approval and kept, commission 0–10,000 or NULL, logo and cover media pairs (uploads arrive in phase 2).
- **`store_status_history`** is append-only (the runtime role has SELECT and INSERT only): one row per submission, resubmission and decision, with the status, reason, store name at the time and actor. Each row is the subject of that event's email, so the outbox's `subject:id:event` deduplication never drops a second rejection, and a retry renders the decision it was recorded for, not the store's later name or reason.
- **Emails** go to the owner's verified account email, never the store's contact email (which nobody verified). They are in English, like the other transactional emails, and still carry the platform brand constant until phase 6.
- **Commission**: `app.services.store_service.effective_commission_bps` is the only place the rate is worked out (override, else `settings_service.default_commission_bps`: the setting, or 1,000 while unset or invalid). Strict integers end to end; a float, string or boolean is 422.
- **`require_approved_seller`** (`app/core/dependencies.py`) returns `SellerContext(user, store)`. It is marked so `tests/integration/test_seller_route_guards.py` can enumerate every `/seller/*` route: any route other than the three application routes without it fails the test, and no seller route may name a store in its path.
- Slugs follow the name until the first approval and are fixed afterwards. A slug collision between two concurrent applications is 409 `store_slug_conflict` (retry).

## Phase 2 as built (2026-11-21)

- **Migration `b2d4f6a8c0e1`** (after `a9d3f5b7c1e2`): `products.store_id` NOT NULL, foreign key to `stores` with `ON DELETE RESTRICT`, index `ix_products_store_status (store_id, status)`. The upgrade refuses while any product exists (it reports the count, changes nothing and never invents an owner); a development database is emptied with the development tooling first and reseeded after the upgrade. The downgrade drops the column. No grant changes: the runtime role already had `products` and `stores` access, and still cannot delete stores.
- **One scope, required everywhere.** `app/services/catalog_scope.py` defines `CatalogScope`: `platform()` for staff, `store(id)` for a seller, the id taken only from `require_approved_seller`. Every product, variant, image and stock function reachable by a seller takes it as a keyword argument without a default (product admin, image admin, inventory admin, bulk activate, the staff list and detail). Another store's product, variant, image or SKU is the same 404 as one that does not exist.
- **Seller routes** (`app/api/v1/endpoints/seller_catalog.py`, all behind `require_approved_seller`): `/seller/products` (list, detail, create, update), variants, images (upload, reorder, update, delete), `/seller/inventory` (list, figures, idempotent adjustments) and the store's logo and cover. Seller bodies are `extra="forbid"` and have no `store_id` or `is_featured`, so both are 422. The publication guard, slug and SKU rules are the staff ones (slugs and SKUs stay unique across the marketplace). Reservations, stock commitment and orders stay with the platform.
- **Staff moderation (SC-05).** `POST /staff/products` answers 409 `staff_product_creation_disabled` with an explanation and creates nothing. Staff list, read, edit, hide, archive, feature and bulk-activate products of every store; the staff list has a `store_id` filter and each row and detail names its store. The catalogue import updates existing products of any store and adds SKUs to them, but refuses (per row, on `product_slug`) a row whose product does not exist; the admin New product button and dashboard action are removed and `/admin/products/new` redirects to the product list.
- **Public catalogue.** `_base_public_products()` (the single public rule) and the sellable rule used by cart, pricing and checkout (`inventory.sellable_variants`, and the staff stock list's `is_sellable`) both require the product's store to be `approved`, so suspending a store hides its products and stops their sale at once. Product responses carry `store` (id, name, slug: "Sold by"); `GET /catalog/products` and `/facets` take `store=<slug>`. `GET /stores` and `GET /stores/{slug}` show approved stores only (district, description, logo, cover, public product count), never contact details, street address, owner, history or commission; any other store is 404.
- **Store images** reuse the category-image pattern (stage, then point and retire; the cleanup worker deletes replaced files), audited `store.logo_upload`, `store.cover_upload`, `store.logo_delete`, `store.cover_delete`, with the same 5 MB request limit as other image uploads. Their files are keyed `stores/<store id>/...` (the media key pattern and the `media_objects` owner check both allow `stores`).
- **Development data.** `scripts/seed_development_catalogue.py` creates three approved demo stores whose owners are verified seed customers, and shares the seed products out over them; each owner creates their products, variants and opening stock through the seller scope, and the administrator only features and activates them. Cleanup removes the seed stores and their history after their products. Furniture data replaces the electronics demo in phase 6.
- **Tests:** `tests/integration/test_seller_catalog_api.py` (both directions of the cross-store matrix for every seller catalogue route, refused fields, staff moderation and the 409, approved-store visibility, store images), the seller route guard test (every new `/seller/*` route is guarded), the import and product tests updated for moderation only, and `tests/postgres` for the migration and live OpenAPI.
- **Limits recorded for the owner:** a seller can re-activate a product an administrator hid (no moderation lock exists; it would be a new feature); a slug or SKU taken by another store answers 409 `slug_taken` or `sku_taken`, as before, which reveals only that the value is used.

## Phase 3 as built (owner decisions 2026-11-21)

The proposed design was put to the owner, who decided on 2026-11-21. Where the owner's decisions differ from the proposal or from decision 9 above, the owner's decisions apply. Requirement: PR-07 (order statuses). No Trello card exists for this work, so none is referenced.

### Owner decisions

1. **Stock leaves inventory when each store ships.** Checkout reserves stock as before. When a store dispatches its seller order, only that store's SKUs are issued: the ledger movement is written, `on_hand` drops and the holds become fulfilled. The other stores' stock stays held or committed until they dispatch, or until a valid cancellation or expiry. `dispatch_order_inventory(..., variant_ids=...)` issues one store's SKUs. It runs under the order's locks and is idempotent, keyed per order and SKU, so stock is never issued twice. The parent's move to `dispatched` repeats the check that every SKU was issued exactly once; it never issues anything itself.
2. **Seller-managed fulfilment. The Marketplace Administrator has no fulfilment controls.** Each store's seller moves only their own seller order, one step at a time: `pending → confirmed → processing → dispatched → delivered`. The parent's status is derived from its seller orders. `PATCH /staff/orders/{id}/status` now accepts only `cancelled` (whole-order cancellation stays with the platform); any other status answers 409 `order_status_follows_seller_orders`. This amends decision 9: `received → confirmed` is no longer an administrator step. The admin order page and drawer no longer offer "Mark as …" or the fulfilment assignment control; they show the stores' parts read-only.
3. **Cash on delivery is allowed for several stores.** There is one parent order and one payment attempt per checkout, and its method stays cash on delivery. A seller order never has a payment of its own. The payment is marked succeeded, and the invoice issued, only when the last store delivers (the existing Q14/Q19 rules on the parent). No store is assumed to have collected the whole amount. Payout and settlement are not built.
4. **Commission is calculated after discounts.** Each store's discount is the sum of its lines' existing allocation (`promotion_service.allocate`: whole RWF, deterministic, shares sum exactly to the order discount). Checkout verifies that the stores' discounts add up to the order's. Commission is `merchandise_total × rate / 10000`, rounded half up to whole RWF. The rate is the store's override, otherwise `marketplace.default_commission_bps`, read at checkout and stored on the seller order. Delivery fees are the platform's and never part of a seller order.

### Data (migration `c6e8a0b2d4f7`)

- **`seller_orders`**, one row per (order, store):
  - columns: status, `store_name_snapshot`, `subtotal`, `discount_total`, `merchandise_total`, `commission_rate_bps`, `commission_amount`, `seller_net_amount`, and `confirmed_at`, `dispatched_at`, `delivered_at`, `cancelled_at`;
  - unique `(order_id, store_id)`;
  - checks: valid status; amounts not negative and within the money cap; `merchandise_total = subtotal - discount_total`; `commission_amount + seller_net_amount = merchandise_total`; rate between 0 and 10000.
- **`seller_order_status_history`** is append-only.
- **`order_items`** gains `store_id` (FK RESTRICT) and `store_name_snapshot`, plus a deferred composite FK `(order_id, store_id) → seller_orders (order_id, store_id)`, so every line belongs to its store's seller order.
- **Migration refusals:**
  - the upgrade refuses while any order exists, because it never guesses a store or a commission for existing lines;
  - the downgrade refuses while any seller order exists.
- **Grants:** `seller_orders` SELECT, INSERT, UPDATE; history SELECT, INSERT; no DELETE.

### Seller moves and the derived parent status

Every move runs in one transaction under the order's locks, taken in the common order: advisory lock, order row, seller order row.

| Seller move | Precondition | Effect on the parent |
| --- | --- | --- |
| `pending → confirmed` | the order is `received`, and its payment is a pending cash-on-delivery attempt or a succeeded one | when **every** store has confirmed, the parent becomes `confirmed`. For cash on delivery this commits the whole order's stock, as an administrator's confirmation did. A hold that lapsed first is refused (409 `inventory_conflict`) and the change rolls back. |
| `confirmed → processing` | the parent is `confirmed` or `processing`; otherwise 409 `seller_order_awaiting_other_stores` | the first store to start processing moves the parent to `processing` |
| `processing → dispatched` | none | this store's SKUs are issued. When every store has dispatched, the parent becomes `dispatched` and the customer is told. |
| `dispatched → delivered` | none | when every store has delivered, the parent becomes `delivered`, with the cash-on-delivery payment, invoice and customer message rules unchanged |

- A failed parent step (inventory, payment rules, audit) rolls the seller's change back with it.
- A repeated or skipped step is 409 `invalid_transition`, and nothing changes.
- Sellers cannot cancel.
- When the parent is cancelled, every open seller order is cancelled in the same transaction, with the same reason. This happens on a staff cancellation, and on the expiry job's `payment_timeout`, which now covers a cash-on-delivery order where only some stores confirmed within the hold.
- The parent can still be cancelled only while its stock is on hold (ADR-002). Once it is confirmed, its stock is committed and cancellation stays 409.

### Who sees what

- **Seller** (`require_approved_seller`, own store only; another store's seller order is the same 404 as a missing one):
  - visibility: cash-on-delivery orders appear when placed (they are the store's to confirm); mobile-money orders appear only once paid;
  - shown: the store's own lines and amounts, the recipient's name and phone, the delivery address fields, the payment method and status, the store's history and the parent status;
  - never shown: the customer's email or account, other stores' lines, the order total, the delivery fee or zone fee, or the discount code;
  - every list and detail read is audited as `seller_order.read`.
- **Staff:** the order detail lists its seller orders (status, money, commission) read-only. The order list takes a `store_id` filter. `GET /staff/sellers/{store_id}/earnings` requires `sellers:read`.
- **Customer:** sees the parent status only, as before; each line now names its store ("Sold by").
- **Invoice:** each line names its store. The platform remains the issuer (decision 12).

### Earnings

`GET /seller/earnings` and the staff view are computed from seller orders and never stored:

- **pending:** confirmed, processing, dispatched, and delivered while the order's payment has not yet succeeded;
- **earned:** delivered, and the order's payment succeeded.

Unconfirmed and cancelled seller orders are in neither. Payouts are not built, so "earned" means owed by the platform, not paid.

### Not in this phase, and points for the owner

- **Not built:**
  - seller notifications of new orders: sellers must check `GET /seller/orders`, and a cash-on-delivery order not confirmed by every store within its 24-hour hold is cancelled;
  - seller order screens (phase 4);
  - per-store customer messages;
  - partial cancellation, refunds, payouts and per-store delivery fees.
- **Points for the owner:**
  - **Paid mobile-money orders that are never confirmed.** A paid mobile-money order whose store never confirms stays `received` with its stock committed. It cannot be cancelled, because no refund workflow is approved. This was already true when staff had to confirm it.
  - **Staff delivery note and fulfilment assignment.** `GET /staff/orders/{id}/delivery-note` and `PATCH /staff/orders/{id}/assignment` still exist in the API. They are platform-side fulfilment tools from the single-store design. Only the assignment control was removed from the admin page. Removing both, or moving the delivery note to sellers, needs the owner's decision.

## Phase 4 as built (2026-11-22)

Frontend only: no backend route, schema, migration or permission changed. Every screen calls the phase 1-3 seller routes, which resolve the caller's store on every request; the frontend only decides what to show.

### Account: "Sell with us" (`/account/seller`)

- A new Account menu item (side menu and the phone Account popup). It reads `GET /seller/application`; 404 means the customer has not applied.
- **No application, pending or rejected:** the application form (name, description, contact email and phone, district, sector, street). It is checked in the browser with the backend's rules (`features/seller/store-form.ts`), then sent with `POST /seller/application` (first time) or `PUT` (edit while pending, or resubmit after a rejection; every field is sent again). Only those fields are sent: never an owner, status, slug or commission.
- **Status card:** under review, approved, needs changes or suspended, with the administrator's reason while rejected or suspended. An approved store links to `/seller` (a full page load: the dashboard is outside the locale routing); approved and suspended stores have no form (the backend answers 409 `store_application_closed`).
- **Errors:** `email_verification_required` shows a "verify your email" notice with the existing resend-link form; `store_name_taken` marks the name; `store_exists` and `store_application_closed` reload the status.

### The seller dashboard (`/seller`)

- **Where it lives:** outside the storefront's `[locale]` routing, like `/admin` (the locale middleware skips `/seller`). Its language is chosen in its top bar and kept in the same `admin_locale` cookie under `Path=/seller`, so the two panels never share a choice. Its messages are `admin.seller.*` in `messages/admin.json` and `admin.rw.json` (the Kinyarwanda is a draft, listed in `docs/frontend/rw-review-admin.md`). Sign-in with `returnTo=/seller` opens it with a full page load.
- **Server check:** `src/app/seller/layout.tsx` checks the session on the server for every request (`lib/seller.ts`: `GET /auth/me`, `GET /seller/store`, and `GET /seller/application` when the store is not approved):
  - no session: sign in, then back to `/seller`;
  - a staff account: "Staff accounts can't sell", with a link to the admin;
  - no store, or a pending, rejected or suspended one: a notice with the status and the reason, linking to the application;
  - only the owner of an approved store gets the shell.
  Each page also re-checks on the server (`SellerPage`, like the admin's `AdminPage`) and renders nothing otherwise. A suspension applies at the next request; the backend refuses every call at once anyway.
- **Shared frame:** the admin shell was split into a shared frame (`features/admin/panel-shell.tsx`: sidebar, top bar, language menu, signed-in person, log out). `AdminShell` and `SellerShell` each give it their own links. The admin looks and behaves as before.
- **Pages:**
  - **Dashboard:** orders to confirm, orders to pack or dispatch, low-stock SKUs, pending and earned totals (goods, commission, the seller's share; "payouts are not part of the dashboard yet"), the store's commission rate and the latest orders.
  - **Orders and order detail:** the store's own seller orders filtered by its status and the order number. The detail shows the store's lines, its share of the discount, commission and net, the recipient's name, phone and delivery address, the payment method and status, the whole order's status and the history. The one next step (confirm, start packing, mark dispatched, mark delivered) is behind a confirmation, with an optional note. Refusals are explained by code: `seller_order_awaiting_payment`, `seller_order_awaiting_other_stores`, `invalid_transition`, `inventory_conflict`. There is no cancel action: cancellation is the platform's.
  - **Products, product editor and inventory:** the admin's own screens. A catalogue scope (`features/admin/catalog-scope.tsx`) points them at `/seller/products`, `/seller/images`, `/seller/inventory` and the public category and brand lists instead of `/staff/*` and `/inventory`. For a seller it removes platform merchandising (the featured flag, bulk publishing, the catalogue import) and never sends `is_featured` (`withoutMerchandising`), and it adds "New product". Inside the admin the scope follows the staff member's permissions as before.
  - **Store profile:** name, description, contact details and location (only the changed fields are sent with `PATCH /seller/store`), logo and cover upload and removal, and the commission rate (read-only).

### Tests

- `frontend/src/features/seller/seller-helpers.test.ts`: next steps, refusal messages, navigation, sign-in return path, the panel language cookie, commission display, store form rules and bodies, when the application form opens, the merchandising strip, the category flattening, and the server check (signed out, staff, approved, suspended, no store).
- `frontend/src/features/seller/seller-dashboard.test.tsx`:
  - the seller's product list, editor and stock screen call only `/seller/*` and the public catalogue, and a new product is sent without `is_featured`;
  - an order detail shows only the store's part, sends exactly `{status, reason}` and explains a refusal;
  - a cancelled order offers no step, and another store's order reads as not found;
  - the application: first submission, verification required, approved (no form) and resubmission after a rejection.
- `category-hierarchy.test.tsx` now mounts the editor in the staff scope.

### Not in this phase, and points for the owner

- **Not built:**
  - the public store page and "Sold by" on cards, the product page and the cart, and the admin Sellers page (all built in phase 5);
  - seller notifications of new orders: the Orders badge counts orders waiting for the store's confirmation, read when a page loads.
- **Not run in a browser:** the development database is still before migration `c6e8a0b2d4f7`, which refuses to run while the development orders exist. Seeing the dashboard with data needs the seed cleanup, the upgrade and a reseed on the local development database, which deletes its demo data and needs the owner's go-ahead.
- **Branding:** the seller dashboard shows the current logo and no marketplace name ("Seller dashboard" in titles); the FurniHub name and logo arrive in phase 6.
- **Categories and brands:** sellers choose from the public category and brand lists (active ones only). A product whose category was hidden later keeps its category, but the picker cannot show its name to the seller.

## Phase 5 as built (2026-11-22)

Frontend, plus one read-only backend field. No migration, permission, route or business rule changed.

### Backend

- `CartLine.store` (`StoreReference`: id, name, slug) on every cart response, joined from the product's store in `cart_repository.lines`. It is display only: the store is never read from the request, and a line of a store that is no longer approved is already `unavailable` (phase 2). Test: `test_each_line_names_the_store_that_sells_it`. API types regenerated (`frontend/src/lib/api/schema.d.ts`).

### Storefront

- **"Sold by <store>"** (`components/store/sold-by.tsx`) on the product card, the listing card, the product page (under the title), the cart page and the mini cart. The store's name links to its page.
- **`/store/[slug]`** (`/rw/store/[slug]` in Kinyarwanda):
  - the store's cover, logo (a store icon when it has none), name, district and description, from `GET /stores/{slug}`;
  - its products in the existing category listing, filtered by `store=<slug>`, with the same filters, sorting and pages. The listing's base query (`BaseQuery`) gained `store`.
  - Pending, rejected, suspended and unknown stores are 404, as the API answers; the page never shows contact details, the street address or the owner (the public API does not send them).
  - There is no stores index page (not in the approved scope).

### Seller dashboard

- A "View my store" button in the top bar opens the store's public page in a new tab.

### Admin: Sellers (`/admin/sellers`, `sellers:read`)

- **Menu:** in the Store group, with a count of pending applications.
- **List:** stores and applications, newest submission first, filtered by status and searched by store, address, owner name or email (the API's own search). Shows the store, owner (name, email), district, submission and last decision dates, and status.
- **Detail (`/admin/sellers/[id]`):** the application (slug, about, address, contact email and phone, logo, cover, first approval), the owner's account, the history (who, when, status, reason or note), and for stores that have been approved, the pending and earned totals (read-only; payouts are not built).
- **Decisions (`sellers:manage`):** exactly the backend's transitions: pending → Approve or Reject; approved → Suspend; suspended → Reinstate. Each is behind a confirmation that says what happens. Rejecting and suspending need a reason of 10 to 500 characters, which the seller sees; approving and reinstating take an optional note kept in the history. A 409 `invalid_store_transition` (another administrator decided first) reloads the store and says so. The view-only state (no `sellers:manage`) shows no buttons and no commission form.
- **Commission (`sellers:manage`):** the store's effective rate, and an override typed as a percentage with up to two decimals (0 to 100), sent as whole basis points; empty sends null (use the platform default). As the backend already defines, a change applies to orders placed afterwards (the rate is snapshotted at checkout).
- **Public page link:** "View public page" opens `/store/<slug>` while the store is approved.

### Messages

English and Kinyarwanda together: `store.soldBy`, `store.storePage`, `admin.sellers.*`, `admin.shell.nav.sellers`, `admin.titles.sellers`/`seller`, `admin.seller.shell.viewStore`. The Kinyarwanda is a draft listed in `docs/frontend/rw-review.md` and `rw-review-admin.md`.

### Tests

- Backend: the cart line names its store (plus the existing cart, cart price, plan and security suites, and the PostgreSQL cart test).
- `frontend/src/features/admin/sellers-admin.test.tsx`:
  - the allowed decisions, the reason rule and percentage to basis points;
  - the menu item needs `sellers:read`;
  - the list filter and the approve, reject (reason required) and 409 flows, with the bodies they send;
  - Reinstate on a suspended store, the public link only while approved;
  - setting and clearing the override, the read-only view without `sellers:manage`, and not found.
- `product-card.test.tsx`: "Sold by" names the store and links to `/store/<slug>`.

### Not in this phase, and points for the owner

- **Not seen in a browser:** the development database is still before migration `c6e8a0b2d4f7` (phase 3), so the store page and the Sellers page have not been run against real data. Upgrading needs the seed cleanup, the upgrade and a reseed of the local development database (it deletes its demo data) and the owner's go-ahead.
- **Order screens:** the customer's order pages and the admin order detail do not show "Sold by" per line or the stores' parts. Only the cart was in this phase's scope.
- **The Sellers page** has no owner contact action beyond email and phone links, and no bulk decisions.
- **Branding:** the store page uses the current storefront frame; furniture taxonomy and FurniHub branding are phase 6.

## Phase 6 as built (2026-11-22)

Furniture domain, services, branding and development data (decisions 14 to 17). One migration (`f2a4c6e8b0d1`, service icons); no table or column changes.

### Taxonomy and attributes (decision 14)

- **One definition:** `backend/app/core/furniture.py` holds the taxonomy (six main categories, 25 subcategories: Living Room, Bedroom, Dining, Office, Outdoor, Kids) and the attributes: `width_cm`, `depth_cm`, `height_cm`, `seat_height_cm`, `weight_kg` (positive numbers up to 100,000), `material`, `color`, `style`, `finish`, `condition` (fixed codes) and `assembly_required` (true or false). An attribute set per category says which ones the editor offers (seating adds the seat height; mattresses have dimensions, weight, material and condition); any other category gets the default set. **The category names, choice lists and sets are development drafts for the owner to confirm.**
- **Stored in `products.specifications`**, beside the free specifications. Product create and update (staff and seller) check only the known keys: a wrong code, a non-number measurement or a non-boolean is 422; any other key stays free text. Products saved before this phase are not rewritten.
- **`GET /api/v1/catalog/attributes`** (public) lists the definitions and sets. **`material`, `color`, `style`** filters on `/catalog/products` and `/catalog/facets` (each repeatable; any code of a key matches, every key applies; an unknown code is 422), and `facets.attributes` counts each code with the other filters applied, listing a chosen code with 0.
- **Categories are data:** `scripts/apply_category_taxonomy.py` (development only, dry run by default) creates the taxonomy categories through the admin service and hides, never deletes, the categories and brands that are not furniture once nothing uses them.

### Storefront and editor

- Listing pages have Material, Colour and Style groups (desktop panel and mobile sheet), in the URL as `?material=…&color=…&style=…`. The frontend mirrors the codes in `frontend/src/lib/furniture.ts` so the URL is read before any request; a test checks every code has English and Kinyarwanda labels (`messages/*.json` → `furniture`).
- The product page shows the attributes first, named and valued in the reader's language with units; free specifications follow as written.
- The product editor (admin and seller) has a "Furniture details" card with the category's set from `/catalog/attributes`: number inputs (decimal comma accepted), choice and yes/no selects. Values are sent typed; the free rows are unchanged. An attribute outside the set that a product already has stays visible, so a category change loses nothing.
- Nav icons follow the furniture words of the category's slug and name.

### Services and quotes (decision 15)

- `scripts/seed_services.py` creates five furniture services (assembly, installation and wall mounting, delivery and room setup, upholstery and repair, wood refinishing; English drafts, Kinyarwanda left to staff) with the new icons `hammer`, `truck`, `ruler`, `sofa`, `paintbrush`, and hides the six technical services (never deleted, so their requests stay readable).
- Quotes: copy only (offices, hotels, schools and institutions); no change to the form, API or data.

### Branding (decision 16)

- Backend: `MARKETPLACE_NAME` (default `FurniHub`) in settings; the API root name and the email templates read it.
- Frontend: `NEXT_PUBLIC_MARKETPLACE_NAME` (default `FurniHub`) in `src/lib/marketplace.ts`. Messages write `{marketplace}` and the name is filled in once when they are loaded (`i18n/request.ts`), so no component holds it. The logo is a drawn wordmark (sofa mark and name) until FurniHub artwork is approved; the 404 illustration is an armchair. The electronics copy in English and Kinyarwanda was rewritten together; the Kinyarwanda texts are drafts listed in `docs/frontend/rw-review*.md`.

### Development data (decision 17)

- `scripts/seed_catalogue_data.py` now seeds the taxonomy (with parents), five invented manufacturers (most products have none), 30 furniture products in subcategories with typed attributes and variants, furniture banners, and the same people and history as before (15 orders, 12 reviews) over the three demo stores. Seed e-mail domain: `seed.furnihub.local`. Placeholder photos are drawn per main category.

### Tests

`test_furniture_attributes.py` (definitions, checks on create and update by staff and seller, filters, facets, order), `test_service_icons_migration.py`, the migration head in the earlier migration tests, `test_seed_development_catalogue.py` for the furniture data; frontend `lib/furniture.test.ts`, `lib/marketplace.test.ts`, `features/admin/furniture-fields.test.ts`, filter-group render tests, the furniture nav icons.

### Not in this phase, and points for the owner

- **To confirm:** the taxonomy, the choice lists and sets, the service texts, the Kinyarwanda drafts and the wordmark (no FurniHub logo file exists yet).
- **Local development database not reseeded.** It is still at phase 2 (`b2d4f6a8c0e1`). Moving it to this phase deletes its demo data (seed cleanup with the phase-2 code, `alembic upgrade head`, runtime-role provisioning, the seed, the taxonomy and services scripts) and waits for the owner's go-ahead.
- **Not filtered:** dimensions, weight, finish and condition are shown and edited but not offered as filters.
- **Quote form** still asks for "product name or model" lines; widening it (rooms, delivery dates per item) was out of scope.

## Consequences

- New tables (`stores`, `seller_orders`, `seller_order_status_history`) and new columns (`products.store_id`, `order_items.store_id`, `order_items.store_name_snapshot`) arrive by reviewed Alembic migrations; each table gets explicit grants in `scripts/provision_runtime_role.py` in the same change.
- The main risk is a missed store filter in reused services. It is mitigated by making the scope a required argument and by a cross-store test matrix: for every seller route, seller A is refused seller B's resources.
- ADR-006 is unchanged for staff; sellers sit beside it, not inside it.
