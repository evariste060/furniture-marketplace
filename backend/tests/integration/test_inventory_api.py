"""Staff inventory API (administrator only; ADR-002 stock lifecycle approved 2026-10-22)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models import StockMovement
from app.models.operations import AuditRecord
from app.services import inventory as inv
from tests.support.commerce import new_order, on_hand, seed_sku, soon

BASE = "/api/v1/inventory"


@pytest.fixture
def sku(db: Session):
    variant = seed_sku(db, on_hand=5)
    db.commit()
    return variant


def post(client, sku_code, body, headers, key="adjust-key-0001"):
    return client.post(
        f"{BASE}/{sku_code}/adjustments",
        json=body,
        headers={**headers, **({"Idempotency-Key": key} if key else {})},
    )


def movements(db: Session) -> int:
    db.expire_all()
    return db.execute(select(func.count(StockMovement.id))).scalar_one()


def test_admin_reads_stock_figures(client: TestClient, admin_auth: dict, sku, db: Session):
    order = new_order({sku.id: 2})
    inv.create_order_with_reservations(db, order, expires_at=soon())
    db.commit()
    res = client.get(f"{BASE}/{sku.sku}", headers=admin_auth["headers"])
    assert res.status_code == 200
    assert res.json() == {
        "sku": sku.sku,
        "variant_id": str(sku.id),
        "is_sellable": True,
        "has_inventory_record": True,
        "on_hand": 5,
        "unavailable_quantity": 0,
        "reserved_quantity": 2,
        "committed_quantity": 0,
        "available_quantity": 3,
    }
    assert client.get(f"{BASE}/NO-SUCH-SKU", headers=admin_auth["headers"]).status_code == 404


def test_receipt_is_applied_audited_and_replayed_idempotently(
    client: TestClient, admin_auth: dict, sku, db: Session
):
    body = {"reason": "receipt", "quantity_delta": 4, "note": "Supplier delivery"}
    first = post(client, sku.sku, body, admin_auth["headers"])
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["replayed"] is False and data["inventory"]["on_hand"] == 9
    assert data["movement"]["quantity_delta"] == 4

    again = post(client, sku.sku, body, admin_auth["headers"])
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["movement"]["id"] == data["movement"]["id"]
    assert on_hand(db, sku.id) == 9 and movements(db) == 1

    (record,) = db.scalars(select(AuditRecord).where(AuditRecord.action == "inventory.adjust"))
    assert record.actor_user_id == admin_auth["user"].id
    assert record.change_summary["on_hand_before"] == 5
    assert record.change_summary["on_hand_after"] == 9

    reused = post(client, sku.sku, {**body, "quantity_delta": 5}, admin_auth["headers"])
    assert reused.status_code == 409 and on_hand(db, sku.id) == 9


def test_removal_below_reserved_stock_is_refused(
    client: TestClient, admin_auth: dict, sku, db: Session
):
    inv.create_order_with_reservations(db, new_order({sku.id: 4}), expires_at=soon())
    db.commit()
    res = post(
        client, sku.sku, {"reason": "adjustment", "quantity_delta": -2}, admin_auth["headers"]
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "insufficient_stock"
    assert "Insufficient stock" in res.json()["error"]["message"]
    ok = post(
        client,
        sku.sku,
        {"reason": "adjustment", "quantity_delta": -1},
        admin_auth["headers"],
        "adjust-key-0002",
    )
    assert ok.status_code == 201
    assert on_hand(db, sku.id) == 4 and movements(db) == 1


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ({"reason": "adjustment", "quantity_delta": 0}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": -1}, "valid-key-01"),
        ({"reason": "inspected_return", "quantity_delta": -1}, "valid-key-01"),
        ({"reason": "dispatch", "quantity_delta": -1}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": 1.5}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": "3"}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": 2**31}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": 1, "on_hand": 99}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": 1, "note": "x" * 501}, "valid-key-01"),
        ({"reason": "receipt", "quantity_delta": 1}, None),
        ({"reason": "receipt", "quantity_delta": 1}, "short"),
        ({"reason": "receipt", "quantity_delta": 1}, "bad key with spaces"),
    ],
)
def test_invalid_adjustments_are_rejected(
    client: TestClient, admin_auth: dict, sku, db: Session, body, key
):
    res = post(client, sku.sku, body, admin_auth["headers"], key)
    assert res.status_code == 422
    assert on_hand(db, sku.id) == 5 and movements(db) == 0


def test_stock_access_follows_the_role_matrix(
    client: TestClient,
    sku,
    db: Session,
    customer_auth: dict,
    admin_auth: dict,
):
    """TC-16: the Marketplace Administrator (the only staff role, SC-05) reads and adjusts
    stock; customers do neither."""
    body = {"reason": "receipt", "quantity_delta": 1}
    expected = {  # role: (auth, read status, adjust status)
        "administrator": (admin_auth, 200, 201),
        "customer": (customer_auth, 403, 403),
    }
    for role, (who, read_status, adjust_status) in expected.items():
        read = client.get(f"{BASE}/{sku.sku}", headers=who["headers"])
        assert read.status_code == read_status, role
        adjust = post(client, sku.sku, body, who["headers"], f"matrix-{role}-key")
        assert adjust.status_code == adjust_status, role
        if adjust_status == 403:
            assert adjust.json()["error"]["code"] == "permission_denied"
    assert client.get(f"{BASE}/{sku.sku}").status_code == 401
    assert post(client, sku.sku, body, {}).status_code == 401
    assert on_hand(db, sku.id) == 6 and movements(db) == 1  # the administrator
    db.expire_all()
    denied = db.scalar(
        select(func.count(AuditRecord.id)).where(AuditRecord.action == "auth.access_denied")
    )
    assert denied == 2  # customer read and adjust


def test_idempotency_keys_are_scoped_to_the_calling_staff_member(
    client: TestClient, admin_auth: dict, sku, db: Session
):
    from tests.conftest import make_staff

    other = make_staff(db, "administrator", "admin2@example.com", "+250788000009")
    body = {"reason": "receipt", "quantity_delta": 1}
    assert post(client, sku.sku, body, admin_auth["headers"], "shared-key-1").status_code == 201
    assert post(client, sku.sku, body, other["headers"], "shared-key-1").status_code == 201
    assert on_hand(db, sku.id) == 7


def test_unknown_sku_adjustment_returns_404(client: TestClient, admin_auth: dict, db: Session):
    body = {"reason": "receipt", "quantity_delta": 1}
    assert post(client, f"NOPE-{uuid.uuid4().hex}", body, admin_auth["headers"]).status_code == 404


def test_reservation_finalization_is_not_exposed_over_http():
    paths = app.openapi()["paths"]
    inventory_paths = {p for p in paths if "inventory" in p or "reservation" in p}
    assert inventory_paths == {
        "/api/v1/inventory",  # module 10 stock list, read-only
        "/api/v1/inventory/{sku}",
        "/api/v1/inventory/{sku}/adjustments",
        # ADR-014 phase 2: the seller's own stock, the same read and adjust, nothing more.
        "/api/v1/seller/inventory",
        "/api/v1/seller/inventory/{sku}",
        "/api/v1/seller/inventory/{sku}/adjustments",
    }
    assert not [p for p in paths if "reservation" in p]
    assert set(paths["/api/v1/seller/inventory"]) == {"get"}
    assert set(paths["/api/v1/seller/inventory/{sku}"]) == {"get"}
    assert set(paths["/api/v1/seller/inventory/{sku}/adjustments"]) == {"post"}
    assert set(paths["/api/v1/inventory"]) == {"get"}
    assert set(paths["/api/v1/inventory/{sku}"]) == {"get"}
    assert set(paths["/api/v1/inventory/{sku}/adjustments"]) == {"post"}
    documented = paths["/api/v1/inventory/{sku}/adjustments"]["post"]["responses"]
    assert {"200", "201", "401", "403", "404", "409", "422"} <= set(documented)
