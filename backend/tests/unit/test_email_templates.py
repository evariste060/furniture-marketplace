"""Transactional message templates (app.services.email_templates): HTML and plain-text content,
totals, links and escaping. Pure functions: no database or network."""

import re

import pytest

from app.services import email_templates as tpl

LINK = tpl.Link("View your order", "https://shop.example.rw/account/orders/ORD-261102-ABCDEF")


def summary(**overrides) -> tpl.OrderSummary:
    values = {
        "number": "ORD-261102-ABCDEF",
        "customer_name": "Aline Uwase",
        "lines": [
            tpl.OrderLine("iPhone 15", "128 GB, Black", 2, 1_250_000, 2_500_000),
            tpl.OrderLine("USB-C cable", None, 1, 15_000, 15_000),
        ],
        "subtotal": 2_515_000,
        "discount_total": 15_000,
        "delivery_fee": 2_000,
        "tax_total": 0,
        "total": 2_502_000,
        "payment_method": "cash_on_delivery",
        "discount_label": "WELCOME10",
        "delivery_zone": "Gasabo",
        "address_lines": ["Aline Uwase", "KG 11 Ave, house 4", "Gasabo"],
        "phone": "+250788123456",
        "email": "aline@example.rw",
    }
    return tpl.OrderSummary(**{**values, **overrides})


def visible(html: str) -> str:
    """The HTML's text, roughly as a reader sees it."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_money_matches_the_storefront_format():
    assert tpl.money(580_000) == "RWF 580,000"
    assert tpl.money(0) == "RWF 0"


def test_the_order_confirmation_is_itemised_with_totals_and_a_link():
    message = tpl.order_received(summary(), LINK)
    assert message.subject == "We received your order ORD-261102-ABCDEF"
    for part in (message.text, visible(message.html)):
        assert "2 x iPhone 15 (128 GB, Black)" in part and "RWF 2,500,000" in part
        assert "1 x USB-C cable" in part and "RWF 15,000" in part
        assert "Subtotal" in part and "RWF 2,515,000" in part
        assert "Discount (WELCOME10)" in part and "-RWF 15,000" in part
        assert "Delivery" in part and "RWF 2,000" in part
        assert "Total" in part and "RWF 2,502,000" in part
        assert "Cash on delivery" in part and "KG 11 Ave, house 4" in part
    assert 'href="https://shop.example.rw/account/orders/ORD-261102-ABCDEF"' in message.html
    assert "View your order: https://shop.example.rw/account/orders/ORD-261102-ABCDEF" in (
        message.text
    )
    assert "Tax" not in message.text  # no tax line when there is none
    assert "+250788123456" not in message.text  # the customer's own contact is not repeated


def test_free_delivery_and_no_discount():
    message = tpl.order_received(summary(delivery_fee=0, discount_total=0), LINK)
    assert "Delivery: Free" in message.text and "Discount" not in message.text


def test_the_staff_alert_shows_the_customer_and_opens_the_admin():
    admin = tpl.Link("Open in admin", "https://shop.example.rw/admin/orders/1")
    message = tpl.staff_new_order(summary(), admin)
    assert message.subject == "New order ORD-261102-ABCDEF: RWF 2,502,000"
    assert "+250788123456" in message.text and "aline@example.rw" in message.text
    assert 'href="https://shop.example.rw/admin/orders/1"' in message.html


@pytest.mark.parametrize("event", ["confirmed", "dispatched", "delivered", "cancelled"])
def test_status_messages(event):
    message = tpl.order_status(event, summary(), LINK)
    assert "ORD-261102-ABCDEF" in message.subject and "ORD-261102-ABCDEF" in message.text
    assert LINK.url in message.html and "RWF 2,502,000" in message.text
    assert "http" not in message.sms and "ORD-261102-ABCDEF" in message.sms


def test_payment_welcome_quote_and_review_messages():
    paid = tpl.payment_succeeded(summary(), 2_502_000, "mtn_momo", LINK)
    assert "RWF 2,502,000 by MTN Mobile Money" in paid.text
    welcome = tpl.welcome("Aline", tpl.Link("Start shopping", "https://shop.example.rw/products"))
    assert welcome.subject == "Welcome to FurniHub" and "Aline" in welcome.text
    quote = tpl.quote_received("Q-261102-ABCD", "Jean", "Acme Ltd", [("Laptop", 10)], None)
    assert "Q-261102-ABCD" in quote.text and "Laptop: qty 10" in quote.text
    review = tpl.review_thanks("Aline U.", "AirPods Pro", None)
    assert "AirPods Pro" in review.text


def test_a_service_request_is_acknowledged_with_its_reference():
    link = tpl.Link("See our services", "https://shop.example.rw/services/cctv-security")
    mail = tpl.service_received("SR-261117-ABCDEF", "Aline <b>", "CCTV & Security", link)
    assert "SR-261117-ABCDEF" in mail.subject
    assert "Aline <b>" in mail.text and "CCTV & Security" in mail.text
    assert "Aline &lt;b&gt;" in mail.html and "<b>" not in mail.html.split("Aline")[1][:10]
    assert 'href="https://shop.example.rw/services/cctv-security"' in mail.html


def test_a_support_reply_carries_the_reply_text():
    reply = tpl.support_reply(
        "M-261111-ABCDEF",
        "Aline",
        "Delivery <soon>",
        "It leaves today.\n\nIt arrives tomorrow.",
        LINK,
        has_account=True,
    )
    assert reply.subject == "Your support request has been answered [M-261111-ABCDEF]"
    assert "It leaves today." in reply.text and "It arrives tomorrow." in reply.text
    assert "My messages" in reply.text and LINK.url in reply.html
    assert "Delivery &lt;soon&gt;" in reply.html and "<soon>" not in reply.html
    guest = tpl.support_reply("M-1", "Jean", "Hi", "Ok", None, has_account=False)
    assert "private to you" in guest.text and "My messages" not in guest.text


def test_without_a_site_url_there_is_no_button_or_link():
    message = tpl.order_received(summary(), None)
    assert "<a " not in message.html and "http" not in message.text


def test_every_value_is_escaped():
    message = tpl.order_received(
        summary(customer_name='<script>alert("x")</script>', note="a & b"), LINK
    )
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html and "a &amp; b" in message.html
    link = tpl.Link("Go", 'https://shop.example.rw/x?a=1&b="2"')
    assert 'href="https://shop.example.rw/x?a=1&amp;b=&quot;2&quot;"' in tpl.welcome("A", link).html


def test_html_is_a_full_responsive_document():
    html = tpl.order_received(summary(), LINK).html
    assert html.startswith("<!doctype html>")
    assert 'name="viewport"' in html and "max-width:600px" in html
    assert "<style" not in html  # inline styles only: email clients drop style sheets


def test_the_reset_code_is_in_every_version():
    message = tpl.password_reset("482913")
    assert "482913" in message.text and "482913" in message.html and "482913" in message.sms
    assert message.sms == (
        "Your password reset code is 482913. It expires in 15 minutes. If you did not ask to "
        "reset your password, ignore this message."
    )


def test_pending_templates_render_but_are_not_events():
    from app.models.commerce import NOTIFICATION_EVENTS

    refund = tpl.refund_acknowledged(summary(), 50_000, LINK)
    assert "RWF 50,000" in refund.text
    assert not set(tpl.PENDING_TEMPLATES) & set(NOTIFICATION_EVENTS)


def test_the_email_verification_message():
    link = tpl.Link("Confirm my email", "https://shop.example.rw/verify-email#token=abc")
    message = tpl.email_verification("Aline", link, 24)
    assert message.subject == "Confirm your email address for FurniHub"
    assert (
        "Hi Aline" in message.text and "because this address was used to register" in message.text
    )
    assert "This link expires in 24 hours." in message.text
    assert link.url in message.text and 'href="https://shop.example.rw/verify-email#token=abc"' in (
        message.html
    )
    assert "If you did not create an account, ignore this email" in message.text
    assert "1 hour." in tpl.email_verification("Aline", link, 1).text
    assert "email_verification" not in tpl.PENDING_TEMPLATES  # it has a workflow now
