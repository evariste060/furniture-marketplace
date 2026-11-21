"""Whole-RWF rounding and VAT extraction (ADR-007, confirmed by the project owner 2026-10-23).

- Round once, on the final amount, to the nearest whole RWF; an exact half goes down (in the
  customer's favour). Intermediate values stay exact (fractions).
- Prices and the delivery fee are VAT-inclusive; VAT is shown as a component extracted from the
  inclusive amount: VAT = amount × 18 / 118, rounded by the same rule. It never changes what the
  customer pays.
"""

from fractions import Fraction

VAT_RATE_PERCENT = 18  # ADR-007 / RE-026 B2


def round_half_down(value: Fraction) -> int:
    """Nearest whole number; an exact half goes down (ADR-007). Only non-negative values."""
    if value < 0:
        raise ValueError("only non-negative amounts are rounded")
    whole = value.numerator // value.denominator
    return whole + 1 if value - whole > Fraction(1, 2) else whole


def vat_component(inclusive_amount: int) -> int:
    """The VAT included in a VAT-inclusive whole-RWF amount (ADR-007)."""
    if inclusive_amount < 0:
        raise ValueError("amounts are never negative")
    return round_half_down(Fraction(inclusive_amount * VAT_RATE_PERCENT, 100 + VAT_RATE_PERCENT))
