# ADR-007: Money representation, rounding and VAT display

Status: **Accepted (project owner, 2026-10-23)** for the decisions marked *Approved*. The project owner is the business owner and also acts as the Finance and Operations owner for this project. Items under "Still open" are not approved and must not be implemented on an assumed answer.

Context: ADR-002 ("Money and pricing decisions requiring approval") and RE-026 blocker B4 left amount precision, rounding and tax inclusion open. The existing schema stores every amount as `Numeric(14, 2)` with `currency_code = 'RWF'`, and the merchandise pricing service (RE-026 S1) uses exact `Decimal` arithmetic in that representation. This ADR records the owner's decision and the engineering consequences. It supersedes ADR-002's money section where they differ.

## Approved decisions

| Area | Decision |
| --- | --- |
| Currency | RWF only for the MVP (existing `currency_code = 'RWF'` checks stay). |
| Storage | Every money amount is a whole number of RWF stored as `BIGINT` (SQLAlchemy `BigInteger`, Python `int`). No fractional RWF is stored anywhere. Binary floating point is never used. |
| Maximum amount | A maximum-amount cap is kept. Engineering value: **999 999 999 999 RWF** per stored amount (the integer range of the previous `Numeric(14, 2)` columns), enforced by the pricing service and by `CHECK` constraints. |
| Rounding | Only where a calculation can produce a fraction (percentage discounts, VAT extraction). Round **once**, on the final line or order amount, to the nearest whole RWF; an exact half is rounded **down**, in the customer's favour. Intermediate values stay exact (integer or `Fraction`/`Decimal` with traps); they are never rounded step by step. |
| Tax inclusion | Prices are **VAT-inclusive**. The customer pays the displayed price; VAT is not added on top. |
| VAT display | Invoices show VAT at **18%** as a component extracted from the inclusive amount: `VAT = amount × 18 / 118`, rounded by the rule above. No RRA EBM claim is made until EBM is implemented and verified (PR-14). |

### How "in the customer's favour" is applied (confirmed by the project owner, 2026-10-23)

The rounding rule is applied to the amount the customer **pays**, not to the discount itself, so that a half RWF always goes to the customer:

- Percentage discount: `payable = round_half_down(eligible_subtotal × (100 − percent) / 100)`, `discount = eligible_subtotal − payable`. Example: 10% off 1 005 RWF → exact payable 904.5 → **904**; discount **101**.
- If the rule were applied to the discount amount instead, the same order would get a discount of 100 and pay 905, which is not in the customer's favour. This ADR therefore uses the payable-amount reading.
- VAT extraction does not change what the customer pays; the same nearest/half-down rule gives the displayed VAT component.

## Columns that change from `Numeric(14, 2)` to `BIGINT`

| Table | Columns |
| --- | --- |
| `product_variants` | `price`, `compare_at_price` |
| `orders` | `subtotal`, `discount_total`, `delivery_fee`, `tax_total`, `total` |
| `order_items` | `unit_price`, `line_subtotal`, `discount_amount`, `tax_amount`, `line_total` |
| `payment_attempts` | `amount` |
| `delivery_fee_rules` | `fee` |
| `discount_redemptions` | `amount` |
| `discounts` | `value` is replaced by `percent_off` (integer) and `amount_off` (BIGINT); see "Further approved decisions" |

## Consequences

Implemented 2026-10-23 in migration `528e6436c34e` (implementation plan step A2).

- One Alembic revision converts the columns. The upgrade **aborts** if any existing value has a fractional part, rather than rounding stored data silently; the downgrade converts back to `Numeric(14, 2)` without loss. Existing `CHECK` constraints are kept and the maximum-amount check is added.
- `app/services/pricing.py` and its tests move from `Decimal` to `int`; `MAX_AMOUNT` becomes `999_999_999_999`.
- Public API amounts change type: catalogue `price`/`compare_at_price` and the `min_price`/`max_price` filters become integers (Pydantic currently serialises `Decimal` as a JSON string such as `"1500.00"`; it becomes the number `1500`). The frontend does not read prices yet (checked 2026-10-23), so no frontend change is needed now; any later client must treat amounts as integers.
- Seeds, fixtures and tests that use decimal amounts are updated.

## Further approved decisions (project owner, 2026-10-23)

- The rounding reading above (round the amount the customer pays, halves down) is confirmed.
- Percentages are whole numbers (1–100). `discounts.value` is replaced by two typed columns, `percent_off` (integer) and `amount_off` (BIGINT RWF), with a check that exactly the one matching `kind` is set.
- The delivery fee is VAT-inclusive, like product prices, so the VAT extracted on the invoice covers it.
- An order-level discount is split across eligible lines in proportion to each line's amount; the rounding remainder goes to the largest line so `order_items.discount_amount` adds up exactly to `orders.discount_total`.

## Still open

- Whether VAT is shown per invoice line, per order, or both; and whether `order_items.tax_amount` is populated per line or left at zero with VAT held at order level.
- EBM scope (required or not, and approach) remains with Finance (RE-026 B2).

## References

- [ADR-002](ADR-002-database-schema-and-inventory-policy.md) money section (superseded where different)
- [RE-026 pricing blockers and readiness](RE-026-pricing-blockers-and-readiness.md), B2 and B4
