# Electronics E-Commerce MVP — Development Activity Plan

Oct 23, 2026 · @Evariste Nkurunziza

## Overview

The MVP is built in 20 working days, Mon 26 Oct to Fri 20 Nov 2026, in four one-week sprints that each end with a demo and a gate. This plan turns the PRD (PR-01 to PR-16), the Technical Delivery Plan and the QA checklist (TC-01 to TC-24) into concrete daily development activities.

| Sprint | Dates | Goal | Gate at end |
| --- | --- | --- | --- |
| 1 — Foundation | 26–30 Oct | Decisions, designs, repo, environments, data model, auth | Scope/design gate (Day 5) |
| 2 — Core store | 2–6 Nov | Browse, search, product page, cart, checkout shell, admin catalogue | Staging demo: test order placed |
| 3 — Transactions | 9–13 Nov | Payments, order lifecycle, delivery, notifications, promotions, reports | Feature gate (Day 15) |
| 4 — Test & launch | 16–20 Nov | QA, UAT, fixes, training, go-live, handover | Launch gate (Day 18/19), handover (Day 20) |

Assumptions: a small team (1 lead, 2–3 developers, 1 designer, 1 QA), a single store with no multi-vendor features, and business decisions closed on the dates set in the PRD. If you start on a different Monday, shift every date by the same amount.

## Proposed stack and architecture

Recommendation for ADR-001: a custom build on React (Next.js) + FastAPI (Python) + PostgreSQL, because it fits the team's chosen skills and gives full control over MoMo/Airtel callbacks and stock rules. The faster alternative is a hosted platform (e.g. Shopify or WooCommerce) if local payment plugins are confirmed; decide by Day 2.

| Layer | Proposal | Why | ADR |
| --- | --- | --- | --- |
| Storefront | Next.js (React), Tailwind CSS, server-side rendering | SEO for product pages, fast on mobile | ADR-001 |
| Admin panel | React pages in the same Next.js app, behind role-based login | One codebase, staff self-service | ADR-001 |
| API | FastAPI (Python, REST), Pydantic validation, auto-generated OpenAPI docs | Team choice, async webhook handling, typed request/response models | ADR-001 |
| Database | PostgreSQL + SQLAlchemy 2.0, Alembic migrations | Transactions for stock and orders, migrations | ADR-002 |
| Images | Cloud object storage with resizing/CDN | Compressed images for slow connections | ADR-002 |
| Payments | MTN MoMo, Airtel Money, card via a local aggregator or direct provider APIs | Sandbox first, webhooks, reconciliation | ADR-003 |
| Hosting | Separate staging and production; managed Postgres with daily backups | Rollback, TLS, restore test | ADR-004 |
| Notifications | SMS + email provider with delivery reports | Order status messages | ADR-005 |
| i18n | next-intl (English + Kinyarwanda) | Language switch from day one | ADR-001 |
| Monitoring | Error tracking + uptime checks + analytics | Launch and first-week support | ADR-004 |

&#91;embedded content: system architecture · web app, API, database, payment and messaging providers\]

The browser never talks to payment providers' callbacks directly: confirmations arrive as webhooks at the API, which updates the order and stock in one transaction.

## Development modules (epics)

The work splits into 12 epics; P0 epics form the purchase path and must ship, P1 ship with the MVP unless the business owner approves a workaround.

| Epic | Main tasks | Requirements | Priority | Sprint | Tests |
| --- | --- | --- | --- | --- | --- |
| E1 Setup & DevOps | Repo, CI, staging/prod, secrets, backups, monitoring | PR-15 | P0 | 1 | TC-23 |
| E2 Auth & roles | Customer register/login (email/phone), staff roles: admin, sales, operations | PR-06, PR-15 | P0 | 1–2 | TC-07, TC-16 |
| E3 Catalogue & admin | Categories, brands, products, variants, images, specs, warranty; CSV/Excel import with error report | PR-10 | P0 | 1–2 | TC-15 |
| E4 Storefront browsing | Home page, category pages, brand/price filters, sort, product detail | PR-01, PR-02, PR-03 | P0 | 2 | TC-01, TC-02, TC-04 |
| E5 Search | Search by name, brand, model; empty-result state with contact link | PR-04 | P0 | 2 | TC-03 |
| E6 Cart & checkout | Cart, guest and account checkout, address, delivery choice, totals | PR-05 | P0 | 2–3 | TC-05, TC-06, TC-07 |
| E7 Inventory | Stock count, reservation on order, release on cancel/fail, low-stock alert | PR-09 | P0 | 2–3 | TC-13, TC-14 |
| E8 Payments | MoMo, Airtel, card, COD; webhooks, idempotency, reconciliation | PR-08 | P0 | 2–3 | TC-08 to TC-12, TC-24 |
| E9 Orders & delivery | Order states, staff order screens, delivery zones/fees, invoice and delivery note | PR-07, PR-11, PR-14 | P0 | 3 | TC-17, TC-18 |
| E10 Notifications | SMS/email on order status, WhatsApp/call links | PR-07 | P1 | 3 | TC-19 |
| E11 Promotions & reports | Discount codes, product discounts, sales/stock reports, Excel export | PR-12, PR-13 | P1 | 3 | UAT scenario 7 |
| E12 Content, SEO & i18n | Policy pages, English/Kinyarwanda, meta tags, sitemap, analytics, image optimisation | PR-15, PR-16 | P1 | 3–4 | TC-20, TC-21, TC-22 |

## Day-by-day development schedule

Each day has one clear output that can be demonstrated or checked; tests are written alongside the feature, not saved for Week 4.

### Sprint 1 — Foundation (26–30 Oct)

| Day | Date | Development activities | Output / evidence |
| --- | --- | --- | --- |
| 1 | Mon 26 Oct | Kickoff; assign RACI names; set up project board and backlog from the epics; send catalogue import template; start payment merchant application | Board with all epics; template sent; payment application started |
| 2 | Tue 27 Oct | Decide stack and hosting (ADR-001, ADR-004); create repo, branch rules, CI pipeline (lint, tests, build); project skeleton for web and API | ADRs written; CI green on empty app |
| 3 | Wed 28 Oct | Database schema v1 (ADR-002): products, variants, categories, brands, users, orders, payments, stock movements; migrations and seed data; validate sample catalogue import | Schema migrated on staging; sample import checked |
| 4 | Thu 29 Oct | Staging deployment live with HTTPS; auth (customer + staff) and role middleware; designer delivers mobile wireframes for home, listing, product, cart, checkout | Staging URL; login works; wireframes reviewed |
| 5 | Fri 30 Oct | Approve designs and design tokens (colours, type, components); freeze MVP scope; payment sandbox credentials requested/received; i18n set up | Scope/design gate signed |

### Sprint 2 — Core store (2–6 Nov)

| Day | Date | Development activities | Output / evidence |
| --- | --- | --- | --- |
| 6 | Mon 2 Nov | Admin: product, variant, category, brand CRUD; image upload with resizing | Staff can add a laptop with variants |
| 7 | Tue 3 Nov | CSV/Excel import with row-level validation and error report; import the first real catalogue batch | TC-15 passes on staging |
| 8 | Wed 4 Nov | Storefront: home page, category pages, brand/price filters, sort; product detail page with specs, stock, warranty | TC-01, TC-02, TC-04 run |
| 9 | Thu 5 Nov | Search (name, brand, model) with empty state; cart (add, update, remove, totals); stock reservation logic | TC-03, TC-05 run |
| 10 | Fri 6 Nov | Checkout shell: guest and account flows, address, order summary; create order in Pending state; payment sandbox first call | Sprint demo: test order placed on staging |

### Sprint 3 — Transactions & operations (9–13 Nov)

| Day | Date | Development activities | Output / evidence |
| --- | --- | --- | --- |
| 11 | Mon 9 Nov | MTN MoMo and Airtel Money sandbox flows; webhook endpoint with signature check and idempotency; payment-to-order matching | TC-08, TC-09 run |
| 12 | Tue 10 Nov | Card payment (if enabled), COD, failed/cancelled/duplicate callback handling; reconciliation view for finance | TC-10, TC-11, TC-12 run |
| 13 | Wed 11 Nov | Order lifecycle and staff order screens; delivery zones and fee matrix in checkout; invoice and delivery note templates | TC-14, TC-17, TC-18 run |
| 14 | Thu 12 Nov | SMS/email notifications with retry and logging; WhatsApp/call links; promotions (codes and product discounts) | TC-19 run |
| 15 | Fri 13 Nov | Reports with Excel export; policy pages; Kinyarwanda strings; SEO (meta, sitemap, clean URLs); analytics | Feature gate: end-to-end sandbox order passes, no P0 open |

### Sprint 4 — Test & launch (16–20 Nov)

| Day | Date | Development activities | Output / evidence |
| --- | --- | --- | --- |
| 16 | Mon 16 Nov | Full QA run TC-01 to TC-23; security checks (roles, secrets, dependency audit); mobile performance on slow connection | Test record filled; defects logged with severity |
| 17 | Tue 17 Nov | Fix S0/S1 defects; business UAT on staging (8 scenarios); backup restore test; production environment set up | UAT in progress; restore verified |
| 18 | Wed 18 Nov | Fix UAT findings; staff training session; admin guide; production deploy; live payment credentials stored securely | UAT signed; production ready |
| 19 | Thu 19 Nov | Live low-value payment smoke test and reconciliation (TC-24); go-live; close monitoring | Launch gate passed; store live |
| 20 | Fri 20 Nov | Monitor and hot-fix; handover pack (repo, deployment/rollback steps, ADRs, known issues); post-launch backlog | Handover signed |

## Core data model and technical rules

Get the schema right on Day 3: orders, payments and stock are the parts that are expensive to change later.

| Table | Key fields |
| --- | --- |
| categories / brands | id, name, slug, parent\_id (categories), active |
| products | id, sku, name, slug, category\_id, brand\_id, model, description, specs (JSON), warranty, active |
| product\_variants | id, product\_id, sku, attributes (colour, storage, RAM), price\_rwf, compare\_at\_price, stock, low\_stock\_threshold |
| product\_images | id, product\_id, variant\_id, url, position |
| users | id, name, email, phone, password\_hash, role (customer, admin, sales, operations) |
| addresses | id, user\_id, district, sector, street/landmark, phone |
| orders | id, number, user\_id or guest contact, status, subtotal, discount, delivery\_fee, tax\_treatment, total, delivery\_zone\_id, timestamps |
| order\_items | id, order\_id, variant\_id, quantity, unit\_price |
| payments | id, order\_id, method, provider\_ref (unique), amount, status, raw\_callback, timestamps |
| stock\_movements | id, variant\_id, change, reason (order, cancel, import, manual), order\_id, user\_id |
| delivery\_zones | id, name, fee\_rwf, free\_over\_rwf |
| promotions | id, code, type, value, starts\_at, ends\_at, usage\_limit, active |
| audit\_log | id, user\_id, action, entity, entity\_id, timestamp |

Rules the code must enforce:

1. Order states move only along allowed paths: Received → Confirmed → Processing → Dispatched → Delivered, and Cancelled from any state before Dispatched.
2. Payment webhooks verify the provider's signature, and a unique provider\_ref means a repeated callback can never mark an order paid twice.
3. Stock is decremented inside a database transaction with a row lock (SELECT … FOR UPDATE), so two customers cannot buy the last unit.
4. Unpaid orders release reserved stock after an agreed timeout (e.g. 30 minutes for mobile money; confirm with operations).
5. Prices are stored as whole RWF integers; never store card numbers, passwords or secrets in logs.

## Development workflow

Every change goes branch → pull request → review → staging → production; nobody pushes straight to production.

- **Branches:** `main` = production, `develop` = staging, feature branches named by backlog ID (e.g. `feat/E6-guest-checkout`).
- **Pull requests:** at least one reviewer, CI must pass (lint, unit tests, build), link the backlog item and attach a screenshot for UI work.
- **Environments:** local → staging (sandbox payments, test data) → production (live payments, real data). Separate credentials for each; secrets only in environment variables.
- **Tests:** unit tests for prices, discounts, delivery fees and order states; integration tests for checkout, webhooks and stock; manual QA against the TC list.
- **Daily routine:** 15-minute stand-up (done yesterday, today's goal, blockers); update the board; deploy to staging at least once a day.
- **Weekly routine:** Friday sprint demo to the business owner, then a short retro and planning for the next sprint.

**Definition of ready:** acceptance criteria agreed, design available, data and dependencies in hand.

**Definition of done:** code reviewed and merged, tests passing, checked on mobile and desktop, errors logged, deployed to staging, QA evidence attached.

## Dependencies and what to build while blocked

Payment approval is the dependency most likely to delay launch, so the code is designed to keep moving without it.

| Dependency | Needed by | Owner | If late, developers… |
| --- | --- | --- | --- |
| Payment merchant account + sandbox | Day 10 (sandbox), Day 18 (live) | Business + finance | Build behind a `PaymentProvider` interface with a mock provider; use COD/manual flow only if business approves |
| Catalogue data (100–200 products) | Day 7 | Merchandising | Use 20 realistic seed products; import the rest when ready |
| Delivery zones and fees | Day 13 | Operations | Build the zone/fee admin screen; load placeholder zones |
| VAT, invoice format, EBM decision | Day 13 | Finance | Build invoice template with configurable tax line; do not claim EBM integration |
| SMS/email provider credentials | Day 14 | Operations + tech lead | Send through a notification interface that logs messages until the provider is connected |
| Policies (returns, warranty, privacy) | Day 15 | Business + legal | Build pages from CMS/markdown; insert final text when approved |
| Domain and hosting access | Day 4 | Business owner | Use the hosting provider's default staging URL |
| Kinyarwanda translations | Day 15 | Translation owner | Keep all text in translation files so strings can be dropped in late |

## Contingency cuts and next steps

If the team is behind at the Day 10 demo, cut P1 items in this order and protect the P0 purchase path:

1. Advanced reports (keep one daily sales export)
2. Product-level discounts (keep discount codes)
3. SMS (keep email and WhatsApp links)
4. Card payments (keep MoMo, Airtel, COD)
5. Kinyarwanda for admin screens (keep it on the storefront)

Next steps before Monday 26 Oct:

- [ ] Name a person for each RACI role
- [ ] Start the payment merchant application
- [ ] Send the catalogue import template to merchandising
- [ ] Shortlist hosting and confirm stack for the Day 2 decision
- [ ] Set up the project board with the 12 epics
