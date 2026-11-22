"""Drive orders through their stores' seller orders (ADR-014 phase 3).

Staff no longer confirm, process, dispatch or deliver an order (owner decision 2, 2026-11-21):
each store's seller moves its own seller order and the order follows. These helpers move every
seller order of an order, as its own store's owner, through the real seller API, so the
notifications, audit and rollup run exactly as in production.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_session_token, hash_session_token
from app.models import SellerOrder, Store, UserSession

SELLER_ORDERS = "/api/v1/seller/orders"
STEPS = ("confirmed", "processing", "dispatched", "delivered")
RANK = {"pending": 0, **{s: i + 1 for i, s in enumerate(STEPS)}}


def owner_headers(db: Session, store_id: UUID) -> dict:
    """A fresh bearer session for the store's owner (test-only, like conftest.make_staff)."""
    owner_id = db.scalar(select(Store.owner_user_id).where(Store.id == store_id))
    assert owner_id is not None
    raw = generate_session_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            user_id=owner_id,
            token_hash=hash_session_token(raw),
            last_active_at=now,
            expires_at=now + timedelta(days=1),
        )
    )
    db.commit()
    return {"Authorization": f"Bearer {raw}"}


def seller_orders(db: Session, order_id: UUID | str) -> list[SellerOrder]:
    db.expire_all()
    return list(
        db.scalars(
            select(SellerOrder)
            .where(SellerOrder.order_id == UUID(str(order_id)))
            .order_by(SellerOrder.store_name_snapshot, SellerOrder.id)
        )
    )


def move(client: TestClient, db: Session, seller_order: SellerOrder, status: str):
    """One seller move through PATCH /seller/orders/{id}/status as the store's owner."""
    return client.patch(
        f"{SELLER_ORDERS}/{seller_order.id}/status",
        json={"status": status},
        headers=owner_headers(db, seller_order.store_id),
    )


def advance(client: TestClient, db: Session, order_id: UUID | str, target: str) -> None:
    """Move every seller order of the order step by step until each is at `target`, so the
    order itself reaches `target` (the stores confirm, then process, dispatch and deliver)."""
    for step in STEPS[: STEPS.index(target) + 1]:
        for row in seller_orders(db, order_id):
            if RANK[row.status] < RANK[step]:
                res = move(client, db, row, step)
                assert res.status_code == 200, (step, res.text)


def client_db(client: TestClient) -> Session:
    """The test session the client's requests use (conftest's get_db override yields it)."""
    from app.db.session import get_db

    return next(client.app.dependency_overrides[get_db]())  # type: ignore[attr-defined]


STAFF_ORDERS = "/api/v1/staff/orders"


def step(client: TestClient, order_id: UUID | str, status: str, staff_headers: dict) -> None:
    """One step of an order as the tests wrote it before phase 3: `cancelled` is the
    administrator's (the platform's); any other status is reached by the stores moving their
    seller orders (owner decision 2)."""
    if status == "cancelled":
        res = client.patch(
            f"{STAFF_ORDERS}/{order_id}/status", json={"status": status}, headers=staff_headers
        )
        assert res.status_code == 200, res.text
        return
    advance(client, client_db(client), order_id, status)


def order_move(client: TestClient, order_id: UUID | str, status: str, staff_headers: dict):
    """One order step returning the response, for tests that check it: `cancelled` through the
    staff route; any other status by each seller order not yet there moving to it (the first
    refusal, else the last response). Asking again for a status already reached is the seller's
    409 invalid_transition, as a repeated staff change was."""
    if status == "cancelled":
        return client.patch(
            f"{STAFF_ORDERS}/{order_id}/status", json={"status": status}, headers=staff_headers
        )
    db = client_db(client)
    rows = seller_orders(db, order_id)
    behind = [r for r in rows if RANK.get(r.status, 99) < RANK.get(status, 0)] or rows[:1]
    res = None
    for row in behind:
        res = move(client, db, row, status)
        if res.status_code != 200:
            return res
    return res
