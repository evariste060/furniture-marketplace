from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.dependencies import SellerContext
from app.core.errors import AppError
from app.core.request_context import RequestContext
from app.models import (
    AuditRecord,
    Brand,
    Category,
    InventoryBalance,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentAttempt,
    Product,
    ProductVariant,
    StockReservation,
    Store,
)
from app.repositories.audit_repository import AuditRepository
from app.services import seller_order_service
from app.services.inventory import (
    InventoryUnavailable,
    commit_order_reservations,
    create_order_with_reservations,
)
from app.services.seller_order_service import SellerOrderService
from tests.conftest import make_staff
from tests.support.commerce import needs_stores
from tests.support.seller_orders import move, owner_headers, seller_orders
from tests.support.sellers import new_store


@pytest.fixture
def session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def _new_reserved_order(session_factory, customer_id: UUID | None = None) -> UUID:
    with session_factory() as session:
        category = Category(name="Phones", slug=f"phones-{uuid4().hex}")
        brand = Brand(name="Example", slug=f"example-{uuid4().hex}")
        product = Product(
            store=new_store(),
            name="Example phone",
            slug=f"example-phone-{uuid4().hex}",
            category=category,
            brand=brand,
            specifications={},
            status="active",  # only sellable SKUs can be reserved
        )
        variant = ProductVariant(
            product=product,
            sku=f"SKU-{uuid4().hex}",
            name="Black",
            price=125000,
        )
        variant.inventory = InventoryBalance(on_hand=2, unavailable_quantity=0)
        session.add(product)
        session.flush()
        order = Order(
            order_number=f"ORD-{uuid4().hex}",
            checkout_idempotency_key=f"checkout-{uuid4().hex}",
            user_id=customer_id,
            subtotal=125000,
            total=125000,
            recipient_name="Test Customer",
            recipient_phone="0780000000",
            delivery_address_snapshot={"district": "Kigali"},
        )
        order.items.append(
            OrderItem(
                variant_id=variant.id,
                sku_snapshot=variant.sku,
                product_name_snapshot=product.name,
                variant_snapshot={},
                specifications_snapshot={},
                quantity=1,
                unit_price=125000,
                line_subtotal=125000,
                line_total=125000,
            )
        )
        create_order_with_reservations(
            session, needs_stores(order), expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        session.add(
            PaymentAttempt(
                order_id=order.id,
                method="cash_on_delivery",
                amount=125000,
                status="pending",
                idempotency_key=f"checkout:{order.id}",
            )
        )
        order_id = order.id
        session.commit()
        return order_id


def _count(session: Session, model, order_id: UUID) -> int:
    return session.scalar(select(func.count(model.id)).where(model.order_id == order_id)) or 0


def _order_audits(session: Session, order_id: UUID) -> list[AuditRecord]:
    return list(
        session.scalars(
            select(AuditRecord).where(
                AuditRecord.entity_id == str(order_id), AuditRecord.action == "order.status_change"
            )
        )
    )


def reservations(session: Session, order_id: UUID) -> list[StockReservation]:
    return list(
        session.scalars(select(StockReservation).where(StockReservation.order_id == order_id))
    )


def make_admin(db: Session) -> dict:
    return make_staff(
        db,
        "administrator",
        f"admin.{uuid4().hex[:8]}@example.com",
        f"+25078{uuid4().int % 10**7:07d}",
    )["headers"]


def _audit_count(session: Session, order_id: UUID) -> int:
    """Order audit events only; the inventory service audits its own inventory.* actions."""
    return (
        session.scalar(
            select(func.count(AuditRecord.id)).where(
                AuditRecord.entity_id == str(order_id), AuditRecord.action.like("order.%")
            )
        )
        or 0
    )


def test_customer_order_read_is_owned_and_hides_other_customers_orders(
    client: TestClient, session_factory, customer_auth: dict, second_customer_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    own = client.get(f"/api/v1/customers/me/orders/{order_id}", headers=customer_auth["headers"])
    other = client.get(
        f"/api/v1/customers/me/orders/{order_id}", headers=second_customer_auth["headers"]
    )
    assert own.status_code == 200 and own.json()["status"] == "received"
    assert other.status_code == 404


def test_order_status_lifecycle_follows_the_seller_order(
    client: TestClient, session_factory, db: Session, customer_auth: dict
):
    """ADR-014 phase 3: the store's seller moves its seller order; the order follows, with its
    history, audit and stock rules (confirming cash on delivery commits, dispatching issues)."""
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    [seller_order] = seller_orders(db, order_id)
    owner_id = db.scalar(select(Store.owner_user_id).where(Store.id == seller_order.store_id))
    for step in ("confirmed", "processing", "dispatched"):
        res = move(client, db, seller_order, step)
        assert res.status_code == 200 and res.json()["status"] == step
        assert res.json()["order_status"] == step
    late_cancel = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=make_admin(db),
    )
    delivered = move(client, db, seller_order, "delivered")
    assert late_cancel.status_code == 409
    assert delivered.status_code == 200 and delivered.json()["order_status"] == "delivered"

    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "delivered"
        assert [entry.status for entry in order.status_history] == [
            "received",
            "confirmed",
            "processing",
            "dispatched",
            "delivered",
        ]
        assert all(entry.actor_user_id == owner_id for entry in order.status_history[1:])
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order_id)
        )
        assert reservation is not None and reservation.status == "fulfilled"
        on_hand = session.scalar(
            select(InventoryBalance.on_hand)
            .join(ProductVariant)
            .join(StockReservation, StockReservation.variant_id == ProductVariant.id)
            .where(StockReservation.order_id == order_id)
        )
        assert on_hand == 1
        records = list(
            session.scalars(
                select(AuditRecord)
                .where(AuditRecord.entity_id == str(order_id))
                .order_by(AuditRecord.created_at, AuditRecord.id)
            )
        )
        changes = [
            r
            for r in records
            if r.action == "order.status_change" and r.change_summary["status"] == "success"
        ]
        assert len(changes) == 4
        assert all(r.change_summary["trigger"] == "seller_orders" for r in changes)
        assert all(r.actor_user_id == owner_id for r in changes)
        assert [r.action for r in records if r.action.startswith("inventory.")] == [
            "inventory.reserve",
            "inventory.reservation_commit",
            "inventory.dispatch",
        ]
        attempt = session.scalar(select(PaymentAttempt).where(PaymentAttempt.order_id == order_id))
        assert attempt is not None and attempt.status == "succeeded"  # cash on delivery (Q14)


@pytest.mark.parametrize(
    "requested", ["received", "confirmed", "processing", "dispatched", "delivered"]
)
def test_staff_cannot_move_an_order_except_to_cancel_it(
    client: TestClient, session_factory, db: Session, customer_auth: dict, requested: str
):
    # Owner decision 2: no administrator fulfilment controls; the order follows its stores.
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    res = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": requested},
        headers=make_admin(db),
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "order_status_follows_seller_orders"
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "received"
        assert _count(session, OrderStatusHistory, order_id) == 1
        assert [r.change_summary["status"] for r in _order_audits(session, order_id)] == [
            "conflict"
        ]


def test_skipped_and_repeated_seller_moves_conflict_without_mutation(
    client: TestClient, session_factory, db: Session, customer_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    [seller_order] = seller_orders(db, order_id)
    for step in ("processing", "dispatched", "delivered"):
        res = move(client, db, seller_order, step)
        assert res.status_code == 409 and res.json()["error"]["code"] == "invalid_transition"
    assert move(client, db, seller_order, "confirmed").status_code == 200
    again = move(client, db, seller_order, "confirmed")
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "confirmed"
        assert _count(session, OrderStatusHistory, order_id) == 2


def test_unknown_status_is_rejected_by_request_validation(
    client: TestClient, session_factory, db: Session, customer_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    response = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "on_hold"},
        headers=make_admin(db),
    )
    [seller_order] = seller_orders(db, order_id)
    for refused in ("on_hold", "cancelled", "received", "pending"):
        res = move(client, db, seller_order, refused)  # sellers cannot cancel (platform only)
        assert res.status_code == 422, refused
    assert response.status_code == 422
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "received"


def test_cancellation_releases_holds_cancels_seller_orders_and_is_terminal(
    client: TestClient, session_factory, db: Session, customer_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    headers = make_admin(db)
    cancelled = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled", "reason": "Customer asked by phone."},
        headers=headers,
    )
    repeated = client.patch(
        f"/api/v1/staff/orders/{order_id}/status", json={"status": "cancelled"}, headers=headers
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert repeated.status_code == 409 and repeated.json()["error"]["code"] == "invalid_transition"
    [seller_order] = seller_orders(db, order_id)
    assert seller_order.status == "cancelled" and seller_order.cancelled_at is not None
    assert [h.status for h in seller_order.history] == ["pending", "cancelled"]
    assert seller_order.history[-1].reason == "Customer asked by phone."
    assert move(client, db, seller_order, "confirmed").status_code == 409
    with session_factory() as session:
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order_id)
        )
        assert reservation is not None and reservation.status == "released"


def test_cancellation_never_releases_committed_stock(
    client: TestClient, session_factory, db: Session, customer_auth: dict
):
    # ADR-002: paid stock needs a separately approved refund/cancellation workflow.
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    with session_factory() as session:
        commit_order_reservations(session, order_id)
    cancelled = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=make_admin(db),
    )
    assert cancelled.status_code == 409
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "received"
        assert _count(session, OrderStatusHistory, order_id) == 1
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order_id)
        )
        assert reservation is not None and reservation.status == "committed"
    assert [s.status for s in seller_orders(db, order_id)] == ["pending"]


def test_only_authorized_staff_can_cancel_an_order(
    client: TestClient,
    session_factory,
    db: Session,
    customer_auth: dict,
    admin_auth: dict,
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    response = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=customer_auth["headers"],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    success = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=admin_auth["headers"],
    )
    assert success.status_code == 200
    assert (
        db.scalar(
            select(func.count(AuditRecord.id)).where(AuditRecord.action == "auth.access_denied")
        )
        == 1  # the customer (SC-05: no other role is refused)
    )


def test_assignment_requires_active_staff_and_is_audited(
    client: TestClient,
    session_factory,
    customer_auth: dict,
    admin_auth: dict,
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    path = f"/api/v1/staff/orders/{order_id}/assignment"
    valid = client.patch(
        path,
        json={"staff_user_id": str(admin_auth["user"].id)},
        headers=admin_auth["headers"],
    )
    customer_target = client.patch(
        path,
        json={"staff_user_id": customer_auth["user"]["id"]},
        headers=admin_auth["headers"],
    )
    missing_user_id = uuid4()
    missing_target = client.patch(
        path,
        json={"staff_user_id": str(missing_user_id)},
        headers=admin_auth["headers"],
    )
    assert valid.status_code == 200
    assert valid.json()["fulfilment_assignee_user_id"] == str(admin_auth["user"].id)
    assert customer_target.status_code == 422
    assert missing_target.status_code == 422
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.fulfilment_assignee_user_id == admin_auth["user"].id
        records = list(
            session.scalars(
                select(AuditRecord).where(
                    AuditRecord.entity_id == str(order_id),
                    AuditRecord.action == "order.fulfilment_assignment",
                )
            )
        )
        assert len(records) == 3
        success = next(record for record in records if record.change_summary["status"] == "success")
        failures = [record for record in records if record.change_summary["status"] == "failure"]
        assert success.actor_user_id == admin_auth["user"].id
        assert success.change_summary["staff_user_id"] == str(admin_auth["user"].id)
        assert {record.change_summary["requested_staff_user_id"] for record in failures} == {
            customer_auth["user"]["id"],
            str(missing_user_id),
        }


def test_assignment_denies_customer_and_reports_missing_order(
    client: TestClient, customer_auth: dict, admin_auth: dict
):
    missing_order_id = uuid4()
    response = client.patch(
        f"/api/v1/staff/orders/{missing_order_id}/assignment",
        json={"staff_user_id": str(admin_auth["user"].id)},
        headers=customer_auth["headers"],
    )
    assert response.status_code == 403
    status_path = f"/api/v1/staff/orders/{missing_order_id}/status"
    denied = client.patch(
        status_path, json={"status": "cancelled"}, headers=customer_auth["headers"]
    )
    assert denied.status_code == 403
    # The administrator may cancel orders, so a missing order is reported as such.
    for requested in ("cancelled", "confirmed"):
        missing = client.patch(
            status_path, json={"status": requested}, headers=admin_auth["headers"]
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "order_not_found"


def test_missing_order_is_not_found_for_authorized_staff(client: TestClient, admin_auth: dict):
    missing_order_id = uuid4()
    response = client.patch(
        f"/api/v1/staff/orders/{missing_order_id}/status",
        json={"status": "cancelled"},
        headers=admin_auth["headers"],
    )
    assert response.status_code == 404


def test_a_failed_stock_issue_rolls_back_the_seller_dispatch(
    client: TestClient, session_factory, db: Session, customer_auth: dict, monkeypatch
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    [seller_order] = seller_orders(db, order_id)
    for step in ("confirmed", "processing"):
        assert move(client, db, seller_order, step).status_code == 200

    def unavailable(*args, **kwargs):
        raise InventoryUnavailable("physical stock no longer covers committed reservation")

    monkeypatch.setattr(seller_order_service, "dispatch_order_inventory", unavailable)
    dispatch = move(client, db, seller_order, "dispatched")
    assert dispatch.status_code == 409
    assert dispatch.json()["error"]["code"] == "inventory_conflict"
    [seller_order] = seller_orders(db, order_id)
    assert seller_order.status == "processing" and seller_order.dispatched_at is None
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "processing"
        assert _count(session, OrderStatusHistory, order_id) == 3
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order_id)
        )
        assert reservation is not None and reservation.status == "committed"


def test_concurrent_seller_moves_serialize_on_the_order(
    session_factory, db: Session, customer_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    [row] = seller_orders(db, order_id)
    seller_order_id, store_id = row.id, row.store_id
    barrier = Barrier(2)

    def attempt() -> int:
        barrier.wait()
        with session_factory() as session:
            store = session.get(Store, store_id)
            assert store is not None
            seller = SellerContext(user=store.owner, store=store)
            try:
                SellerOrderService.change_status(
                    session, seller, seller_order_id, "confirmed", RequestContext(None, None)
                )
                return 200
            except AppError as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: attempt(), range(2)))
    assert outcomes == [200, 409]
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "confirmed"
        assert _count(session, OrderStatusHistory, order_id) == 2
        assert [r.status for r in reservations(session, order_id)] == ["committed"]


def test_audit_failure_rolls_back_the_seller_move_and_the_order(
    client: TestClient,
    session_factory,
    db: Session,
    customer_auth: dict,
    monkeypatch,
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    [seller_order] = seller_orders(db, order_id)
    headers = owner_headers(db, seller_order.store_id)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    try:
        client.patch(
            f"/api/v1/seller/orders/{seller_order.id}/status",
            json={"status": "confirmed"},
            headers=headers,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("audit failure should propagate to the test client")

    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "received"
        assert _count(session, OrderStatusHistory, order_id) == 1
        assert _audit_count(session, order_id) == 0
        assert [r.status for r in reservations(session, order_id)] == ["active"]
    assert [s.status for s in seller_orders(db, order_id)] == ["pending"]


def test_audit_failure_rolls_back_assignment(
    client: TestClient,
    session_factory,
    customer_auth: dict,
    admin_auth: dict,
    monkeypatch,
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))

    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    try:
        client.patch(
            f"/api/v1/staff/orders/{order_id}/assignment",
            json={"staff_user_id": str(admin_auth["user"].id)},
            headers=admin_auth["headers"],
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("audit failure should propagate to the test client")

    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.fulfilment_assignee_user_id is None
        assert _audit_count(session, order_id) == 0


def test_assignment_follows_the_fulfilment_permission(
    client: TestClient,
    session_factory,
    customer_auth: dict,
    admin_auth: dict,
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    path = f"/api/v1/staff/orders/{order_id}/assignment"
    body = {"staff_user_id": str(admin_auth["user"].id)}
    for denied in (customer_auth,):  # SC-05: the administrator is the only staff role
        assert client.patch(path, json=body, headers=denied["headers"]).status_code == 403
    response = client.patch(path, json=body, headers=admin_auth["headers"])
    assert response.status_code == 200
    assert response.json()["fulfilment_assignee_user_id"] == str(admin_auth["user"].id)
