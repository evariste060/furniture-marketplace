# RE-026: Pricing Blockers and Readiness

Card: [P0] RE-026 — Build server-side delivery, discount and tax pricing. Requirements: PR-05, PR-11, PR-12, PR-14. QA: TC-06, TC-17 (TC-18 depends on the same tax decisions). Card title, requirement/QA links and prerequisites are as given in the task brief; the card itself could not be read (see below).

**Status update 2026-10-23: B1, B3, B4, B5, B6 and B7 resolved** by the project owner (business owner, also acting as the Finance and Operations owner); B2 partially resolved (VAT rate and inclusion). The final delivery and promotion table columns (B5) were approved with `docs/IMPLEMENTATION_PLAN.md` on 2026-10-23. See "Recorded decisions" below. B2 (EBM scope), B9 and B10 stay as recorded in the register; B10 is not approved and is summarised in the implementation plan for the owner's decision. B9 (runtime grants) is engineering work delivered with each module.

**Original status: Blocked — awaiting approvals and prerequisite verification.** Recorded 2026-10-23 from a repository inspection at commit `3496b39` (`feat/order-fulfilment`); rechecked on `dev` at `53092e1` with no new approvals or prerequisite evidence. Only slice S1 (trusted merchandise subtotal, below) is implemented. No delivery, discount, tax, checkout, migration or permission work was done. Nothing in this record is an approval, and no requirement, prerequisite or QA case is complete.

Why blocked: the Technical Plan's risk register (§7) says to "approve delivery matrix and policies before checkout completion" (Operations) and to obtain a Finance EBM/VAT decision. Its definition of ready (§5) requires agreed acceptance criteria and available data and dependencies. PRD §7 still lists the delivery fee matrix and the VAT/invoice/EBM approach as **TBD**, and ADR-002 is **Proposed** apart from its approved stock lifecycle. Implementing anything beyond S1 now would require inventing a delivery, discount, tax or rounding policy.

**Implementation update 2026-10-24:** B1, B5 and B6 are implemented by module 12 (delivery zones, fee history, the free-delivery threshold setting and the cart delivery quote; `docs/qa/module-12-delivery-acceptance.md`), not yet reviewed or committed. The seed values remain placeholders.

**Implementation update 2026-10-25:** B3 is implemented by module 13 (promotion codes, cart discount, redemption limits and release; `docs/qa/module-13-promotions-acceptance.md`), not yet reviewed or committed. Recording a redemption at checkout waits for module 14. The "minimum order amount" is implemented as the whole merchandise subtotal before discount, without delivery (project owner's implementation decision, 2026-10-25, module 13 D-P2); this record has not yet been formally amended.

**Implementation update 2026-10-25 (module 14):** checkout now prices orders on the server (subtotal, discount, delivery, VAT extracted at 18%, total) in one transaction with the stock holds and the promotion use, and guests look up orders with number + phone (B7); `docs/qa/module-14-checkout-acceptance.md`. Not yet reviewed or committed. Open: the guest lookup rate limit (D-O3) and payments (module 15).

## Recorded decisions (project owner, 2026-10-23)

### B1 — Delivery (resolved)

- Zones: **Gasabo, Kicukiro, Nyarugenge** (Kigali). No delivery outside Kigali in the MVP.
- One flat fee per zone, editable by administrators. **Placeholder** seed values, to be replaced with approved values before launch: Nyarugenge 1 500 RWF, Kicukiro 2 000 RWF, Gasabo 2 000 RWF.
- Free delivery when the merchandise subtotal **after discount** is at least the threshold. The threshold is stored as an editable setting, not in code. **Placeholder** seed value, to be replaced before launch: 200 000 RWF.
- Cash on delivery is available in all three zones.
- The delivery fee is VAT-inclusive, like product prices.

### B3 — Promotions (resolved)

- Discount codes are a percentage (whole percent, 1–100) or a fixed amount (whole RWF). One code per order; no stacking.
- A code applies to the merchandise subtotal only, never to the delivery fee. It can target all products, or specific categories, brands or products.
- Optional per code: minimum order amount, maximum discount amount, start and end dates, total usage limit, per-customer usage limit.
- A discount never makes a total negative.
- A code counts as used when the order is placed. The use is released if the order is cancelled before dispatch.
- The order discount is split across the eligible order lines in proportion to each line's amount; any rounding remainder goes to the largest line, so the line discounts add up exactly to the order discount.
- Per-customer limit for guest checkout: counted by phone number.
- A category target includes all of its subcategories.
- An unpaid order whose reservation expires releases its code, the same as a cancellation.
- Promotion start and end dates are in Africa/Kigali time.
- Not covered by this decision: whether `compare_at_price` drives a discount (ADR-002 point 5), and whether PR-12's "product discounts" means discounts applied without a code. Both are listed in the implementation plan's open questions.

### B4 — Money (resolved; see [ADR-007](ADR-007-money-representation-and-rounding.md))

- All money is stored as whole RWF in `BIGINT` columns; every `Numeric(14, 2)` money column is migrated. A maximum-amount cap is kept.
- One rounding, on the final line or order amount, to the nearest whole RWF; halves are rounded down (customer's favour).
- Prices are VAT-inclusive. Invoices show 18% VAT as an extracted component.

### B2 — Tax (partially resolved)

- Resolved by the B4 decision: VAT rate 18%, prices VAT-inclusive, VAT shown as an extracted component on invoices.
- Resolved 2026-10-23: the delivery fee is VAT-inclusive.
- Still open: EBM scope and approach; per-line or per-order VAT display on the invoice. No EBM claim until implemented and verified (PR-14).

### B5 — Delivery and promotion schema (resolved)

- Approved on 2026-10-23 together with `docs/IMPLEMENTATION_PLAN.md`, which lists the final columns (modules 12 and 13).

### B6 — Who may change delivery and promotion configuration (resolved)

- Only administrators may create, edit, activate or deactivate delivery zones, fees, the free-delivery threshold and promotions. Management may view them. Other roles have no access.

### B7 — Guest checkout (resolved)

- Guest carts are owned through a cart token (only its hash is stored, as `carts.guest_token_hash` already provides).
- Guests look up an order with its order number plus the order's phone number.

### B10 — Prerequisites RE-006, RE-007, RE-016 (not approved)

- Not recorded as approved. Their scope could not be found in the repository, commit history or requirement documents; the implementation plan records this for the owner's decision.

## Policy constraints (apply until each decision below is recorded)

> Since 2026-10-23 the delivery, discount and money constraints below are superseded by the recorded decisions above, but only for the points those decisions cover. They still apply to the points listed there as open.

- Do not invent or seed delivery zones, coverage, fees, free-delivery thresholds or a delivery partner.
- Do not invent discount codes, amounts, eligibility, stacking, caps, usage limits, validity windows or an expiry timezone.
- Do not invent a VAT rate, tax-inclusive or tax-exclusive pricing, a calculation basis, invoice tax presentation or rounding. No default fee, discount or tax rate may be substituted for a missing value.
- Do not claim RRA EBM integration until it is implemented and verified (PR-14).
- Prices, discounts, delivery fees, tax and totals are always recomputed on the server from trusted database values. Client-submitted amounts are never trusted (AGENTS.md; ADR-002 ‘Integrity rules and indexes’).
- Order-time pricing is saved as an immutable snapshot (ADR-002 ‘Relationships and transactional boundaries’).
- Existing approved behavior stays unchanged, including the ADR-002 stock lifecycle. Cancelling an order with committed (paid) stock returns 409.

## Prerequisite verification

The Trello board's JSON endpoint (`https://trello.com/b/yjoXwPEK.json`) returned **HTTP 401** on 2026-10-23, and the requirements README already records failed board access. Card status is therefore unknown. It must not be inferred from tables or code in this repository.

| Card | Evidence found | Status | Needed to clear |
| --- | --- | --- | --- |
| RE-006 | None. No mention in repository documents, commit messages or PRs #1–#9. | **Unknown** (scope and status) | Card content plus linked completion evidence from its owner. Confirm what it delivers and which part RE-026 depends on. |
| RE-007 | None. No mention in repository documents, commit messages or PRs #1–#9. | **Unknown** (scope and status) | Same as RE-006. |
| RE-016 | PR #4 (catalogue, RE-018) says "Prerequisites RE-002 and RE-016 remain unverified; their completion must not be assumed." No later evidence. | **Unverified** | Card content plus linked completion evidence from its owner. |

- [ ] RE-006 scope and completion evidence obtained
- [ ] RE-007 scope and completion evidence obtained
- [ ] RE-016 scope and completion evidence obtained
- [ ] Blockers recorded on the project board (Technical Plan §5). This was not possible because of the 401.

## Blocker register

Owner roles come from PRD §7, ADR-002, the Technical Plan RACI, and the RE-004 plan. Named individuals are unassigned in all sources ("one named individual should be assigned to each role at kickoff").

| # | Decision or dependency | Accountable owner (role) | Evidence currently available | Resolution evidence required | Affects |
| --- | --- | --- | --- | --- | --- |
| B1 | Delivery zones and coverage, fee matrix, free-delivery threshold, delivery-partner policy | Operations (PRD §7); individual unassigned | PRD §7: "TBD". ADR-002 delivery row: geography, matrix, threshold and partner "explicitly TBD". Schema has `delivery_zones` and `delivery_fee_rules` only. | Written Operations decision: zone coverage definition, fee per zone (or approved calculation basis), threshold, partner and handoff. Include worked fee examples. | PR-05, PR-11; TC-06, TC-17 |
| B2 | VAT rate and treatment, tax-inclusive or tax-exclusive prices, line or order calculation basis, tax rounding, invoice presentation, EBM scope | Finance (PRD §7; RACI A/R for policy); individual unassigned | PRD §7: "TBD". PR-14 requires Finance approval before release. ADR-002 money section: tax inclusion, basis, rounding, VAT display, invoice fields and EBM path unresolved. | Written Finance decision with example orders reconciled across line, discount, delivery, tax, total and invoice. Include an EBM scope statement (required or not, and approach). | PR-05, PR-14; TC-06, TC-18 |
| B3 | Discount scope (line or order), allocation to lines and residuals, stacking, caps, per-customer and global usage limits, eligibility, expiry and timezone, product discounts, compare-at price meaning | Business owner (ADR-002); Finance for financial treatment; individuals unassigned | ADR-002 PR-12 row: "Stacking, scope, expiry timezone, usage limits, rounding and eligibility rules unresolved". Schema has `discounts` (percent/fixed), `discount_targets` and `discount_redemptions` only. | Written discount policy with worked examples: eligibility, limit and validity boundaries, line allocation and residuals, product discounts, compare-at semantics. | PR-05, PR-12; TC-06 |
| B4 | RWF precision (whole RWF or fixed decimal) and rounding at unit, line, tax and order-total stages | Finance for policy; engineering lead for representation after the policy (ADR-002) | ADR-002 money section: unresolved. Existing columns are `Numeric(14, 2)` with `currency_code = 'RWF'`. That is a proposed schema, not an approved precision. | Recorded precision and rounding rule per stage, then an engineering decision confirming or migrating the column representation. | PR-05, PR-14; TC-06, TC-18 |
| B5 | Delivery and promotion schema (zones, fee rules, discounts, targets, redemptions, order pricing snapshot fields) | Technical Product Lead accountable; engineering lead responsible (Technical Plan RACI) | ADR-002 status: "Proposed for explicit approval, except the stock reservation lifecycle approved on 2026-10-22". | Recorded ADR-002 approval (or conditional approval) covering these tables and snapshot fields, with approver and date. | PR-05, PR-11, PR-12, PR-14 |
| B6 | Who may create, update, activate and deactivate delivery and promotion configuration | Authorization owner: unassigned. ADR-006 records project-owner approvals only for the permissions it lists; `orders:fulfil` exists in code but is not among them. | ADR-006 staff permission matrix: permissions "exist only for built features". No delivery or promotion permission exists in `app/core/roles.py`. | Approved permission entries (role → action) recorded in ADR-006, with allow and deny test expectations. | PR-11, PR-12, PR-15; TC-16 |
| B7 | Guest cart ownership and secure guest-order lookup | Checkout requirements owner: unassigned. Business plus finance/legal adviser for privacy (RE-004 plan) | ADR-002 PR-05 row: guest cart/session ownership and secure guest-order retrieval unresolved. RE-004 plan: "do not invent authentication". | Written guest checkout policy (cart ownership, retrieval method, lifetime, retention) and a security review. | PR-05, PR-06, PR-15; TC-06 |
| B8 | Checkout and pricing services and endpoints | Engineering lead (RACI R); depends on B1–B7 | `docs/api/endpoint-inventory.md`: no cart, checkout, order-creation, delivery-quote, discount or tax route exists. Reservations are created only by internal services and tests. | Implemented checkout with server-side totals, meeting the readiness checklist below. | PR-05, PR-11, PR-12, PR-14; TC-06, TC-17 |
| B9 | Runtime database access to pricing tables | Engineering lead; reviewed with B6 | ADR-006 allow-list and `scripts/provision_runtime_role.py` grant nothing on delivery, fee, discount or cart tables. | Grants added only for tables and privileges the approved implementation uses, pinned by `tests/unit/test_runtime_role_grants.py`-style tests, with ADR-006 updated. | PR-15 |
| B10 | Prerequisites RE-006, RE-007, RE-016 | Card owners: unknown (board unreadable) | See the prerequisite table above. | Linked completion evidence for each. | RE-026 as a whole |

Existing delivery, fee and discount tables are an unapproved schema proposal. They are not a working or approved pricing implementation.

## Implementation progress

| Slice | Status | Evidence |
| --- | --- | --- |
| S1 — trusted merchandise subtotal | **Implemented and tested** (2026-10-23) | See below |
| S2 delivery, S3 discounts, S4 tax, S5 checkout, S6 QA | **Blocked** (B1–B10) | None; not started |

S1 is an internal service. It adds no endpoint, migration, permission or database grant.
- `backend/app/services/pricing.py`: `quote_merchandise(session, lines)` takes `(variant_id, quantity)` pairs.
  - SKU ids must be UUIDs. Quantities must be whole numbers from 1 to the PostgreSQL integer maximum. A SKU may appear only once.
  - Sellability and availability reuse the inventory service's sellable-SKU and quantity checks and the catalogue availability query (on hand − unavailable − active − committed).
  - Unit prices are read from `product_variants.price`; `compare_at_price` is ignored.
  - Line and merchandise subtotals are whole-RWF integers (ADR-007; changed from `Decimal`/`Numeric(14, 2)` on 2026-10-23), so price × quantity needs no rounding. Amounts above the 999 999 999 999 RWF cap are rejected.
  - The quote is read-only and takes no locks. Its reads are separate statements, so a concurrent catalogue or stock change can land between them. Checkout (S5) must therefore reprice inside its order transaction, where order creation re-checks sellability and stock under row locks.
  - The sellable-SKU and quantity checks are the inventory service's public `check_sellable` and `check_quantity` (made public 2026-10-23 with the module owner's approval). They are reused, not copied, so the rules cannot drift.
  - `MerchandiseQuote.order_total()` raises `PricingPolicyNotApproved`, so delivery, discount and tax are never defaulted to zero.
- `backend/app/schemas/pricing.py`: request contract with `extra="forbid"`. Any client price, subtotal, discount, fee, tax, total or currency field is rejected, and duplicate SKU lines are rejected.
- Tests (all passed on 2026-10-23):
  - `tests/unit/test_pricing_units.py`: 36 tests covering tampered amount and total fields, invalid quantities, non-UUID SKU ids, duplicate and empty lines, and the order total failing closed.
  - `tests/integration/test_pricing.py`: 18 PostgreSQL tests covering whole-RWF integer amounts, database price changes, tampering, unknown SKUs, non-sellable variant/product/category/brand, invalid quantities, duplicates, a missing inventory record, active, committed and unavailable units, released holds, the amount range, and no writes.
  - `tests/postgres/test_pg_pricing.py`: 1 test showing the quote works on the least-privilege runtime role with existing grants.

S1 contributes to PR-05 and TC-06 (server-side subtotal; client amounts rejected). It does not satisfy them: delivery, fees, discount and tax treatment, and checkout are still missing. TC-06 and TC-17 remain "Not run". Since 2026-10-23 S1 uses whole-RWF integers (B4, ADR-007).

## Decision-resolution sequence

Items within step 2 can run in parallel. A later step must not start on an assumed answer from an earlier one.

1. **Prerequisites and ownership:** obtain RE-006, RE-007 and RE-016 evidence (B10). Assign named individuals to the Operations, Finance, business-owner and authorization roles.
2. **Policy decisions (parallel):** Operations delivery policy (B1); Finance tax, invoice and EBM policy (B2); business-owner discount policy (B3); guest checkout policy (B7).
3. **Money representation (B4):** after B2 and B3, Finance fixes rounding per stage, then the engineering lead confirms the numeric representation.
4. **Schema approval (B5):** after steps 2–3, ADR-002 approval for the pricing tables and order snapshot fields, plus any migration they require.
5. **Authorization (B6) and runtime access (B9):** record the permission entries in ADR-006 and plan the least-privilege grants.
6. **Implementation (B8):** build pricing and checkout against the recorded decisions only.
7. **Verification:** run automated and manual QA for TC-06 and TC-17 (and TC-18 once invoice work exists) using the approved worked examples. Record evidence in `docs/qa/`.

## Implementation-readiness checklist

Every item stays unchecked until evidence is linked. Do not start step 6 above while any decision item is unchecked.

Decisions
- [x] B1 delivery policy recorded (2026-10-23; worked fee examples still to be added with the delivery module tests)
- [ ] B2 tax, invoice and EBM policy recorded by Finance, with reconciled example orders (VAT rate and inclusion recorded 2026-10-23; EBM scope open)
- [x] B3 discount policy recorded (2026-10-23; worked examples still to be added with the promotions module tests; open points listed above)
- [x] B4 precision and rounding per stage recorded (2026-10-23, ADR-007)
- [x] B5 ADR-002 approval covering pricing tables and snapshots (2026-10-23, with `docs/IMPLEMENTATION_PLAN.md`)
- [x] B7 guest checkout policy recorded (2026-10-23; security review still due with the cart and checkout modules)
- [ ] B10 prerequisites verified

Authorization
- [ ] B6 permission entries approved and recorded in ADR-006 (decision recorded above 2026-10-23; ADR-006 entry added with the role and permission update)
- [ ] Server-side permission checks on every configuration endpoint, not only in the UI
- [ ] Allow and deny tests for each staff role and for customers (TC-16 pattern)

Migrations and data
- [ ] Alembic revisions reviewed with a single head and a tested upgrade and downgrade path (or a documented forward fix)
- [ ] No seeded zones, fees, discounts or tax rates unless supplied by the approving owner
- [ ] Runtime grants limited to used privileges and pinned by tests (B9)

Server-side totals
- [ ] Unit prices read from trusted variant rows; quantities and availability validated under the approved stock lifecycle
- [ ] Discount, delivery fee and tax computed only from recorded rules
- [ ] Client-submitted prices, discounts, fees, taxes and totals ignored or rejected
- [ ] Totals non-negative, with no repeated discount application, using exact whole-RWF integer arithmetic (ADR-007)
- [ ] Order, redemption, pricing snapshot and reservation written in one transaction; a failure leaves nothing partial
- [ ] API response amounts equal persisted order amounts

Tests
- [ ] Unit tests for each approved formula and rounding boundary
- [ ] PostgreSQL integration tests for valid, invalid, inactive and missing configuration, tampering, limits and concurrency
- [ ] Real-HTTP tests on the runtime role for checkout and configuration endpoints
- [ ] Regression: order fulfilment flow, and 409 when cancelling committed stock
- [ ] Each test mapped to PR-05, PR-11, PR-12, PR-14, TC-06 or TC-17

API documentation and QA
- [ ] Endpoint inventory, OpenAPI descriptions and admin configuration instructions updated
- [ ] Pricing formula and order-total rules documented from the approved decisions
- [ ] Manual QA script for TC-06 and TC-17 executed, with evidence recorded in `docs/qa/` (executed vs pending clearly separated)
- [ ] No EBM claim without implementation and verification evidence

## Sources

- [Product Requirements Document](../01_Product_Requirements_Document.docx): PR-05, PR-11, PR-12, PR-14 and §7 key business decisions.
- [Technical Delivery and Implementation Plan](../02_Technical_Delivery_and_Implementation_Plan.docx): §4 RACI, §5 workflow and definition of ready, §6 implementation requirements, risk register (§7) (delivery fees, EBM/VAT).
- [QA, UAT and Go-Live Checklist](../03_QA_UAT_and_Go_Live_Checklist.docx): TC-05, TC-06, TC-16, TC-17, TC-18 (all "Not run").
- [ADR-002](ADR-002-database-schema-and-inventory-policy.md): status, Discount/Delivery entity rows, money section, traceability rows for PR-05/11/12/14.
- [ADR-006](ADR-006-authentication-security-controls.md): staff permission matrix and runtime role allow-list.
- [RE-004 decision resolution plan](RE-004-decision-resolution-plan.md), [endpoint inventory](../api/endpoint-inventory.md), [requirements README](../requirements/README.md); PR #4 description (RE-016).
