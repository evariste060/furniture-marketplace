# 3 Sixty Technologies — Design handoff for Claude Code

This folder is the **approved UI design** for the 3 Sixty Technologies e-commerce frontend (storefront + admin panel). Build the Next.js app so every page looks and behaves like its design file here. Treat these files as the source of truth for layout, spacing, colours, typography, copy and states.

## What's in this folder

| Path | What it is |
|---|---|
| `tokens-and-components.css` | All design tokens (colours, type scale, radii, shadows) and the shared component styles (buttons, badges, inputs, cards, tables, tabs, icons, product illustrations). |
| `screens/*.dc.html` | One file per screen or shared component. |
| `assets/3sixty-logo.jpeg` | The real logo. On white it's shown with `mix-blend-mode: multiply`; on navy it sits on a white rounded plate. |

### How to read a `.dc.html` file

Each file is plain HTML + inline styles with a small template layer on top:

- `{{name}}` — a value from the `renderVals()` function at the bottom of the file. That function holds **example content** to show what each field looks like. In the app, the same fields come from the API (see "Data" below).
- `<sc-for list="{{items}}" as="it">…</sc-for>` — repeat the block for each item (→ `items.map(...)`).
- `<sc-if value="{{cond}}">…</sc-if>` — render only when true (→ `cond && ...`).
- `<dc-import name="Header" active="Phones">` — use the shared component `screens/Header.dc.html` with those props.
- `class="ic ic-cart i18"` — an icon (CSS-mask icons, Lucide set) at 18px. Use `lucide-react` with the same icon and size.
- `class="dev dev-ph-violet"` — a placeholder product illustration. In the real app this is the product photo URL from the API (see "Images" below), same box size.
- Ignore `<script src="./support.js">`, `<x-dc>`, `<helmet>` and `data-props` — they belong to the design tool.

## Rules for matching the design

1. **Use the tokens, never new values.** Put the `:root` variables from `tokens-and-components.css` into your Tailwind theme (or global CSS) and use them everywhere. No new colours, font sizes or radii.
2. **Font:** Inter 400/500/600/700/800, self-hosted with `next/font/local` (`src/app/fonts/InterVariable.woff2`, OFL licence beside it; owner decision 2026-10-27). No Google Fonts.
3. **Content width:** 1240px max with 24px side padding (`.wrap`). Mobile gutters 16px. Mobile-first: the `screens/Mobile*.dc.html` files show the 390px layouts.
4. **Copy is final.** Use the exact text from the designs, then move every string into `messages/en.json` and `messages/rw.json`.
5. **Build shared components first** and reuse them — never re-create a header or card inside a page.
6. **Keep every state** shown in the designs (empty, error, out of stock, price changed, payment failed, expired link, no access).
7. **Accessibility as drawn:** real `<button>`, `<a>`, `<label>`; `aria-label` on icon-only buttons.
8. When unsure, open the matching design file and copy its structure and inline style values exactly.

## Colour usage (from the brand palette)

| Token | Hex | Use |
|---|---|---|
| `--navy` | #0D2D52 | Announcement bar, footer, headings |
| `--deep` | #071F42 | Admin sidebar, business band |
| `--pri` | #0866F5 | Primary buttons, active nav, links, admin active item, sales chart |
| `--light` | #EAF3FF | Home hero, selected filter chips, info boxes |
| white | #FFFFFF | Store header, product cards, admin cards & tables |
| `--page` | #F5F8FC | Admin content area, store section backgrounds |
| `--bd` | #E2E8F0 | Borders: filter panel, cards, inputs, tables |
| `--ok` | #16A34A | In stock, paid, delivered |
| `--warn` | #F59E0B | Low stock, pending payment |
| `--err` | #DC2626 | Out of stock, failed payment, discounts, errors |

**Contrast substitutions (WCAG AA, approved 2026-10-27).** Three pairings in the designs are below 4.5:1, so the app uses an existing darker token instead:

| Design pairing | Ratio | Used instead | Ratio |
|---|---|---|---|
| `--pri` text on `--light` (secondary button, soft info badge, hero overline) | 4.44:1 | `--pri-h` | 6.15:1 |
| white text on `--ok` (solid green badge) | 3.30:1 | white on `--ok-tx` | 5.02:1 |
| `--mut` text on `--page` (table headers) | 4.47:1 | `--tx2` | 7.11:1 |

## Shared components → React components

| Design file | Component | Used on |
|---|---|---|
| `Header.dc.html` | `StoreHeader` (announcement bar + header + category nav; props: active nav item, cart count, account label, search query) | All storefront pages |
| `Footer.dc.html` | `StoreFooter` | All storefront pages |
| `CheckoutHeader.dc.html` | `CheckoutHeader` (prop `step` 0–4) | Checkout, payment status |
| `ProductCard.dc.html` | `ProductCard` | Home, search, related products |
| `ListingCard.dc.html` | `ListingCard` | Category / brand listing |
| `AdminSidebar.dc.html` | `AdminSidebar` (prop `active`; filter items by role) | All `/admin` pages |
| `AdminTopbar.dc.html` | `AdminTopbar` | All `/admin` pages |
| `StyleGuide.dc.html` | Reference only | — |

## Screens → routes

**Storefront**

| Design file | Route |
|---|---|
| `Main.dc.html` | `/` |
| `Category.dc.html` | `/category/[slug]` (also `/brand/[slug]`: first filter group becomes Category) |
| `Product.dc.html` | `/product/[slug]` |
| `MiniCart.dc.html` | Drawer opened by "Add to Cart" |
| `Search.dc.html`, `SearchEmpty.dc.html` | `/search?q=` (results / no results) |
| `Cart.dc.html` | `/cart` (shows price-changed, out-of-stock and invalid-code states) |
| `CheckoutContact.dc.html` → `CheckoutDelivery` → `CheckoutPayment` → `CheckoutReview` | `/checkout` steps 1–4 |
| `PaymentWaiting.dc.html`, `PaymentFailed.dc.html` | `/checkout/pay/[orderNumber]` |
| `OrderConfirmed.dc.html` | `/order/[number]/confirmed` |
| `Track.dc.html` | `/track` |
| `Login`, `Register`, `Forgot`, `Reset` | `/login`, `/register`, `/forgot-password`, `/reset-password` |
| `Account`, `MyOrders`, `OrderDetail`, `Addresses`, `Profile` | `/account`, `/account/orders`, `/account/orders/[number]`, `/account/addresses`, `/account/profile` |
| `WriteReview.dc.html` | `/review/[token]` (includes thank-you, expired, already-reviewed states) |
| `Contact.dc.html` | `/contact` |
| `Policy.dc.html` | `/pages/[slug]` |
| `NotFound.dc.html`, `ServerError.dc.html` | `not-found.tsx`, `error.tsx` |
| `MobileHome`, `MobileCategory`, `MobileProduct`, `MobileCart`, `MobileCheckout`, `MobileMenu` | Phone layouts of the pages above (< 768px) |

**Admin (`/admin`)**

| Design file | Route |
|---|---|
| `Dashboard.dc.html` | `/admin` |
| `Orders.dc.html`, `AdminOrderDetail.dc.html` | `/admin/orders`, `/admin/orders/[id]` |
| `Products.dc.html`, `ProductEditor.dc.html` | `/admin/products`, `/admin/products/new`, `/admin/products/[id]` |
| `Inventory.dc.html` | `/admin/inventory` (with Adjust stock dialog) |
| `Payments.dc.html` | `/admin/payments` |
| `Reviews.dc.html` | `/admin/reviews` |
| `Categories.dc.html` | `/admin/categories`, `/admin/brands` |
| `Import.dc.html` | `/admin/import` |
| `Delivery.dc.html` | `/admin/delivery` |
| `Promotions.dc.html` | `/admin/promotions` |
| `Analytics.dc.html` | `/admin/analytics` (use Recharts for the charts) |
| `Reports.dc.html` | `/admin/reports` |
| `Notifications.dc.html` | `/admin/notifications` |
| `Staff.dc.html` | `/admin/staff` |
| `Settings.dc.html` | `/admin/settings`, `/admin/pages` |
| `Audit.dc.html` | `/admin/audit` |
| `AccessDenied.dc.html` | Shown inside the admin shell when a role can't open a page |

## Suggested build order

1. Tokens + fonts + base components (Button, Badge, Input, Select, Checkbox, Card, Table, Tabs).
2. `StoreHeader`, `StoreFooter`, `ProductCard`, `ListingCard`, WhatsApp button.
3. Home → Category → Product → Search.
4. Cart → Checkout → Payment status → Confirmation.
5. Track, auth pages, account area, write review.
6. Admin shell → Dashboard → Orders → Products → Inventory → the rest.
7. Support pages and error states.

## Data: real API from day one (no mock data)

- The `renderVals()` data in the design files shows **what content looks like**. Do not copy it into the frontend as mock data. Every page reads from the FastAPI backend.
- Sample content lives in the backend's **seed script** (`backend/scripts/seed.py` or similar), which loads realistic categories, brands, products with images, orders and staff into the dev database.
- Generate TypeScript types from the backend's OpenAPI schema (`openapi-typescript` → `src/lib/api/schema.d.ts`) and use one typed client in `src/lib/api/` (`openapi-fetch`). Regenerate types whenever the backend changes. Never hand-write response types.
- The base URL comes from `NEXT_PUBLIC_API_URL` (browser) and `API_URL` (server). Storefront pages fetch in Server Components; admin pages and interactive parts (cart, filters) use TanStack Query.
- Every list reads the backend's `{ items, total, page, size }`. `total`, `page` and `size` drive pagination and totals.
- If a page needs an endpoint that doesn't exist yet, **stop and add the endpoint to the backend first** (or tell the user). Don't fake it in the frontend.
- Handle loading (skeletons the same size as the real cards), empty and error states on every page, as shown in the designs.

## Images

- Product, category, brand and banner images are uploaded in the admin (Product editor, Categories, Settings/Promotions). The backend stores the file and returns full URLs in the API, e.g. `images: [{ url, width, height, alt, position }]` on products, `image` on categories and `logo` on brands.
- The frontend never stores images and never hard-codes image paths. It renders whatever URL the API returns with `next/image` (`object-fit: contain` on product photos, white background, same box sizes as the `.dev` placeholders in the designs).
- Allow the image host in `next.config` `images.remotePatterns` (the API host in development, the storage/CDN domain in production).
- If a product has no image, show a neutral placeholder (light grey box with the `ic-package` icon), never a broken image.
- Only the logo, favicon and static brand graphics live in `public/`.
