"""Module 16 invoices and delivery notes over the API: issuance with a recorded payment success or
a cash-on-delivery delivery (§7 Q19), nothing for unconfirmed payments, seller-setting refusals,
ownership and staff permissions, immutable snapshots and the PDFs. Disposable per-test schema
of rwanda_ecommerce_test."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.kigali_time import KIGALI
from app.core.money import vat_component
from app.core.roles import ROLE_PERMISSIONS, Permission
from app.models import Invoice, InvoiceCounter, Order, PaymentAttempt
from app.models.operations import AuditRecord
from app.services import checkout_service
from app.services.audit_service import AuditService
from app.services.document_pdf import money
from app.services.promotion_service import database_now
from tests.integration.test_cart_api import add, code, sku
from tests.integration.test_checkout_api import INLINE, STAFF, checkout, guest_cart
from tests.integration.test_payments_api import (  # noqa: F401
    delivery,
    event,
    initiate,
    momo_order,
    started,
    webhook,
)
from tests.support.commerce import wait_until_due
from tests.support.pdf import is_complete_pdf, pdf_text

SETTINGS = "/api/v1/staff/settings"
CUSTOMER_ORDERS = "/api/v1/customers/me/orders"
SELLER = {
    "seller.legal_name": "Test Electronics Ltd",
    "seller.tin": "TEST-TIN-0001",
    "seller.address": "KG 7 Ave\nKigali",
}


@pytest.fixture
def seller(client, admin_auth) -> None:
    res = client.patch(SETTINGS, json=SELLER, headers=admin_auth["headers"])
    assert res.status_code == 200, res.text


def invoices(db) -> list[Invoice]:
    db.expire_all()
    return list(db.scalars(select(Invoice).order_by(Invoice.invoice_number)))


def counter(db) -> int | None:
    db.expire_all()
    return db.scalar(select(func.max(InvoiceCounter.last_number)))


def first_number(db) -> str:
    year = database_now(db).astimezone(KIGALI).year
    return f"INV-{year}-000001"


def pay(client, order: dict, reference: str):
    res = webhook(client, event(reference, "succeeded", order["total"]))
    assert res.status_code == 200, res.text
    return res


def paid_customer_order(client, db, headers) -> dict:
    order = momo_order(client, db, headers)
    res = initiate(client, order["order_number"], phone=None, headers=headers)
    assert res.status_code == 200, res.text
    pay(client, order, res.json()["reference"])
    return order


def deliver(client, order: dict, headers: dict, steps=("confirmed", "processing", "dispatched")):
    for step in steps:
        res = client.patch(f"{STAFF}/{order['id']}/status", json={"status": step}, headers=headers)
        assert res.status_code == 200, res.text


def audits(db, order_id: str, action: str) -> list[dict]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditRecord.change_summary).where(
                AuditRecord.entity_id == order_id, AuditRecord.action == action
            )
        )
    )


# ---- issuance (§7 Q19) -----------------------------------------------------------------------
def test_a_verified_payment_success_issues_one_invoice(client, db, delivery, seller):  # noqa: F811
    order, body = started(client, db)
    res = pay(client, order, body["reference"])
    assert res.json()["status"] == "processed"
    [invoice] = invoices(db)
    assert invoice.invoice_number == first_number(db) and counter(db) == 1
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None
    assert (invoice.total, invoice.vat_amount) == (stored.total, stored.tax_total)
    assert invoice.vat_amount == vat_component(stored.total)  # ADR-007, order level
    snap = invoice.snapshot
    assert snap["invoice_number"] == invoice.invoice_number
    assert snap["seller"] == {
        "legal_name": SELLER["seller.legal_name"],
        "tin": SELLER["seller.tin"],
        "address": SELLER["seller.address"],
    }
    assert snap["order"]["number"] == order["order_number"]
    assert snap["order"]["payment_method"] == "mtn_momo"
    assert snap["totals"]["total"] == stored.total and snap["vat"]["amount"] == stored.tax_total
    assert sum(line["line_total"] for line in snap["lines"]) + snap["totals"]["delivery_fee"] == (
        stored.total
    )
    # No phone number stored. The full digits: a bare "788" also matches the timestamps'
    # microseconds now and then (e.g. "...16.554788+00:00").
    assert "788123456" not in str(snap) and "123 456" not in str(snap)
    [issued] = audits(db, order["id"], "invoice.issue")
    assert issued["status"] == "success" and issued["invoice_number"] == invoice.invoice_number
    # A repeated or second success never issues again.
    again = pay(client, order, body["reference"])
    assert again.json()["status"] == "processed"
    assert len(invoices(db)) == 1 and counter(db) == 1


def test_a_cash_on_delivery_order_is_invoiced_on_delivery(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    operations_auth,
):
    order = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, order, operations_auth["headers"])
    assert invoices(db) == []  # confirmed and dispatched: not yet paid
    deliver(client, order, operations_auth["headers"], steps=("delivered",))
    [invoice] = invoices(db)
    assert invoice.snapshot["order"]["payment_method"] == "cash_on_delivery"
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "succeeded"


@pytest.mark.parametrize("outcome", ["pending", "failed", "cancelled"])
def test_unconfirmed_outcomes_issue_nothing(client, db, delivery, seller, outcome):  # noqa: F811
    order, body = started(client, db)
    webhook(client, event(body["reference"], outcome, order["total"]))
    assert invoices(db) == [] and counter(db) is None


def test_a_mismatched_or_unknown_success_issues_nothing(client, db, delivery, seller):  # noqa: F811
    order, body = started(client, db)
    res = webhook(client, event(body["reference"], "succeeded", order["total"] - 1))
    assert res.json()["status"] == "needs_reconciliation"
    res = webhook(client, event("MOCK-UNKNOWNREFERENCE", "succeeded", order["total"]))
    assert res.json()["status"] == "needs_reconciliation"
    assert invoices(db) == [] and counter(db) is None


def test_a_late_success_issues_nothing(client, db, delivery, seller, monkeypatch):  # noqa: F811
    monkeypatch.setitem(checkout_service.HOLDS, "mtn_momo", timedelta(seconds=1))
    order, body = started(client, db)
    wait_until_due()
    res = pay(client, order, body["reference"])
    assert res.json()["status"] == "needs_reconciliation"  # D-Y4: not paid
    assert invoices(db) == [] and counter(db) is None


# ---- seller settings and refusals --------------------------------------------------------------
def test_missing_seller_details_refuse_the_invoice_but_keep_the_payment(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
    customer_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "succeeded"  # the payment stands
    assert invoices(db) == [] and counter(db) is None  # no number used
    [refused] = audits(db, order["id"], "invoice.issue")
    assert refused["status"] == "failure" and refused["reason"] == "seller_details_missing"
    res = client.get(f"{CUSTOMER_ORDERS}/{order['id']}/invoice", headers=customer_auth["headers"])
    assert res.status_code == 409 and code(res) == "invoice_not_available"
    # Configuring the seller later does not issue it; the next invoice still gets number 1.
    assert client.patch(SETTINGS, json=SELLER, headers=admin_auth["headers"]).status_code == 200
    assert invoices(db) == []
    second, body = started(client, db)
    pay(client, second, body["reference"])
    [invoice] = invoices(db)
    assert invoice.invoice_number == first_number(db) and counter(db) == 1


def test_an_invalid_stored_seller_setting_refuses_the_invoice(client, db, delivery, seller):  # noqa: F811
    db.execute(text("UPDATE settings SET value = '\"bad/tin\"' WHERE key = 'seller.tin'"))
    db.commit()
    order, body = started(client, db)
    pay(client, order, body["reference"])
    assert invoices(db) == [] and counter(db) is None
    [refused] = audits(db, order["id"], "invoice.issue")
    assert refused["reason"] == "seller_details_missing"


def test_seller_settings_are_managed_like_other_settings(client, admin_auth, management_auth):
    bad = client.patch(SETTINGS, json={"seller.tin": "12/34"}, headers=admin_auth["headers"])
    assert bad.status_code == 422
    blank = client.patch(SETTINGS, json={"seller.legal_name": " "}, headers=admin_auth["headers"])
    assert blank.status_code == 422
    denied = client.patch(SETTINGS, json=SELLER, headers=management_auth["headers"])
    assert denied.status_code == 403
    ok = client.patch(SETTINGS, json=SELLER, headers=admin_auth["headers"])
    assert ok.status_code == 200
    values = {item["key"]: item["value"] for item in ok.json()["items"]}
    assert {key: values[key] for key in SELLER} == SELLER


def test_a_failure_after_the_number_is_taken_rolls_everything_back(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    monkeypatch,
):
    order, body = started(client, db)
    original = AuditService.log_event

    def failing(*args, **kwargs):
        if kwargs.get("action") == "invoice.issue" and kwargs.get("status") == "success":
            raise RuntimeError("audit store down")
        return original(*args, **kwargs)

    monkeypatch.setattr(AuditService, "log_event", staticmethod(failing))
    with pytest.raises(RuntimeError):
        webhook(client, event(body["reference"], "succeeded", order["total"]))
    db.rollback()
    assert invoices(db) == [] and counter(db) is None  # the number was given back
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "pending"  # the success rolled back too
    monkeypatch.setattr(AuditService, "log_event", staticmethod(original))
    pay(client, order, body["reference"])  # the provider's retry
    [invoice] = invoices(db)
    assert invoice.invoice_number == first_number(db) and counter(db) == 1


# ---- downloads: ownership and permissions ------------------------------------------------------
def test_customers_download_only_their_own_invoices(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    customer_auth,
    second_customer_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])
    url = f"{CUSTOMER_ORDERS}/{order['id']}/invoice"
    own = client.get(url, headers=customer_auth["headers"])
    assert own.status_code == 200 and own.headers["content-type"] == "application/pdf"
    number = invoices(db)[0].invoice_number
    assert own.headers["content-disposition"] == f'attachment; filename="{number}.pdf"'
    assert own.headers["cache-control"] == "no-store"
    assert is_complete_pdf(own.content) and number in pdf_text(own.content)
    other = client.get(url, headers=second_customer_auth["headers"])
    missing = client.get(
        f"{CUSTOMER_ORDERS}/{uuid.uuid4()}/invoice", headers=customer_auth["headers"]
    )
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()  # another customer's order looks like no order
    assert client.get(url).status_code == 401
    assert (
        client.get(
            f"{CUSTOMER_ORDERS}/not-a-uuid/invoice", headers=customer_auth["headers"]
        ).status_code
        == 422
    )


def test_an_unpaid_order_has_no_invoice(client, db, delivery, seller, customer_auth):  # noqa: F811
    order = momo_order(client, db, customer_auth["headers"])
    res = client.get(f"{CUSTOMER_ORDERS}/{order['id']}/invoice", headers=customer_auth["headers"])
    assert res.status_code == 409 and code(res) == "invoice_not_available"


@pytest.mark.parametrize("role", ["administrator", "sales", "operations", "management"])
def test_staff_invoice_and_delivery_note_permissions(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    role,
    request,
    customer_auth,
):
    headers = request.getfixturevalue(
        {
            "administrator": "admin_auth",
            "sales": "sales_auth",
            "operations": "operations_auth",
            "management": "management_auth",
        }[role]
    )["headers"]
    order = paid_customer_order(client, db, customer_auth["headers"])
    granted = ROLE_PERMISSIONS[role]
    res = client.get(f"{STAFF}/{order['id']}/invoice", headers=headers)
    assert res.status_code == (200 if Permission.ORDER_READ.value in granted else 403)
    note = client.get(f"{STAFF}/{order['id']}/delivery-note", headers=headers)
    assert note.status_code == (200 if Permission.ORDER_FULFIL.value in granted else 403)
    if note.status_code == 200:
        assert note.headers["content-type"] == "application/pdf"
        assert note.headers["content-disposition"] == (
            f'attachment; filename="delivery-note-{order["order_number"]}.pdf"'
        )


def test_staff_routes_refuse_customers_and_anonymous_callers(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    customer_auth,
    admin_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])
    for path in ("invoice", "delivery-note"):
        url = f"{STAFF}/{order['id']}/{path}"
        assert client.get(url).status_code == 401
        assert client.get(url, headers=customer_auth["headers"]).status_code == 403
        missing = client.get(f"{STAFF}/{uuid.uuid4()}/{path}", headers=admin_auth["headers"])
        assert missing.status_code == 404 and code(missing) == "order_not_found"


# ---- snapshots ---------------------------------------------------------------------------------
def test_downloads_render_the_issued_snapshot_and_never_issue_again(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    admin_auth,
    customer_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])
    url = f"{CUSTOMER_ORDERS}/{order['id']}/invoice"
    first = client.get(url, headers=customer_auth["headers"]).content
    [invoice] = invoices(db)
    issued = dict(invoice.snapshot)
    # Everything the invoice was built from changes afterwards.
    changed = {**SELLER, "seller.legal_name": "Renamed Ltd", "seller.tin": "OTHER-TIN"}
    assert client.patch(SETTINGS, json=changed, headers=admin_auth["headers"]).status_code == 200
    db.execute(text("UPDATE products SET name = 'Renamed product'"))
    db.execute(
        text("UPDATE orders SET recipient_name = 'Someone Else' WHERE id = :id"),
        {"id": order["id"]},
    )
    db.commit()
    for _ in range(3):
        assert client.get(url, headers=customer_auth["headers"]).content == first
    staff = client.get(f"{STAFF}/{order['id']}/invoice", headers=admin_auth["headers"]).content
    assert staff == first
    text_ = pdf_text(first)
    assert (
        "Test Electronics Ltd" in text_ and "Renamed" not in text_ and "Someone Else" not in text_
    )
    assert invoices(db)[0].snapshot == issued and len(invoices(db)) == 1 and counter(db) == 1


def test_the_invoice_pdf_matches_the_order_and_handles_long_and_accented_text(
    client,
    db,
    delivery,  # noqa: F811
    seller,
    customer_auth,
):
    headers = customer_auth["headers"]
    long_name = "Écouteurs sans fil édition Kigali " * 5
    for price in (12_000, 7_500, 30_000):
        variant = sku(db, price=price)
        db.execute(
            text(
                "UPDATE products SET name = :name WHERE id = "
                "(SELECT product_id FROM product_variants WHERE id = :v)"
            ),
            {"name": long_name.strip() + f" {price}", "v": variant},
        )
        db.commit()
        assert add(client, variant, 1, headers).status_code == 200
    res = checkout(client, headers, {"address": INLINE, "payment_method": "mtn_momo"})
    order = res.json()["order"]
    started_ = initiate(client, order["order_number"], phone=None, headers=headers)
    pay(client, order, started_.json()["reference"])
    pdf = client.get(f"{CUSTOMER_ORDERS}/{order['id']}/invoice", headers=headers).content
    text_ = pdf_text(pdf)
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None
    assert money(stored.total) in text_ and money(stored.tax_total) in text_
    assert "Écouteurs sans fil" in text_
    assert len(invoices(db)[0].snapshot["lines"]) == 3


# ---- delivery notes ----------------------------------------------------------------------------
def test_the_delivery_note_follows_the_fulfilment_workflow_and_shows_no_prices(
    client,
    db,
    delivery,  # noqa: F811
    operations_auth,
):
    headers = operations_auth["headers"]
    order = checkout(client, guest_cart(client, db)).json()["order"]
    url = f"{STAFF}/{order['id']}/delivery-note"
    early = client.get(url, headers=headers)  # cash on delivery, not confirmed: stock on hold
    assert early.status_code == 409 and code(early) == "delivery_note_unavailable"
    deliver(client, order, headers, steps=("confirmed",))  # Q13: stock committed
    note = client.get(url, headers=headers)
    assert note.status_code == 200 and is_complete_pdf(note.content)
    text_ = pdf_text(note.content)
    for expected in (order["order_number"], INLINE["recipient_name"], INLINE["street_address"]):
        assert expected in text_, expected
    for absent in ("RWF", "VAT", "Total", "Cash", "0788", "788 123"):
        assert absent not in text_, absent
    deliver(client, order, headers, steps=("processing", "dispatched", "delivered"))
    assert client.get(url, headers=headers).status_code == 200  # still available afterwards


def test_no_delivery_note_for_unpaid_or_cancelled_orders(
    client,
    db,
    delivery,  # noqa: F811
    operations_auth,
):
    headers = operations_auth["headers"]
    unpaid = momo_order(client, db)
    res = client.get(f"{STAFF}/{unpaid['id']}/delivery-note", headers=headers)
    assert res.status_code == 409 and code(res) == "delivery_note_unavailable"
    cancelled = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, cancelled, headers, steps=("cancelled",))
    res = client.get(f"{STAFF}/{cancelled['id']}/delivery-note", headers=headers)
    assert res.status_code == 409 and code(res) == "delivery_note_unavailable"
