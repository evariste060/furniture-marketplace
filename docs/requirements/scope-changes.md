# Approved scope changes

The original requirement documents stay unchanged (see `original-checksums.txt`). Every change
to the MVP scope approved by the project owner after they were written is recorded here, newest
first. Where this file and an original document disagree, this file wins.

## SC-09: Back to top, one pinned header, no brands on the storefront (2026-11-24)

Approved by the project owner on 2026-11-24 (brief "FurniHub — Small UI & UX Enhancements", items
2 to 4). Trello card: none. Frontend only; no backend, API or database change. Item 1 (cascading
seller location) is not done yet: it needs a Rwanda location dataset and the owner's approval for
the dependency and for storing cell and village.

- **Back to top.** A round button in the page corner on every storefront page, once the page has
  scrolled past 600px; hidden again near the top. It scrolls smoothly (at once with reduced
  motion) and sits centred above the WhatsApp button, above the phone tab bar on small screens.
- **One pinned header.** When the header scrolls out of view it slides back in and stays pinned as
  one block: the actions row and the blue store menu together (it used to pin the actions row
  alone and hide the store menu).
- **No brands on the storefront.** The home page's Trusted Brands section is removed, and brands
  are no longer a filter anywhere: the Brand group in the filter panel and the phone filter
  sheet, the brand chips, `?brand=` in listing URLs (ignored), the mega menu's brand column (it
  lists the subcategories) and the phone menu's Brands row. **Left in place:** brand data, the
  admin's brand pages and the API; the `/brands` and `/brand/{slug}` pages still open when a link
  leads there (the product page's brand name links to its brand page).

## SC-08: seller application wizard, Seller Dashboard link, grey dark mode (2026-11-24)

Approved by the project owner on 2026-11-24 (items 6 to 9 of the storefront brief). Trello card:
none. Frontend only; the seller application API and its rules are unchanged.

- **Account menu.** "Sell with us" is removed from the account side menu and the phone Account
  popup. Applying starts from "Become a seller" in the store menu (SC-07), which opens
  `/account/seller`; a pending, rejected or suspended application shows its status there.
- **Seller Dashboard** appears in both account menus only while `GET /seller/application`
  answers `approved`, and opens `/seller`. It is not the control: the `/seller` layout checks the
  store on the server (a customer without an approved store gets the notice, no dashboard), and
  every seller API call requires an approved store (`require_approved_seller`, 403
  `seller_not_approved`). The menu follows sign-in, sign-out (the customer queries are dropped),
  refresh and approval (the status is read again when the page regains focus).
- **Application wizard.** The application form is four steps with "Step n of 4" and a progress
  bar: Your store (name, description), Contact (email, phone), Location (district, sector,
  street), Review (every answer, Edit per section) and Submit. Next checks the step with the
  existing rules (`checkStoreForm`); answers are kept moving back and forth; the same POST/PUT
  calls and error handling, and a store name the backend refuses returns to step 1.
- **Dark mode in charcoal greys** instead of navy: page `#1b1c1f` < card `#242529` < subtle
  `#2e3034`, borders `#383a40`/`#4a4d55`, never pure black. The navy bars, the admin sidebar and the
  blue category bar turn charcoal too. Two text tokens, `pri-fg` and `err-fg` (equal to `pri` and
  `err` in light mode), are lighter in dark mode, where the solid brand blue and red are below
  4.5:1 as text; the solid colours stay for buttons. Light mode and the saved choice are unchanged.

## SC-07: storefront changes: Services removed, Become a seller, dark mode, search suggestions (2026-11-23)

Approved by the project owner on 2026-11-23 (brief "Storefront UI Enhancement Task"). Trello card:
none (no furniture board exists). Frontend only; no backend, API or database change.

- **Services removed from the platform's pages.** The storefront's Services pages
  (`/services`, `/services/{slug}`, `/services/{slug}/request`), the Services entries in the
  category bar, the All Categories menu, the phone menu and the footer, the home page's services
  section and the Services place in the hero showcase are gone, as are the admin's Services and
  Service requests pages, their sidebar entries, badge counts and Overview tasks. This replaces
  SC-06's plan to make services seller-owned later. **Left in place:** the backend's services and
  service-request API, tables and data (ADR-013) are unchanged and no page uses them; removing
  them needs a migration and is left for the owner to approve. The audit log still names past
  service events.
- **Become a seller** on the right of the store's category bar, and in the phone menu, opens the
  existing seller application (`/account/seller`; sign-in first for guests).
- **Dark mode.** A toggle in the header's actions row (and Appearance in the phone menu) switches
  light and dark at once, everywhere (storefront, account, seller dashboard, admin). The choice is
  kept in this browser (`localStorage`) and applied before the first paint. Light stays the
  default. The design tokens gain two roles that equal the existing values in light mode,
  `card` (white surfaces) and `head` (navy headings), and a dark palette for the neutral tokens
  (`html[data-theme="dark"]` in `globals.css`); brand blues, navy bars and status colours keep
  their values. This extends the design handoff's "no new colours" rule for dark mode only.
- **Search suggestions.** The header's search box shows the shopper's recent searches (kept in
  this browser, at most six, each removable, and "Clear") and popular products (the best-selling
  product names from `GET /catalog/products`) while it has focus; typing narrows both; one click
  searches. Every search that opens `/search` is remembered.
- **Login page:** the note telling staff to sign in there is removed.

## SC-06: sellers operate their stores, administrators govern the marketplace (2026-11-22)

Approved by the project owner on 2026-11-22 (brief "Seller & Administrator Dashboard
Responsibility Consolidation" and the owner's answers the same day). Trello card: none (no
furniture board exists). Built as ADR-014 phase 7.

The Marketplace Administrator no longer runs store operations; each approved seller runs their own
store from `/seller`. The administrator governs the marketplace: sellers, product moderation,
categories and brands, promotions, reviews, platform support, analytics, settings, administrators
and the audit log.

- **Permissions held by no role.** `orders:read`, `orders:fulfil`, `payments:read`,
  `payments:manage`, `inventory:read`, `inventory:adjust` and the new `catalog:edit` stay declared,
  and every route keeps its check, but no role holds them in V1
  (`UNASSIGNED_PERMISSIONS` in `app/core/roles.py`). The administrator is refused with 403
  `permission_denied` on the staff order, payment, stock, stock report, variant, photo, bulk photo,
  bulk publish, catalogue import and import job routes. Nothing is deleted, so a later scope change
  can give a permission back without touching a route.
- **Product moderation only.** `PATCH /api/v1/staff/products/{id}` needs `catalog:manage` for
  `status` and `is_featured` and also `catalog:edit` (no role) for any other field. Products are
  created and edited by their sellers (SC-05 already stopped staff creating them).
- **No whole-order cancellation by hand.** Staff could cancel a whole order (`orders:fulfil`);
  nobody can now. Sellers cancel their own seller group as before, and the expiry job still
  cancels unpaid orders. Payment, stock commitment and the parent order stay with the platform.
- **Cash on delivery** needs no staff confirmation: a COD payment is settled automatically when its
  last store delivers. The staff confirmation route is unassigned with `payments:manage`.
- **Admin pages removed:** Orders and order detail, Payments, Inventory, Catalogue import and
  Product photos. The admin search finds products only; the bell no longer counts new orders and
  now counts seller applications.
- **New:** `GET /api/v1/staff/reports/marketplace` (`reports:read`; day, week or month): paid
  orders, goods sold and commission (from seller orders), new stores and new customers per period,
  and stores by status, customer accounts and published products now. Aggregates only, no
  customer, seller or order detail. It drives the new admin Overview and the
  `/admin/analytics` page (with the existing sales and best-seller Excel exports).
- **Seller dashboard:** a new Earnings page (`/seller/earnings`) shows the existing pending and
  earned totals and each seller order's goods, commission and share; the overview splits "to pack"
  and "to dispatch". No payouts, payout requests or seller promo codes are added.
- **Unchanged for now:** technical services, service requests and quote requests stay
  platform-owned under Platform support; making them seller-owned is a later phase. Invoice
  recovery (`invoices:recover`, backend only) stays with the administrator.
- **Known gap:** there is no moderation lock, so a seller can set a product the administrator hid
  back to active. A lock needs a new column and is left for the owner to approve.

## SC-05: the Marketplace Administrator is the only staff role (2026-11-21)

Approved by the project owner on 2026-11-21. Trello card: none (no furniture board exists).

The sales, operations, management and finance staff roles were designed for the original
single-business shop and are not carried into the marketplace. FurniHub V1 has one staff role,
the **Marketplace Administrator** (stored as `administrator`).

- **Permissions stay.** Every staff route still requires its own fine-grained permission
  (`catalog:manage`, `sellers:manage`, ...); the Marketplace Administrator holds them all
  (until SC-06, which leaves the store operations to the sellers). The
  authorization checks themselves are unchanged, so a role can be added later as a new scope
  change without touching the routes.
- **Staff accounts.** Administrators still create, edit, disable and re-enable other
  administrators, and the last active administrator can never be disabled. With one role there
  is nothing to change a role to: `PATCH /api/v1/staff/{staff_id}/role` and the admin's role
  filter and role pickers are removed; `role` may be omitted when creating staff and only
  `administrator` is accepted.
- **Database.** `staff_role_assignments.role` accepts only `administrator` (migration
  `a9d3f5b7c1e2`). The upgrade refuses to run while any staff account holds another role, and
  reports only the count per role; it never converts, disables or deletes an account.
- **Unchanged:** customer sign-in and accounts, seller authorization (sellers are store owners,
  not staff, ADR-014), the `/admin` server-side session check.
- **Product creation is moderation only** (confirmed with SC-05, built with ADR-014 phase 2):
  administrators review, edit, hide and archive any store's products but do not create products
  for sellers. Staff product creation is refused with 409 `staff_product_creation_disabled`, and
  an import row naming a product that does not exist is refused on that row (`product_slug`);
  import rows that update existing products still apply.

## SC-04: multi-vendor furniture marketplace (2026-11-21)

Approved by the project owner on 2026-11-21. Trello card: none (no furniture board exists).
Baseline before the change: commit `03bb5cc`.

The original documents describe a single electronics store. The owner changed both the business
model and the domain: the platform becomes a **multi-vendor furniture marketplace**, provisionally
named **FurniHub**, where sellers apply, are approved by a platform administrator, and run
their own store, products, stock and orders. Existing features are reused, not rebuilt.

- **Sellers.** A customer applies with their shop details; administrators approve, reject,
  suspend or reinstate. Only approved sellers reach seller features, checked by the backend on
  every request. Sellers are store owners, not staff, and see only their own store's data.
- **Products** belong to one store. Staff moderate the catalogue (review, hide, archive); they do
  not create products for sellers in V1.
- **Orders.** One customer order and one payment per checkout, split into one group per seller
  (ADR-014 option A). Sellers fulfil their own group; payment and whole-order cancellation stay
  with the platform. A commission is recorded per group.
- **Furniture domain.** Furniture categories and attributes; technical services become furniture
  services (assembly, installation); quote requests serve bulk furniture purchasing for offices,
  hotels, schools and other organizations; the development catalogue is reseeded with furniture
  from several demo stores.
- **Not in V1:** seller payouts, partial seller cancellations or refunds, per-seller delivery
  fees (the platform fee by district stays), per-seller invoicing. The platform issues invoices
  for the class project; this is configurable and not a verified legal or tax decision.

Full specification and phases: `docs/architecture/ADR-014-multi-vendor-marketplace.md`.

## SC-03: social media links in the footer (2026-11-18)

Approved by the project owner on 2026-11-18. Trello card: none.

The footer design showed social icons, but no setting held their links, so they were left out.
The owner added them: administrators set the store's Facebook, Instagram, X, YouTube, TikTok
and LinkedIn links in Settings (each optional, `https://` on the network's own site, removable),
and the footer shows an icon for each link that is set. In the same change the footer's contact
lines were removed and Company moved onto the first row, with "We accept" on a second row.

## SC-02: technical services and service requests (2026-11-17)

Approved by the project owner on 2026-11-17. Trello card: none.

The original documents cover selling electronics only. The owner added **technical services**
(CCTV and security surveillance, smart gates and gate automation, smart automation and access
control, IT infrastructure and networking, phone/computer/electronics repair, technical
training) to the MVP. Services are not products: no price, stock, cart or online payment.

- **Storefront.** A Services page lists the active services as cards; each service has its own
  page with what it includes, who it is for, Call and WhatsApp buttons and a "Request this
  service" form (name, Rwandan mobile number, optional email, location and preferred date,
  client type, message). "Services" is on the category bar after Deals, with a dropdown, and in
  the footer and the mobile menu. Pages exist in English and Kinyarwanda.
- **Home page** (approved the same day): an Our Services section under Featured Products, the
  services in the hero showcase, and Services as the last entry of the All Categories menu with
  the services under it. How Shopping Works is removed, and Best Selling Products and New
  Arrivals move below the category spotlights.
- **Requests.** Each request gets an `SR-` reference and, when an email is given, an
  acknowledgement email. Spam is limited by a hidden honeypot field and a per-number and
  per-network rate limit.
- **Admin.** Administrators and sales staff manage the services (texts in English and
  Kinyarwanda, icon, image, items, order, shown or hidden) and follow requests up (status,
  assignee, internal notes); management can view them. A service with requests can only be
  hidden, not deleted. Every change is audited.

Full specification: `docs/architecture/ADR-013-technical-services.md`.

## SC-01: customer reviews and wishlist move into the MVP (2026-10-27)

Approved by the project owner on 2026-10-27, during frontend phase 2.

The Product Requirements Document lists "customer reviews, wishlist and advanced product
comparison" as out of scope "unless explicitly approved after MVP scope is secured". The owner
approved **customer reviews** and the **wishlist** for the MVP. Product comparison, installment
lending and trade-in stay out of scope.

- **Reviews (backend module 20).** Verified buyers review a product once per delivered order
  item, through a single-use link that expires 90 days after delivery: signed-in customers from
  their order pages, guests from order tracking. Rating 1–5 (required), optional title (at most
  80 characters) and text (at most 2,000), plain text, no photos, no editing after sending. New
  reviews wait for moderation by an administrator or sales staff (`reviews:moderate`); only
  approved reviews are public, with the reviewer's first name and last initial and a "Verified
  purchase" label. Products show the average rating, the number of reviews and the 5-to-1
  distribution; the catalogue filters by minimum rating and sorts by top rated. Sending review
  links by SMS or email waits for notifications (module 17).
- **Wishlist (backend module 21).** Signed-in customers save up to 200 products. A guest who
  taps the heart signs in first, and the product is saved afterwards. Saved products that are
  no longer sold stay in the list, marked "No longer available", so the customer can remove
  them.

Full specification: `docs/IMPLEMENTATION_PLAN.md`, modules 20 and 21.
