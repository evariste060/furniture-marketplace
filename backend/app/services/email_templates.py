"""Transactional message templates (docs/deployment/email.md): an HTML email, its plain-text
alternative and a short SMS text for every message the outbox sends, plus the password reset
code, the email verification link, and one template whose business workflow does not exist yet
(refund acknowledgement; see PENDING_TEMPLATES).

Pure functions of plain data: no database or network, so every template is rendered the same
way in tests. The brand is the MARKETPLACE_NAME setting (ADR-014 decision 16), read once.
Every value is HTML-escaped. The HTML is table-based with inline styles
(email clients ignore stylesheets) and reads as one column on a phone. Links are built by the
caller from SITE_URL; without it (None) a message carries no button and no link.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape

from app.core.config import get_settings

BRAND = get_settings().marketplace_name
NAVY = "#0d2d52"
PRIMARY = "#0866f5"
TEXT = "#1b2b3a"
MUTED = "#5b6b7c"
BORDER = "#dbe4ee"
PAGE = "#f5f8fc"

PAYMENT_METHODS = {
    "mtn_momo": "MTN Mobile Money",
    "airtel_money": "Airtel Money",
    "card": "Card",
    "cash_on_delivery": "Cash on delivery",
}

# Templates ready for workflows that do not exist yet. Nothing records these messages: no
# event is invented for them (docs/deployment/email.md, "Pending integrations").
PENDING_TEMPLATES = ("refund_acknowledged",)


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str
    sms: str  # one short line for the SMS channel; no links or codes beyond the order number


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class OrderLine:
    name: str
    variant: str | None
    quantity: int
    unit_price: int
    line_total: int


@dataclass(frozen=True)
class OrderSummary:
    number: str
    customer_name: str
    lines: Sequence[OrderLine]
    subtotal: int
    discount_total: int
    delivery_fee: int
    tax_total: int
    total: int
    payment_method: str | None = None
    discount_label: str | None = None
    delivery_zone: str | None = None
    address_lines: Sequence[str] = field(default_factory=tuple)
    phone: str | None = None
    email: str | None = None
    note: str | None = None


def money(amount: int) -> str:
    """580000 -> "RWF 580,000", as on the storefront (whole RWF, ADR-007)."""
    return f"RWF {amount:,}"


def payment_label(method: str | None) -> str | None:
    return PAYMENT_METHODS.get(method or "", method)


# ---- building blocks -----------------------------------------------------------------------
def _p(text: str, *, muted: bool = False, size: int = 15) -> str:
    color = MUTED if muted else TEXT
    return (
        f'<p style="margin:0 0 14px;font-size:{size}px;line-height:1.55;color:{color};">'
        f"{escape(text)}</p>"
    )


def _button(link: Link | None) -> str:
    if link is None:
        return ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px 0 22px;"><tr>'
        f'<td style="border-radius:10px;background:{PRIMARY};">'
        f'<a href="{escape(link.url, quote=True)}" target="_blank" '
        'style="display:inline-block;padding:13px 26px;font-size:15px;font-weight:600;'
        f'color:#ffffff;text-decoration:none;border-radius:10px;">{escape(link.label)}</a>'
        "</td></tr></table>"
    )


def _rows(rows: Sequence[tuple[str, str]], *, bold_last: bool = False) -> str:
    cells = []
    for index, (label, value) in enumerate(rows):
        last = bold_last and index == len(rows) - 1
        weight = "700" if last else "400"
        top = f"border-top:1px solid {BORDER};" if last else ""
        cells.append(
            f'<tr><td style="padding:6px 0;font-size:14px;color:{MUTED};{top}">{escape(label)}'
            f'</td><td align="right" style="padding:6px 0;font-size:14px;font-weight:{weight};'
            f'color:{TEXT};{top}">{escape(value)}</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 18px;">{"".join(cells)}</table>'
    )


def _heading(text: str) -> str:
    return (
        f'<h2 style="margin:22px 0 10px;font-size:15px;font-weight:700;color:{NAVY};">'
        f"{escape(text)}</h2>"
    )


def _layout(title: str, preheader: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title></head>"
        f'<body style="margin:0;padding:0;background:{PAGE};">'
        f'<div style="display:none;max-height:0;overflow:hidden;">{escape(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{PAGE};"><tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;font-family:Arial,Helvetica,sans-serif;">'
        f'<tr><td style="background:{NAVY};border-radius:14px 14px 0 0;padding:18px 24px;'
        f'font-size:18px;font-weight:700;color:#ffffff;">{escape(BRAND)}</td></tr>'
        f'<tr><td style="background:#ffffff;border:1px solid {BORDER};border-top:0;'
        f'border-radius:0 0 14px 14px;padding:26px 24px 10px;">'
        f'<h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:{NAVY};">'
        f"{escape(title)}</h1>{body}</td></tr>"
        f'<tr><td style="padding:16px 8px;font-size:12px;line-height:1.5;color:{MUTED};" '
        f'align="center">{escape(BRAND)}, Kigali, Rwanda. You received this email because of '
        "an account, order or request on our shop.</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def _text(title: str, paragraphs: Sequence[str], link: Link | None) -> str:
    parts = [title, "", *[p for p in paragraphs if p is not None]]
    if link is not None:
        parts += ["", f"{link.label}: {link.url}"]
    parts += ["", "--", BRAND]
    return "\n".join(parts).replace("\n\n\n", "\n\n")


def _order_rows(order: OrderSummary) -> list[tuple[str, str]]:
    rows = [("Subtotal", money(order.subtotal))]
    if order.discount_total:
        label = f"Discount ({order.discount_label})" if order.discount_label else "Discount"
        rows.append((label, f"-{money(order.discount_total)}"))
    rows.append(("Delivery", money(order.delivery_fee) if order.delivery_fee else "Free"))
    if order.tax_total:
        rows.append(("Tax", money(order.tax_total)))
    rows.append(("Total", money(order.total)))
    return rows


def _line_label(line: OrderLine) -> str:
    return f"{line.name} ({line.variant})" if line.variant else line.name


def _order_html(order: OrderSummary, *, contact: bool) -> str:
    lines = _rows(
        [(f"{line.quantity} x {_line_label(line)}", money(line.line_total)) for line in order.lines]
    )
    body = _heading("Items") + lines + _rows(_order_rows(order), bold_last=True)
    details: list[tuple[str, str]] = [("Order number", order.number)]
    if order.payment_method:
        details.append(("Payment", payment_label(order.payment_method) or ""))
    if order.delivery_zone:
        details.append(("Delivery zone", order.delivery_zone))
    body += _heading("Order details") + _rows(details)
    if order.address_lines:
        body += _heading("Delivery address") + "".join(
            _p(line, size=14) for line in order.address_lines
        )
    if contact:
        who = [order.customer_name, order.phone or "", order.email or ""]
        body += _heading("Customer") + "".join(_p(v, size=14) for v in who if v)
    if order.note:
        body += _heading("Note") + _p(order.note, size=14)
    return body


def _order_text(order: OrderSummary, *, contact: bool) -> list[str]:
    lines = [
        f"- {line.quantity} x {_line_label(line)}: {money(line.line_total)}" for line in order.lines
    ]
    totals = [f"{label}: {value}" for label, value in _order_rows(order)]
    parts = ["Items:", *lines, "", *totals, "", f"Order number: {order.number}"]
    if order.payment_method:
        parts.append(f"Payment: {payment_label(order.payment_method)}")
    if order.delivery_zone:
        parts.append(f"Delivery zone: {order.delivery_zone}")
    if order.address_lines:
        parts += ["", "Delivery address:", *order.address_lines]
    if contact:
        parts += [
            "",
            "Customer:",
            *[v for v in (order.customer_name, order.phone, order.email) if v],
        ]
    if order.note:
        parts += ["", f"Note: {order.note}"]
    return ["\n".join(parts)]


def _message(
    subject: str,
    title: str,
    paragraphs: Sequence[str],
    link: Link | None,
    sms: str,
    *,
    extra_html: str = "",
    extra_text: Sequence[str] = (),
    after: Sequence[str] = (),
) -> Rendered:
    html_body = (
        "".join(_p(p) for p in paragraphs)
        + _button(link)
        + extra_html
        + "".join(_p(p, muted=True, size=13) for p in after)
    )
    return Rendered(
        subject=subject,
        text=_text(title, [*paragraphs, *extra_text, *after], link),
        html=_layout(title, paragraphs[0] if paragraphs else title, html_body),
        sms=sms,
    )


# ---- messages --------------------------------------------------------------------------------
def order_received(order: OrderSummary, link: Link | None) -> Rendered:
    first = (
        f"Hi {order.customer_name}, thank you for your order. We have received order "
        f"{order.number} and will confirm it shortly."
    )
    return _message(
        f"We received your order {order.number}",
        "Order received",
        [first],
        link,
        f"{BRAND}: we received your order {order.number} ({money(order.total)}).",
        extra_html=_order_html(order, contact=False),
        extra_text=_order_text(order, contact=False),
        after=["We will email you again when your order is confirmed and on its way."],
    )


def staff_new_order(order: OrderSummary, link: Link | None) -> Rendered:
    return _message(
        f"New order {order.number}: {money(order.total)}",
        f"New order {order.number}",
        [f"{order.customer_name} placed order {order.number} for {money(order.total)}."],
        link,
        f"New order {order.number}: {money(order.total)}.",
        extra_html=_order_html(order, contact=True),
        extra_text=_order_text(order, contact=True),
    )


def payment_succeeded(
    order: OrderSummary, amount: int, method: str | None, link: Link | None
) -> Rendered:
    paid = f"We received your payment of {money(amount)}"
    paid += f" by {payment_label(method)}" if method else ""
    return _message(
        f"Payment received for order {order.number}",
        "Payment received",
        [f"Hi {order.customer_name}, {paid} for order {order.number}. Thank you."],
        link,
        f"{BRAND}: payment of {money(amount)} received for order {order.number}.",
        extra_html=_rows([("Order number", order.number), ("Amount paid", money(amount))]),
        extra_text=[f"Order number: {order.number}\nAmount paid: {money(amount)}"],
        after=["Your invoice is available from your order page."],
    )


STATUS_COPY = {
    "confirmed": (
        "Order {number} confirmed",
        "Order confirmed",
        "Your order {number} is confirmed. We are preparing it and will tell you when it is on "
        "its way.",
        "Your order {number} is confirmed. We will tell you when it is on its way.",
    ),
    "dispatched": (
        "Order {number} is on its way",
        "Your order is on its way",
        "Good news: your order {number} has left our store and is out for delivery. Please keep "
        "your phone nearby so our courier can reach you.",
        "Your order {number} is on its way.",
    ),
    "delivered": (
        "Order {number} delivered",
        "Order delivered",
        "Your order {number} has been delivered. Thank you for shopping with us. We would love "
        "to hear what you think of your products.",
        "Your order {number} has been delivered. Thank you for shopping with us.",
    ),
    "cancelled": (
        "Order {number} cancelled",
        "Order cancelled",
        "Your order {number} has been cancelled. If you paid for it, we will contact you about "
        "the refund. Contact us if you have any questions.",
        "Your order {number} has been cancelled. Contact us if you have any questions.",
    ),
}


def order_status(event: str, order: OrderSummary, link: Link | None) -> Rendered:
    subject, title, body, sms = STATUS_COPY[event]
    number = order.number
    greeting = f"Hi {order.customer_name}, " if order.customer_name else ""
    return _message(
        subject.format(number=number),
        title,
        [greeting + body.format(number=number)],
        link,
        sms.format(number=number),
        extra_html=_rows([("Order number", number), ("Total", money(order.total))]),
        extra_text=[f"Order number: {number}\nTotal: {money(order.total)}"],
    )


def order_status_sms(event: str, number: str) -> str:
    """The status SMS when the order itself cannot be loaded (never expected)."""
    return STATUS_COPY[event][3].format(number=number)


def welcome(name: str, link: Link | None) -> Rendered:
    return _message(
        f"Welcome to {BRAND}",
        f"Welcome, {name}",
        [
            f"Hi {name}, your {BRAND} account is ready. You can now track your orders, save your "
            "delivery addresses and keep a wishlist of the products you love.",
        ],
        link,
        f"Welcome to {BRAND}, {name}.",
    )


def quote_received(
    reference: str,
    contact_name: str,
    company: str,
    lines: Sequence[tuple[str, int]],
    link: Link | None,
) -> Rendered:
    items = _rows([(name, f"Qty {quantity}") for name, quantity in lines])
    return _message(
        f"We received your quote request {reference}",
        "Quote request received",
        [
            f"Hi {contact_name}, thank you for your quote request for {company}. Our sales team "
            f"will contact you soon. Your reference is {reference}.",
        ],
        link,
        f"{BRAND}: quote request {reference} received.",
        extra_html=_heading("Requested products") + items,
        extra_text=["Requested products:\n" + "\n".join(f"- {n}: qty {q}" for n, q in lines)],
        after=["Reply to this email if you want to add anything to your request."],
    )


def service_received(reference: str, full_name: str, service: str, link: Link | None) -> Rendered:
    return _message(
        f"We received your service request {reference}",
        "Service request received",
        [
            f"Hi {full_name}, thank you for your request for {service}. Our team will call you "
            f"soon to agree the details. Your reference is {reference}.",
        ],
        link,
        f"{BRAND}: service request {reference} received.",
        after=["Reply to this email if you want to add anything to your request."],
    )


# Seller applications and decisions (ADR-014 phase 1). {store} is the store's name and {reason}
# the administrator's reason, both as they were when the event was recorded.
STORE_STATUS_COPY: dict[str, tuple[str, str, str]] = {
    "store_application_received": (
        "We received your seller application for {store}",
        "Seller application received",
        "Hi {name}, thank you for applying to sell on {brand} as {store}. Our team will review "
        "your application and email you when it has been decided.",
    ),
    "store_approved": (
        "Your store {store} is approved",
        "Your store is approved",
        "Hi {name}, good news: your seller application for {store} has been approved. You can "
        "now set up your store and start listing your products.",
    ),
    "store_rejected": (
        "Your seller application for {store} was not approved",
        "Seller application not approved",
        "Hi {name}, we could not approve your seller application for {store}. You can update "
        "your application and send it again.",
    ),
    "store_suspended": (
        "Your store {store} has been suspended",
        "Your store is suspended",
        "Hi {name}, your store {store} has been suspended. While it is suspended your store "
        "and its products are not shown to customers and you cannot manage them.",
    ),
    "store_reinstated": (
        "Your store {store} is active again",
        "Your store is active again",
        "Hi {name}, your store {store} has been reinstated. Customers can see it again and you "
        "can manage it as before.",
    ),
}


def store_status(
    event: str, name: str, store: str, reason: str | None, link: Link | None
) -> Rendered:
    subject, title, first = STORE_STATUS_COPY[event]
    paragraphs = [first.format(name=name, store=store, brand=BRAND)]
    if reason and event in ("store_rejected", "store_suspended"):
        paragraphs.append(f"Reason: {reason}")
    return _message(
        subject.format(store=store),
        title,
        paragraphs,
        link,
        f"{BRAND}: {title.lower()} ({store}).",
    )


def review_thanks(name: str, product: str, link: Link | None) -> Rendered:
    return _message(
        "Thank you for your review",
        "Thank you for your review",
        [
            f"Hi {name}, thank you for reviewing {product}. Your review helps other customers "
            "choose well. It appears on the product page once our team has checked it.",
        ],
        link,
        f"{BRAND}: thank you for reviewing {product}.",
    )


def support_reply(
    reference: str,
    name: str,
    subject: str,
    body: str,
    link: Link | None,
    *,
    has_account: bool,
) -> Rendered:
    """A staff reply to a support request: the reply text, and a button to the conversation (My
    messages for a customer, the private link for a guest)."""
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    after = (
        "Open the conversation in My messages to read every message and reply."
        if has_account
        else "Use the button to read the whole conversation and reply. Keep this email: the link "
        "is private to you."
    )
    return _message(
        f"Your support request has been answered [{reference}]",
        "Your request has been answered",
        [
            f"Hi {name}, our support team has answered your request “{subject}” "
            f"({reference}). Their reply:",
            *paragraphs,
        ],
        link,
        f"{BRAND}: your support request {reference} has been answered. Check your email.",
        after=[after],
    )


def password_reset(code: str) -> Rendered:
    """The code is in the message only; callers never store or log it."""
    text = (
        f"Your password reset code is {code}. It expires in 15 minutes. If you did not ask to "
        "reset your password, ignore this message."
    )
    code_html = (
        f'<p style="margin:4px 0 20px;font-size:30px;font-weight:700;letter-spacing:6px;'
        f'color:{NAVY};">{escape(code)}</p>'
    )
    return _message(
        "Your password reset code",
        "Reset your password",
        ["Use this code to reset your password. It expires in 15 minutes."],
        None,
        text,
        extra_html=code_html,
        extra_text=[f"Code: {code}"],
        after=["If you did not ask to reset your password, ignore this email."],
    )


def email_verification(name: str, link: Link, hours: int) -> Rendered:
    """The link holds the verification token: callers never store or log the rendered message
    (ADR-006 amendment 2026-11-12). No password or other account detail is included."""
    lifetime = f"{hours} hour" if hours == 1 else f"{hours} hours"
    return _message(
        f"Confirm your email address for {BRAND}",
        "Confirm your email",
        [
            f"Hi {name}, thank you for creating a {BRAND} account. You are receiving this email "
            "because this address was used to register. Please confirm that it is yours to "
            "start signing in.",
            f"This link expires in {lifetime}.",
        ],
        link,
        f"{BRAND}: confirm your email address.",
        after=[
            "If you did not create an account, ignore this email: the account cannot be used "
            "until the address is confirmed.",
        ],
    )


# ---- pending integrations (templates only) ---------------------------------------------------


def refund_acknowledged(order: OrderSummary, amount: int, link: Link | None) -> Rendered:
    """Pending: no workflow records refunds yet (no refund amount or refunded status is set)."""
    return _message(
        f"Refund for order {order.number}",
        "Refund on its way",
        [
            f"Hi {order.customer_name}, we have started a refund of {money(amount)} for order "
            f"{order.number}. It can take a few business days to reach you.",
        ],
        link,
        f"{BRAND}: refund of {money(amount)} for order {order.number} started.",
        extra_html=_rows([("Order number", order.number), ("Refund", money(amount))]),
        extra_text=[f"Order number: {order.number}\nRefund: {money(amount)}"],
    )
