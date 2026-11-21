"""Module 16 hardening: the administrator's invoice recovery for paid orders whose issuance was
refused, the staff COD-confirmation issuance path, and delivery-note eligibility across every
reachable order state. Disposable per-test schema of rwanda_ecommerce_test."""

import threading
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.core.request_context import RequestContext
from app.core.roles import ROLE_PERMISSIONS, Permission
from app.models import Order, PaymentAttempt
from app.models.identity import User
from app.models.operations import AuditRecord
from app.services import invoice_service
from tests.integration.test_cart_api import code
from tests.integration.test_checkout_api import STAFF, checkout, guest_cart
from tests.integration.test_invoices_api import (
    CUSTOMER_ORDERS,
    SELLER,
    SETTINGS,
    audits,
    counter,
    deliver,
    first_number,
    invoices,
    paid_customer_order,
)
from tests.integration.test_payments_api import delivery, momo_order, started  # noqa: F401

STAFF_PAYMENTS = "/api/v1/staff/payments"
CTX = RequestContext(ip_address="127.0.0.1", user_agent="invoice-recovery-test")
TIMEOUT = 30


def recover(client, order_id: str, headers: dict):
    return client.post(f"{STAFF}/{order_id}/invoice", headers=headers)


def configure(client, admin_auth) -> None:
    assert client.patch(SETTINGS, json=SELLER, headers=admin_auth["headers"]).status_code == 200


# ---- recovery --------------------------------------------------------------------------------
def test_an_administrator_recovers_a_refused_invoice_once(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
    customer_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])  # seller details unset
    assert invoices(db) == []
    early = recover(client, order["id"], admin_auth["headers"])
    assert early.status_code == 409 and code(early) == "seller_details_missing"
    assert invoices(db) == [] and counter(db) is None  # still no number used
    configure(client, admin_auth)
    db.expire_all()
    before = db.get(Order, uuid.UUID(order["id"]))
    assert before is not None
    status_before = before.status
    res = recover(client, order["id"], admin_auth["headers"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["issued"] is True and body["invoice_number"] == first_number(db)
    assert body["total"] == order["total"] and body["order_id"] == order["id"]
    [invoice] = invoices(db)
    assert invoice.snapshot["order"]["payment_method"] == "mtn_momo"
    db.expire_all()
    after = db.get(Order, uuid.UUID(order["id"]))
    assert after is not None and after.status == status_before  # order unchanged
    assert db.scalar(select(PaymentAttempt.status)) == "succeeded"  # payment unchanged
    issued = [a for a in audits(db, order["id"], "invoice.issue") if a["status"] == "success"]
    assert len(issued) == 1 and issued[0]["recovery"] is True
    # Idempotent: no second invoice, no number.
    again = recover(client, order["id"], admin_auth["headers"])
    assert again.status_code == 200 and again.json()["issued"] is False
    assert again.json()["invoice_number"] == body["invoice_number"]
    assert len(invoices(db)) == 1 and counter(db) == 1
    download = client.get(
        f"{CUSTOMER_ORDERS}/{order['id']}/invoice", headers=customer_auth["headers"]
    )
    assert download.status_code == 200


@pytest.mark.parametrize("role", ["customer_auth"])
def test_only_invoice_recoverers_can_recover(client, db, delivery, admin_auth, role, request):  # noqa: F811
    configure(client, admin_auth)
    order, _ = started(client, db)
    member = request.getfixturevalue(role)
    url = f"{STAFF}/{order['id']}/invoice"
    assert recover(client, order["id"], member["headers"]).status_code == 403
    denied = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "auth.access_denied", AuditRecord.entity_id == url
        )
    ).all()
    assert [str(r.actor_user_id) for r in denied] == [member["user"]["id"]]  # audited
    assert recover(client, order["id"], {}).status_code == 401
    missing = recover(client, str(uuid.uuid4()), admin_auth["headers"])
    assert missing.status_code == 404 and code(missing) == "order_not_found"
    assert recover(client, "nope", admin_auth["headers"]).status_code == 422
    assert invoices(db) == []
    assert Permission.INVOICES_RECOVER.value not in ROLE_PERMISSIONS[role.removesuffix("_auth")]


def test_invoices_recover_not_payments_manage_gates_recovery(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
    customer_auth,
    monkeypatch,
):
    order = paid_customer_order(client, db, customer_auth["headers"])  # refused: seller unset
    configure(client, admin_auth)
    # The administrator is the only staff role (SC-05): take invoices:recover away from it alone.
    everything = ROLE_PERMISSIONS["administrator"]
    without = everything - {Permission.INVOICES_RECOVER.value}
    assert Permission.PAYMENTS_MANAGE.value in without
    monkeypatch.setitem(ROLE_PERMISSIONS, "administrator", without)
    refused = recover(client, order["id"], admin_auth["headers"])
    assert refused.status_code == 403 and invoices(db) == []  # payments:manage is not enough
    monkeypatch.setitem(ROLE_PERMISSIONS, "administrator", everything)
    first = recover(client, order["id"], admin_auth["headers"])
    assert first.status_code == 201 and first.json()["issued"] is True
    second = recover(client, order["id"], admin_auth["headers"])
    assert second.status_code == 200 and second.json()["issued"] is False
    assert len(invoices(db)) == 1 and counter(db) == 1
    db.expire_all()
    [issued] = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "invoice.issue", AuditRecord.entity_id == order["id"]
        )
    ).all()[-1:]
    assert issued.actor_user_id == admin_auth["user"].id
    assert issued.change_summary["status"] == "success" and issued.change_summary["recovery"]


def test_unpaid_orders_cannot_be_invoiced_by_recovery(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
):
    configure(client, admin_auth)
    unpaid = momo_order(client, db)
    res = recover(client, unpaid["id"], admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "invoice_not_issuable"
    cod = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, cod, admin_auth["headers"])  # dispatched, not delivered: not paid
    res = recover(client, cod["id"], admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "invoice_not_issuable"
    assert invoices(db) == [] and counter(db) is None
    [refused] = audits(db, unpaid["id"], "invoice.issue")
    assert refused["status"] == "conflict" and refused["reason"] == "not_paid"


def test_recovery_refuses_amounts_that_do_not_reconcile(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
    customer_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])
    configure(client, admin_auth)
    db.execute(
        text("UPDATE orders SET tax_total = tax_total + 1 WHERE id = :id"), {"id": order["id"]}
    )
    db.commit()
    res = recover(client, order["id"], admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "order_amounts_inconsistent"
    assert invoices(db) == [] and counter(db) is None


def test_concurrent_recoveries_issue_one_invoice(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
    customer_auth,
):
    order = paid_customer_order(client, db, customer_auth["headers"])
    configure(client, admin_auth)
    admin_id = admin_auth["user"].id
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(6)
    outcomes: list[tuple[str, bool]] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def worker() -> None:
        try:
            with make() as session:
                actor = session.get(User, admin_id)
                assert actor is not None
                barrier.wait(TIMEOUT)
                invoice, issued = invoice_service.recover_invoice(
                    session, uuid.UUID(order["id"]), actor, CTX
                )
                with guard:
                    outcomes.append((invoice.invoice_number, issued))
        except BaseException as exc:  # reported below
            with guard:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT)
    assert errors == [] and not any(t.is_alive() for t in threads), errors
    assert sorted(issued for _, issued in outcomes) == [False] * 5 + [True]
    assert {number for number, _ in outcomes} == {first_number(db)}
    assert len(invoices(db)) == 1 and counter(db) == 1


# ---- staff COD confirmation ----------------------------------------------------------------
def test_delivery_always_settles_a_cod_payment_so_confirmation_never_needs_to(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
):
    configure(client, admin_auth)
    order = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, order, admin_auth["headers"], steps=("confirmed", "processing"))
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "pending"
    deliver(client, order, admin_auth["headers"], steps=("dispatched", "delivered"))
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "succeeded"  # Q14, in the same change
    [invoice] = invoices(db)
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None
    res = client.post(f"{STAFF_PAYMENTS}/{attempt.id}/confirm-cod", headers=admin_auth["headers"])
    assert res.status_code == 200 and res.json()["status"] == "succeeded"  # a no-op
    assert invoices(db) == [invoice] and counter(db) == 1


def test_a_cod_delivery_without_seller_details_is_refused_then_recovered_unchanged(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
):
    """Seller details unset when a cash-on-delivery order is delivered: the delivery and the
    cash payment commit, no invoice or number is used, the refusal is audited; an administrator
    later recovers the invoice without changing the order or its payment."""
    order = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, order, admin_auth["headers"])  # confirmed, processing, dispatched
    res = client.patch(
        f"{STAFF}/{order['id']}/status",
        json={"status": "delivered"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 200, res.text  # the refusal never blocks the delivery
    db.expire_all()
    stored = db.get(Order, uuid.UUID(order["id"]))
    attempt = db.scalar(select(PaymentAttempt))
    assert stored is not None and attempt is not None
    assert stored.status == "delivered" and attempt.status == "succeeded"  # Q14 still applies
    assert invoices(db) == [] and counter(db) is None  # no number used
    [refused] = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "invoice.issue", AuditRecord.entity_id == order["id"]
        )
    ).all()
    assert refused.change_summary["status"] == "failure"
    assert refused.change_summary["reason"] == "seller_details_missing"
    assert refused.actor_user_id == admin_auth["user"].id  # the delivering staff member
    before = (stored.status, stored.total, stored.tax_total, stored.updated_at)
    paid = (attempt.status, attempt.amount, attempt.succeeded_at, attempt.updated_at)
    # Recovery is refused while the details are unset, then issues once they are.
    early = recover(client, order["id"], admin_auth["headers"])
    assert early.status_code == 409 and code(early) == "seller_details_missing"
    assert invoices(db) == [] and counter(db) is None
    configure(client, admin_auth)
    issued = recover(client, order["id"], admin_auth["headers"])
    assert issued.status_code == 201 and issued.json()["invoice_number"] == first_number(db)
    [invoice] = invoices(db)
    assert invoice.snapshot["order"]["payment_method"] == "cash_on_delivery"
    assert invoice.total == stored.total and invoice.vat_amount == stored.tax_total
    db.expire_all()
    stored = db.get(Order, uuid.UUID(order["id"]))
    attempt = db.scalar(select(PaymentAttempt))
    assert stored is not None and attempt is not None
    assert (stored.status, stored.total, stored.tax_total, stored.updated_at) == before
    assert (attempt.status, attempt.amount, attempt.succeeded_at, attempt.updated_at) == paid
    assert recover(client, order["id"], admin_auth["headers"]).status_code == 200  # idempotent
    assert len(invoices(db)) == 1 and counter(db) == 1


def test_staff_cod_confirmation_of_an_unsettled_delivered_order_issues_the_invoice(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
):
    """The API cannot produce a delivered order with a pending cash payment (delivery settles
    it); this state is built directly to cover the defensive issuance in confirm_cod."""
    configure(client, admin_auth)
    order = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, order, admin_auth["headers"], steps=("confirmed", "processing"))
    db.execute(text("UPDATE orders SET status = 'delivered' WHERE id = :id"), {"id": order["id"]})
    db.commit()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None and attempt.status == "pending" and invoices(db) == []
    res = client.post(f"{STAFF_PAYMENTS}/{attempt.id}/confirm-cod", headers=admin_auth["headers"])
    assert res.status_code == 200 and res.json()["status"] == "succeeded"
    [invoice] = invoices(db)
    assert invoice.snapshot["order"]["payment_method"] == "cash_on_delivery"
    again = client.post(f"{STAFF_PAYMENTS}/{attempt.id}/confirm-cod", headers=admin_auth["headers"])
    assert again.status_code == 200 and len(invoices(db)) == 1 and counter(db) == 1


# ---- delivery-note eligibility across the state machine ----------------------------------------
def note(client, order_id: str, headers: dict) -> int:
    return client.get(f"{STAFF}/{order_id}/delivery-note", headers=headers).status_code


def test_delivery_note_eligibility_for_every_reachable_state(
    client,
    db,
    delivery,  # noqa: F811
    admin_auth,
    customer_auth,
):
    """Implemented rule (pending owner approval): not cancelled, and all stock committed for
    delivery or fulfilled."""
    configure(client, admin_auth)
    ops = admin_auth["headers"]
    # Mobile money: received and unpaid (stock on hold) -> no; received and paid -> yes.
    unpaid = momo_order(client, db)
    assert note(client, unpaid["id"], ops) == 409
    paid = paid_customer_order(client, db, customer_auth["headers"])
    assert note(client, paid["id"], ops) == 200
    for step in ("confirmed", "processing", "dispatched", "delivered"):
        deliver(client, paid, ops, steps=(step,))
        assert note(client, paid["id"], ops) == 200, step
    # Cash on delivery: received (hold) -> no; confirmed (Q13 commits the stock) onwards -> yes.
    cod = checkout(client, guest_cart(client, db)).json()["order"]
    assert note(client, cod["id"], ops) == 409
    for step in ("confirmed", "processing", "dispatched", "delivered"):
        deliver(client, cod, ops, steps=(step,))
        assert note(client, cod["id"], ops) == 200, step
    # Cancelled -> no. Only orders whose stock is still on hold can be cancelled (committed
    # stock cannot be released: 409 inventory_conflict), so: a received COD order, and an unpaid
    # mobile-money order from received, confirmed or processing.
    cod_cancelled = checkout(client, guest_cart(client, db)).json()["order"]
    deliver(client, cod_cancelled, ops, steps=("cancelled",))
    assert note(client, cod_cancelled["id"], ops) == 409
    for steps in ((), ("confirmed",), ("confirmed", "processing")):
        order = momo_order(client, db)
        assert note(client, order["id"], ops) == 409, steps  # on hold before cancelling too
        deliver(client, order, ops, steps=(*steps, "cancelled"))
        assert note(client, order["id"], ops) == 409, steps
    paid_cancel = client.patch(
        f"{STAFF}/{paid['id']}/status", json={"status": "cancelled"}, headers=ops
    )
    assert paid_cancel.status_code == 409  # delivered: no transition, so never both
