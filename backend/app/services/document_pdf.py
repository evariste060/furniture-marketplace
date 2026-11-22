"""Invoice and delivery-note PDFs (module 16), rendered in memory with ReportLab.

Rendering only: the invoice comes from its stored snapshot and the delivery note from
app.services.invoice_service.DeliveryNote; nothing here reads the database. Every value is
treated as text: it is XML-escaped before ReportLab's paragraph markup sees it, and characters
the built-in Helvetica fonts cannot draw (outside Windows-1252, which covers English, French and
Kinyarwanda) are replaced with "?" rather than dropped silently. Tables split across pages and
repeat their header row. Output is deterministic (no creation date or random document ID) and
is checked to be a complete PDF before it is returned.
"""

from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.invoice_service import DeliveryNote

PAYMENT_METHODS = {
    "mtn_momo": "MTN Mobile Money",
    "airtel_money": "Airtel Money",
    "cash_on_delivery": "Cash on delivery",
    "card": "Card",
}

_styles = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=9, leading=12)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8, leading=10)
RIGHT = ParagraphStyle("right", parent=BODY, alignment=2)
TITLE = ParagraphStyle("title", parent=_styles["Title"], fontSize=18, leading=22, alignment=0)
HEADING = ParagraphStyle("heading", parent=BODY, fontName="Helvetica-Bold")


class RenderError(RuntimeError):
    """The renderer produced no complete PDF."""


def _drawable(value: Any) -> str:
    """Characters the built-in fonts can draw; anything else becomes "?"."""
    return str(value).encode("cp1252", errors="replace").decode("cp1252")


def _safe(value: Any) -> str:
    """Plain text for a paragraph: drawable characters only, markup escaped, line breaks kept."""
    return escape(_drawable(value)).replace("\n", "<br/>")


def _p(value: Any, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(_safe(value), style)


def money(amount: int) -> str:
    return f"{amount:,} RWF"


def _footer(label: str):
    def draw(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(doc.leftMargin, 10 * mm, _drawable(label))
        canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _build(story: list, title: str, footer: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="",
        subject="",
        creator="",
        invariant=1,
    )
    draw = _footer(footer)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    data = buffer.getvalue()
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
        raise RenderError("incomplete PDF")
    return data


def _grid(rows: list[list[Any]], widths: list[float], numeric_from: int) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (numeric_from, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    return table


def render_invoice(snapshot: dict[str, Any]) -> bytes:
    """The invoice PDF of a stored snapshot (version 1)."""
    seller, customer, order = snapshot["seller"], snapshot["customer"], snapshot["order"]
    totals, vat = snapshot["totals"], snapshot["vat"]
    number = snapshot["invoice_number"]
    head = Table(
        [
            [
                [
                    _p(seller["legal_name"], HEADING),
                    _p(f"TIN: {seller['tin']}"),
                    _p(seller["address"]),
                ],
                [
                    _p(f"Invoice number: {number}", HEADING),
                    _p(f"Issue date: {snapshot['issued_on']}"),
                    _p(f"Order number: {order['number']}"),
                    _p(f"Order date: {order['placed_on']}"),
                    _p(
                        "Payment method: "
                        + PAYMENT_METHODS.get(order["payment_method"], order["payment_method"])
                    ),
                ],
            ]
        ],
        colWidths=[95 * mm, 85 * mm],
    )
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    lines = [["Description", "SKU", "Qty", "Unit price", "Discount", "Amount"]]
    for line in snapshot["lines"]:
        # Invoices issued before ADR-014 phase 3 have no store in their snapshot.
        store = line.get("store_name")
        description = f"{line['description']} (sold by {store})" if store else line["description"]
        lines.append(
            [
                _p(description),
                _p(line["sku"], SMALL),
                str(line["quantity"]),
                money(line["unit_price"]),
                money(line["discount"]),
                money(line["line_total"]),
            ]
        )
    discount_label = "Discount"
    if totals.get("discount_code"):
        discount_label += f" ({totals['discount_code']})"
    summary = [
        ["Subtotal", money(totals["subtotal"])],
        [_p(discount_label, RIGHT), f"-{money(totals['discount'])}"],
        ["Delivery fee", money(totals["delivery_fee"])],
        ["Total (VAT inclusive)", money(totals["total"])],
        [f"of which VAT {vat['rate_percent']}%", money(vat["amount"])],
    ]
    summary_table = Table(summary, colWidths=[140 * mm, 40 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("LINEABOVE", (0, 3), (-1, 3), 0.5, colors.black),
            ]
        )
    )
    story = [
        _p("Invoice", TITLE),
        head,
        Spacer(1, 6 * mm),
        _p("Bill to", HEADING),
        _p(customer["name"]),
        *[_p(part) for part in customer["address"]],
        Spacer(1, 6 * mm),
        _grid(lines, [70 * mm, 30 * mm, 12 * mm, 24 * mm, 20 * mm, 24 * mm], numeric_from=2),
        Spacer(1, 4 * mm),
        summary_table,
        Spacer(1, 4 * mm),
        _p(
            f"Prices include VAT at {vat['rate_percent']}%. The VAT shown is the component "
            "contained in the total; it is not added to it.",
            SMALL,
        ),
    ]
    return _build(story, title=f"Invoice {number}", footer=f"Invoice {number}")


def render_delivery_note(note: DeliveryNote) -> bytes:
    """The delivery-note PDF: order number, recipient, delivery address and items only."""
    lines = [["Description", "SKU", "Qty"]]
    for line in note.lines:
        lines.append([_p(line["description"]), _p(line["sku"], SMALL), str(line["quantity"])])
    story = [
        _p("Delivery note", TITLE),
        _p(f"Order number: {note.order_number}", HEADING),
        Spacer(1, 4 * mm),
        _p("Deliver to", HEADING),
        _p(note.recipient),
        *[_p(part) for part in note.address],
        Spacer(1, 6 * mm),
        _grid(lines, [110 * mm, 50 * mm, 20 * mm], numeric_from=2),
    ]
    title = f"Delivery note {note.order_number}"
    return _build(story, title=title, footer=title)
