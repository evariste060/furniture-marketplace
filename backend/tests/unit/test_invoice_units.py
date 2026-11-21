"""Module 16 units: VAT extraction and rounding (ADR-007), invoice numbers, seller-setting rules,
and the PDF renderer (escaping, unsupported characters, page breaks, determinism)."""

from decimal import ROUND_HALF_DOWN, Decimal
from fractions import Fraction

import pytest

from app.core.money import round_half_down, vat_component
from app.models.commerce import MAX_INVOICE_SEQUENCE
from app.models.common import MAX_MONEY_RWF
from app.schemas.settings import SELLER_ADDRESS, SELLER_LEGAL_NAME, SELLER_TIN
from app.services.document_pdf import money, render_delivery_note, render_invoice
from app.services.invoice_service import DeliveryNote, invoice_number
from app.services.settings_service import SETTINGS
from tests.support.pdf import is_complete_pdf, page_count, pdf_text


def reference_vat(total: int) -> int:
    """ADR-007 with Decimal: total × 18 / 118, nearest whole RWF, an exact half down."""
    exact = Decimal(total) * Decimal(18) / Decimal(118)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_DOWN))


# ---- VAT (ADR-007) ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("total", "vat"),
    [
        (0, 0),
        (1, 0),  # 0.1525...
        (3, 0),  # 0.4576... just below a half
        (4, 1),  # 0.6101... just above a half
        (118, 18),  # exact
        (1_180, 180),
        (10_000, 1_525),  # 1525.42...
        (12_000, 1_831),  # 1830.50847... rounds up (above a half)
        (100_000, 15_254),  # 15254.237...
        (MAX_MONEY_RWF, reference_vat(MAX_MONEY_RWF)),
    ],
)
def test_vat_is_extracted_from_the_inclusive_total(total, vat):
    assert vat_component(total) == vat == reference_vat(total)
    assert vat < total or total == 0  # extracted, never added


def test_vat_matches_the_decimal_reference_across_a_wide_range():
    for total in range(0, 50_000):
        assert vat_component(total) == reference_vat(total), total
    for total in range(MAX_MONEY_RWF - 2_000, MAX_MONEY_RWF + 1):
        assert vat_component(total) == reference_vat(total), total


def test_an_exact_half_rounds_down_and_cannot_arise_from_a_whole_rwf_total():
    assert round_half_down(Fraction(1, 2)) == 0
    assert round_half_down(Fraction(3, 2)) == 1
    assert round_half_down(Fraction(5, 2)) == 2
    assert round_half_down(Fraction(51, 100)) == 1
    # total × 18 / 118 has a fractional part of exactly 1/2 only if 18 × total = 118k + 59,
    # which is odd: impossible for a whole total, so the half-down rule never changes a VAT.
    for total in range(0, 118 * 3):
        assert Fraction(total * 18, 118) - (total * 18) // 118 != Fraction(1, 2)


@pytest.mark.parametrize("invalid", [-1, -10_000])
def test_negative_totals_are_refused(invalid):
    with pytest.raises(ValueError):
        vat_component(invalid)


# ---- numbers and seller settings ---------------------------------------------------------------
def test_invoice_numbers_follow_q19():
    assert invoice_number(2026, 1) == "INV-2026-000001"
    assert invoice_number(2026, MAX_INVOICE_SEQUENCE) == "INV-2026-999999"


@pytest.mark.parametrize(
    ("key", "value", "valid"),
    [
        (SELLER_LEGAL_NAME, "Test Electronics Ltd", True),
        (SELLER_LEGAL_NAME, " padded", False),
        (SELLER_LEGAL_NAME, "A", False),
        (SELLER_LEGAL_NAME, "Bell\x07", False),
        (SELLER_LEGAL_NAME, 42, False),
        (SELLER_TIN, "123456789", True),
        (SELLER_TIN, "TIN-12 34", True),
        (SELLER_TIN, "", False),
        (SELLER_TIN, "12/34", False),
        (SELLER_TIN, "1" * 41, False),
        (SELLER_ADDRESS, "KG 7 Ave\nKigali", True),
        (SELLER_ADDRESS, "x", False),
        (SELLER_ADDRESS, "KG 7\tAve", False),
    ],
)
def test_seller_settings_are_validated_when_read(key, value, valid):
    assert SETTINGS[key].valid(value) is valid


# ---- PDF rendering -----------------------------------------------------------------------------
def snapshot(lines: int = 2, **overrides) -> dict:
    data = {
        "version": 1,
        "invoice_number": "INV-2026-000042",
        "issued_at": "2026-10-26T08:00:00+00:00",
        "issued_on": "2026-10-26",
        "currency": "RWF",
        "seller": {
            "legal_name": "Test Electronics <b>Ltd</b> & Co",
            "tin": "TEST-TIN-0001",
            "address": "KG 7 Ave\nKigali",
        },
        "customer": {"name": "Amélie Uwase ☃", "address": ["KG 11 Ave, house 4", "Gasabo"]},
        "order": {
            "number": "ORD-261026-ABCDEF",
            "placed_on": "2026-10-25",
            "payment_method": "mtn_momo",
        },
        "lines": [
            {
                "sku": f"SKU-{i:03d}",
                "description": f"Écouteurs sans fil, line {i} " + "very long name " * 10,
                "quantity": 1,
                "unit_price": 10_000,
                "line_subtotal": 10_000,
                "discount": 0,
                "line_total": 10_000,
            }
            for i in range(lines)
        ],
        "totals": {
            "subtotal": 10_000 * lines,
            "discount": 0,
            "discount_code": None,
            "delivery_fee": 2_000,
            "total": 10_000 * lines + 2_000,
        },
        "vat": {
            "rate_percent": 18,
            "amount": vat_component(10_000 * lines + 2_000),
            "basis": "extracted_from_inclusive_total",
            "rounding": "nearest_whole_rwf_half_down",
        },
    }
    data.update(overrides)
    return data


def test_the_invoice_shows_the_required_fields_and_reconciled_totals():
    snap = snapshot()
    pdf = render_invoice(snap)
    assert is_complete_pdf(pdf)
    text = pdf_text(pdf)
    for expected in (
        "INV-2026-000042",
        "Issue date: 2026-10-26",
        "TIN: TEST-TIN-0001",
        "KG 7 Ave",
        "Order number: ORD-261026-ABCDEF",
        "MTN Mobile Money",
        "Total (VAT inclusive)",
        money(22_000),
        "of which VAT 18%",
        money(vat_component(22_000)),
        "Gasabo",
    ):
        assert expected in text, expected
    assert "EBM" not in text  # no EBM claim (PR-14)


def test_user_text_is_never_markup_and_undrawable_characters_become_question_marks():
    text = pdf_text(render_invoice(snapshot()))
    assert "<b>Ltd</b> & Co" in text.replace("\n", "")  # drawn literally, not as bold markup
    assert "Amélie Uwase ?" in text  # Latin-1 accents kept; the snowman cannot be drawn


def test_long_invoices_break_across_pages_with_totals_at_the_end():
    pdf = render_invoice(snapshot(lines=70))
    assert page_count(pdf) >= 3
    text = pdf_text(pdf)
    assert text.count("Description") == page_count(pdf)  # the header row repeats on each page
    assert text.index(money(702_000)) > text.index("SKU-069")  # totals follow the last line
    assert f"Page {page_count(pdf)}" in text


def test_rendering_is_deterministic():
    assert render_invoice(snapshot()) == render_invoice(snapshot())


def test_the_delivery_note_has_no_prices_or_payment_details():
    note = DeliveryNote(
        order_number="ORD-261026-ABCDEF",
        recipient="Aline <i>Uwase</i>",
        address=["KG 11 Ave, house 4", "Gasabo"],
        lines=[{"sku": "SKU-001", "description": "Phone", "quantity": 2}],
    )
    pdf = render_delivery_note(note)
    assert is_complete_pdf(pdf)
    text = pdf_text(pdf)
    joined = text.replace("\n", "")  # escaped markup is drawn as several literal runs
    assert "Aline <i>Uwase</i>" in joined
    for expected in ("Delivery note", "ORD-261026-ABCDEF", "Gasabo", "SKU-001"):
        assert expected in text, expected
    for absent in ("RWF", "VAT", "Total", "Payment", "Mobile Money", "Cash"):
        assert absent not in text, absent
