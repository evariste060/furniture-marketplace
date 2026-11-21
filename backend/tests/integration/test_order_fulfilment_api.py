from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

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
    Product,
    ProductVariant,
    StockReservation,
)
from app.models.identity import User
from app.repositories.audit_repository import AuditRepository
from app.services.inventory import commit_order_reservations, create_order_with_reservations
from app.services.order_service import OrderService
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
            session, order, expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        order_id = order.id
        session.commit()
        return order_id


def _count(session: Session, model, order_id: UUID) -> int:
    return session.scalar(select(func.count(model.id)).where(model.order_id == order_id)) or 0


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


def test_order_status_lifecycle_updates_history_audit_and_inventory(
    client: TestClient, session_factory, customer_auth: dict, admin_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    headers = admin_auth["headers"]
    for next_status in ("confirmed", "processing"):
        response = client.patch(
            f"/api/v1/staff/orders/{order_id}/status",
            json={"status": next_status},
            headers=headers,
        )
        assert response.status_code == 200 and response.json()["status"] == next_status

    with session_factory() as session:
        assert commit_order_reservations(session, order_id).lines_changed == 1

    dispatched = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "dispatched"},
        headers=headers,
    )
    late_cancel = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=headers,
    )
    delivered = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "delivered"},
        headers=headers,
    )
    assert dispatched.status_code == delivered.status_code == 200
    assert late_cancel.status_code == 409
    assert delivered.json()["status"] == "delivered"

    with session_factory() as session:
        session.expire_all()
        order = session.get(Order, order_id)
        assert order is not None and order.status == "delivered"
        assert [entry.status for entry in order.status_history] == [
            "received",
            "confirmed",
            "processing",
            "dispatched",
            "delivered",
        ]
        assert all(
            entry.actor_user_id == admin_auth["user"].id and entry.created_at is not None
            for entry in order.status_history[1:]
        )
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order_id)
        )
        assert reservation is not None and reservation.status == "fulfilled"
        movement_quantity = session.scalar(
            select(InventoryBalance.on_hand)
            .join(ProductVariant)
            .join(StockReservation, StockReservation.variant_id == ProductVariant.id)
            .where(StockReservation.order_id == order_id)
        )
        assert movement_quantity == 1
        records = list(
            session.scalars(
                select(AuditRecord)
                .where(AuditRecord.entity_id == str(order_id))
                .order_by(AuditRecord.created_at, AuditRecord.id)
            )
        )
        order_records = [record for record in records if record.action.startswith("order.")]
        successes = [r for r in order_records if r.change_summary["status"] == "success"]
        assert [record.action for record in successes] == ["order.status_change"] * 4
        assert all(record.actor_user_id == admin_auth["user"].id for record in successes)
        assert [record.action for record in records if record.action.startswith("inventory.")] == [
            "inventory.reserve",
            "inventory.reservation_commit",
            "inventory.dispatch",
        ]


def test_invalid_repeated_and_skipped_transitions_conflict_without_mutation(
    client: TestClient, session_factory, customer_auth: dict, admin_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    for next_status in ("received", "processing", "delivered"):
        result = client.patch(
            f"/api/v1/staff/orders/{order_id}/status",
            json={"status": next_status},
            headers=admin_auth["headers"],
        )
        assert result.status_code == 409
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "received"
        assert _count(session, OrderStatusHistory, order_id) == 1
        assert _audit_count(session, order_id) == 3


def test_unknown_status_is_rejected_by_request_validation(
    client: TestClient, session_factory, customer_auth: dict, admin_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    response = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "on_hold"},
        headers=admin_auth["headers"],
    )
    assert response.status_code == 422
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "received"


@pytest.mark.parametrize("prefix", [(), ("confirmed",), ("confirmed", "processing")])
def test_cancellation_releases_reservation_and_terminal_status_cannot_change(
    client: TestClient,
    session_factory,
    customer_auth: dict,
    admin_auth: dict,
    prefix: tuple[str, ...],
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    for next_status in prefix:
        advanced = client.patch(
            f"/api/v1/staff/orders/{order_id}/status",
            json={"status": next_status},
            headers=admin_auth["headers"],
        )
        assert advanced.status_code == 200
    cancelled = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=admin_auth["headers"],
    )
    repeated = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "received"},
        headers=admin_auth["headers"],
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert repeated.status_code == 409
    with session_factory() as session:
        reservation = session.scalar(
            select(StockReservation).where(StockReservation.order_id == order_id)
        )
        assert reservation is not None and reservation.status == "released"


def test_cancellation_never_releases_committed_stock(
    client: TestClient, session_factory, customer_auth: dict, admin_auth: dict
):
    # ADR-002: paid stock needs a separately approved refund/cancellation workflow.
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    with session_factory() as session:
        commit_order_reservations(session, order_id)
    cancelled = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "cancelled"},
        headers=admin_auth["headers"],
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


def test_only_authorized_staff_can_change_order_status(
    client: TestClient,
    session_factory,
    db: Session,
    customer_auth: dict,
    admin_auth: dict,
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    for headers in (customer_auth["headers"],):  # SC-05: the administrator is the only staff role
        response = client.patch(
            f"/api/v1/staff/orders/{order_id}/status",
            json={"status": "confirmed"},
            headers=headers,
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "permission_denied"
    success = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "confirmed"},
        headers=admin_auth["headers"],
    )
    assert success.status_code == 200
    again = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "processing"},
        headers=admin_auth["headers"],
    )
    assert again.status_code == 200 and again.json()["status"] == "processing"
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
        status_path, json={"status": "confirmed"}, headers=customer_auth["headers"]
    )
    assert denied.status_code == 403
    # The administrator may fulfil orders, so a missing order is reported as such.
    missing = client.patch(status_path, json={"status": "confirmed"}, headers=admin_auth["headers"])
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "order_not_found"


def test_missing_order_is_not_found_for_authorized_staff(client: TestClient, admin_auth: dict):
    missing_order_id = uuid4()
    response = client.patch(
        f"/api/v1/staff/orders/{missing_order_id}/status",
        json={"status": "confirmed"},
        headers=admin_auth["headers"],
    )
    assert response.status_code == 404


def test_dispatch_without_committed_reservation_rolls_back_status(
    client: TestClient, session_factory, customer_auth: dict, admin_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    for next_status in ("confirmed", "processing"):
        response = client.patch(
            f"/api/v1/staff/orders/{order_id}/status",
            json={"status": next_status},
            headers=admin_auth["headers"],
        )
        assert response.status_code == 200
    dispatch = client.patch(
        f"/api/v1/staff/orders/{order_id}/status",
        json={"status": "dispatched"},
        headers=admin_auth["headers"],
    )
    assert dispatch.status_code == 409
    with session_factory() as session:
        order = session.get(Order, order_id)
        assert order is not None and order.status == "processing"
        assert _count(session, OrderStatusHistory, order_id) == 3
        assert _audit_count(session, order_id) == 3


def test_concurrent_status_requests_serialize_on_order_row(
    session_factory, customer_auth: dict, admin_auth: dict
):
    order_id = _new_reserved_order(session_factory, UUID(customer_auth["user"]["id"]))
    barrier = Barrier(2)
    actor_id = admin_auth["user"].id

    def attempt() -> int:
        barrier.wait()
        with session_factory() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            try:
                OrderService.change_status(
                    session,
                    order_id=order_id,
                    actor=actor,
                    new_status="confirmed",
                    ctx=RequestContext(None, None),
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


def test_audit_failure_rolls_back_status_and_history(
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
            f"/api/v1/staff/orders/{order_id}/status",
            json={"status": "confirmed"},
            headers=admin_auth["headers"],
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
