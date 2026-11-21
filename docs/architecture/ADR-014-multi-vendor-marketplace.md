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
9. **Parent order lifecycle.** The parent `orders.status` keeps its existing machine and remains what the customer sees. Payment, the `received → confirmed` step (which commits stock and applies the cash-on-delivery rules) and whole-order cancellation stay at the parent. Each seller moves its own group through processing, dispatched and delivered; the parent becomes `dispatched` when every group is dispatched and `delivered` when every group is delivered, which keeps the existing cash-on-delivery "delivered marks the payment succeeded" and invoice rules on the parent. Exact rollup rules and their edge cases are specified and approved in phase 3 before they are built.
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
| 0 | Baseline commit `03bb5cc`; this ADR, SC-04, AGENTS.md and README updates | Done (2026-11-21); awaiting owner review |
| 1 | `stores`, seller application and admin review APIs, `require_approved_seller`, `sellers:*` permissions, runtime-role grants | Not started |
| 2 | `products.store_id`, store-scoped seller product, image and inventory APIs, approved-store catalogue filter, public store endpoints, cross-store isolation tests | Not started |
| 3 | `order_items.store_id`, `seller_orders`, checkout grouping, seller order API, parent status rollup, admin group view, commission and earnings | Not started |
| 4 | Frontend: "Become a seller" and application status in Account; `/seller` dashboard reusing the admin shell and components | Not started |
| 5 | Frontend: `/store/[slug]`, "Sold by" on cards, product page and cart; admin Sellers page | Not started |
| 6 | Furniture taxonomy, attribute sets, filters, services and quotes adaptation, FurniHub branding (English and Kinyarwanda), furniture seed data | Not started |

## Consequences

- New tables (`stores`, `seller_orders`, `seller_order_status_history`) and new columns (`products.store_id`, `order_items.store_id`, `order_items.store_name_snapshot`) arrive by reviewed Alembic migrations; each table gets explicit grants in `scripts/provision_runtime_role.py` in the same change.
- The main risk is a missed store filter in reused services. It is mitigated by making the scope a required argument and by a cross-store test matrix: for every seller route, seller A is refused seller B's resources.
- ADR-006 is unchanged for staff; sellers sit beside it, not inside it.
