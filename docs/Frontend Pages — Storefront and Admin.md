# Frontend Pages — Storefront and Admin

Oct 23, 2026 · @Evariste Nkurunziza

The frontend needs 38 pages: 22 for customers and 16 in the admin panel, built in one Next.js app, mobile-first, in English and Kinyarwanda. Each page lists the backend modules it calls (numbers from the Backend Modules doc), so it is built only after those modules are ready.

## Storefront pages

These 8 pages are how customers discover products; they must load fast on mid-range phones and be indexable by Google.

| # | Page | Route | What it shows / does | Key components | Backend modules | Req | Build day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Home | `/` | Banner, key categories, featured / bestselling / new products, trust and contact info | HeroBanner, CategoryGrid, ProductCarousel, TrustBar | 5, 6, 9, 19 | PR-01 | Day 8 |
| 2 | Category listing | `/category/[slug]` | Products in a category with brand and price filters, sort, clear filters, pagination | FilterPanel, SortSelect, ProductGrid, Pagination | 5, 9 | PR-02 | Day 8 |
| 3 | Brand listing | `/brand/[slug]` | Same listing filtered by brand | (reuses listing components) | 5, 9 | PR-02 | Day 8 |
| 4 | Product detail | `/product/[slug]` | Images, brand/model, specs, RWF price, variant picker, stock, warranty, delivery and payment info, related items, add to cart, WhatsApp button | ImageGallery, VariantPicker, SpecsTable, PriceTag, StockBadge, AddToCart | 6, 7, 10, 11 | PR-03 | Day 8 |
| 5 | Search results | `/search?q=` | Matches by name, brand, model; helpful empty state with contact link | SearchBar, ProductGrid, EmptyState | 9 | PR-04 | Day 9 |
| 6 | Contact & bulk quote | `/contact` | Phone, WhatsApp, email, store location; quote request form for business buyers | ContactCard, QuoteForm | 19 | PR-01 | Day 15 |
| 7 | Info & policy pages | `/pages/[slug]` | About, delivery info, returns, warranty, privacy, terms | RichText | 19 | PR-15 | Day 15 |
| 8 | Not found / error | `/not-found`, error boundary | Friendly message, search and home links | EmptyState | — | PR-16 | Day 15 |

## Checkout and customer account pages

These 14 pages carry the purchase and the customer's history; checkout must work as a guest and show every fee before the order is placed.

| # | Page | Route | What it shows / does | Key components | Backend modules | Req | Build day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 9 | Cart | `/cart` | Items, quantity change, remove, discount code, subtotal | CartItem, QuantityStepper, PromoCodeInput, OrderSummary | 11, 13 | PR-05 | Day 9 |
| 10 | Checkout | `/checkout` | Steps: contact → address and delivery zone → payment method → review; fees and total visible before submit | CheckoutStepper, AddressForm, DeliveryZoneSelect, PaymentMethodPicker, OrderSummary | 12, 13, 14 | PR-05, PR-11 | Day 10 |
| 11 | Payment status | `/checkout/pay/[orderNumber]` | "Approve on your phone" screen for MoMo/Airtel, polls status, retry or change method | PaymentWaiting, StatusPoller | 15 | PR-08 | Day 11 |
| 12 | Order confirmation | `/order/[number]/confirmed` | Order number, items, total, payment status, next steps, invoice link | OrderSummary, StatusBadge | 14, 16 | PR-07 | Day 11 |
| 13 | Track order | `/track` | Enter order number + phone; shows status timeline | TrackForm, OrderTimeline | 14 | PR-07 | Day 13 |
| 14 | Login | `/login` | Email or phone + password; redirects staff to admin | AuthForm | 2 | PR-06 | Day 5 |
| 15 | Register | `/register` | Name, email/phone, password | AuthForm | 2 | PR-06 | Day 5 |
| 16 | Forgot password | `/forgot-password` | Request reset code | AuthForm | 2 | PR-06 | Day 5 |
| 17 | Reset password | `/reset-password` | Enter code and new password | AuthForm | 2 | PR-06 | Day 5 |
| 18 | Account overview | `/account` | Greeting, recent orders, quick links | AccountNav, OrderCard | 3, 14 | PR-06 | Day 10 |
| 19 | My orders | `/account/orders` | Order history with status and totals | OrderCard, Pagination | 14 | PR-06 | Day 10 |
| 20 | Order detail | `/account/orders/[number]` | Items, payment, delivery timeline, invoice download | OrderTimeline, OrderSummary | 14, 16 | PR-07 | Day 13 |
| 21 | Addresses | `/account/addresses` | Add, edit, delete, set default | AddressForm, AddressCard | 3 | PR-06 | Day 10 |
| 22 | Profile | `/account/profile` | Name, phone, email, change password, language | ProfileForm | 3 | PR-06 | Day 10 |

## Admin panel pages

These 16 pages under `/admin` let staff run the store without developers; each is hidden from roles that may not use it.

| # | Page | Route | What it shows / does | Roles | Backend modules | Req | Build day |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | Staff & roles | `/admin/staff` | Create staff, assign role, deactivate | Admin | 3 | PR-15 | Day 6 |
| A2 | Categories & brands | `/admin/categories`, `/admin/brands` | Tree editor, add/edit/hide | Admin, sales | 5 | PR-10 | Day 6 |
| A3 | Products list | `/admin/products` | Search, filter by category/brand/status, quick hide, low-stock flag | Admin, sales | 6, 9 | PR-10 | Day 6 |
| A4 | Product editor | `/admin/products/new`, `/admin/products/[id]` | Details, specs, warranty, variants with price and stock, image upload and ordering | Admin, sales | 6, 7 | PR-10 | Day 6 |
| A5 | Catalogue import | `/admin/import` | Download template, upload CSV/XLSX, progress, row/field error report | Admin, sales | 8 | PR-10 | Day 7 |
| A6 | Inventory | `/admin/inventory` | Stock per variant, low-stock filter, manual adjustment with reason, movement history | Admin, sales, ops | 10 | PR-09 | Day 9 |
| A7 | Payments | `/admin/payments` | Provider reference, amount, status, linked order; failed/pending filter; export | Admin, finance | 15 | PR-08 | Day 12 |
| A8 | Orders list | `/admin/orders` | Filter by status, date, payment method; search by number/phone | Admin, sales, ops | 14 | PR-07 | Day 13 |
| A9 | Order detail | `/admin/orders/[id]` | Items, customer, payment, status buttons (only allowed next states), cancel, invoice and delivery note | Admin, sales, ops | 14, 15, 16 | PR-07, PR-14 | Day 13 |
| A10 | Delivery zones | `/admin/delivery` | Zones, fees, free-delivery threshold | Admin, ops | 12 | PR-11 | Day 13 |
| A11 | Promotions | `/admin/promotions` | Create/disable codes and product discounts, validity dates, usage | Admin | 13 | PR-12 | Day 14 |
| A12 | Notifications log | `/admin/notifications` | Sent/failed SMS and email, retry | Admin | 17 | PR-07 | Day 14 |
| A13 | Dashboard | `/admin` | Today's orders and sales, pending payments, orders to dispatch, low stock | All staff | 14, 10, 18 | PR-13 | Day 15 |
| A14 | Reports | `/admin/reports` | Daily/weekly sales, top products, stock; export to Excel | Admin, management | 18 | PR-13 | Day 15 |
| A15 | Settings & pages | `/admin/settings`, `/admin/pages` | Store contact, WhatsApp number, banners, policy text in EN/RW | Admin | 19 | PR-01, PR-15 | Day 15 |
| A16 | Audit log | `/admin/audit` | Who changed what and when | Admin | 4 | PR-15 | Day 15 |

## Shared layouts and components

Build these first (Days 4–5) so every page is assembled from the same parts.

| Group | Components | Used by |
| --- | --- | --- |
| Store layout | Header (logo, search, cart count, account, language switch), category menu, mobile bottom bar, footer (contact, policies, payment logos), floating WhatsApp button | Pages 1–22 |
| Admin layout | Sidebar filtered by role, top bar with user and logout, breadcrumbs | A1–A16 |
| Product display | ProductCard, ProductGrid, PriceTag (RWF format), StockBadge, ImageGallery | Home, listings, search, product |
| Forms | Input, PhoneInput (+250), Select, Checkbox, FormError, SubmitButton with loading state | Auth, checkout, account, admin |
| Feedback | Toast, Skeleton loader, EmptyState, ConfirmDialog, ErrorBoundary | All pages |
| Data (admin) | DataTable with sort/filter/pagination, StatusBadge, DateRangePicker, ExportButton | Admin lists and reports |
| Order | OrderSummary, OrderTimeline, StatusBadge | Cart, checkout, account, admin orders |

## Folder structure and conventions

One Next.js App Router project holds the store and the admin, separated by route groups.

```
web/
  src/
    app/
      [locale]/                 # en | rw
        (store)/
          layout.tsx            # store header/footer
          page.tsx              # home
          category/[slug]/page.tsx
          brand/[slug]/page.tsx
          product/[slug]/page.tsx
          search/page.tsx
          cart/page.tsx
          checkout/page.tsx
          checkout/pay/[orderNumber]/page.tsx
          order/[number]/confirmed/page.tsx
          track/page.tsx
          contact/page.tsx
          pages/[slug]/page.tsx
          (auth)/login, register, forgot-password, reset-password
          account/ (overview, orders, orders/[number], addresses, profile)
        admin/
          layout.tsx            # role-checked admin shell
          page.tsx              # dashboard
          products/, categories/, brands/, import/, inventory/,
          orders/, payments/, delivery/, promotions/, reports/,
          notifications/, staff/, settings/, pages/, audit/
    components/
      ui/        # buttons, inputs, dialogs, toast
      store/     # ProductCard, FilterPanel, CartItem ...
      admin/     # DataTable, StatusBadge ...
    lib/
      api.ts     # fetch wrapper: base URL, auth token, error shape
      format.ts  # RWF, dates, phone
    messages/    # en.json, rw.json
    middleware.ts  # locale + admin route protection
```

- **Rendering:** store pages server-rendered for SEO and speed; cart, checkout and admin are client components.
- **Data:** one `api.ts` client that understands the backend's `{ data, meta }` / `{ error }` shapes; TanStack Query for client-side caching.
- **Forms:** React Hook Form + Zod schemas that mirror the backend's Pydantic models; generate TypeScript types from FastAPI's OpenAPI spec (e.g. openapi-typescript).
- **Text:** no hard-coded strings; every label goes in `messages/en.json` and `messages/rw.json`.
- **Images:** `next/image` with sizes set; WebP; lazy loading below the fold.
- **Mobile-first:** design and test at 360 px width first, then tablet and desktop.

## Page done checklist

A page is finished only when every box is ticked.

- [ ] Matches the approved design at mobile (360 px), tablet and desktop
- [ ] Loading, empty and error states handled
- [ ] All text in English and Kinyarwanda message files
- [ ] Connected to the real API (no mock data left)
- [ ] Forms validate and show clear errors; buttons show a loading state
- [ ] Admin pages hidden and blocked for roles that may not use them
- [ ] Store pages have a title, meta description and clean URL
- [ ] Usable on a slow 3G connection; images optimised
- [ ] Linked TC tests run and recorded in the QA checklist
