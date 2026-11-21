"""Seller applications over real HTTP on the least-privilege runtime role, in two API processes
(ADR-014 phase 1): administrators deciding at the same moment have exactly one winner, a
suspension made through one process blocks the seller's existing session on the other, and the
runtime role can never delete a store or change its history."""

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, parallel, register

APPLICATION = {
    "contact_email": "shop@pg.test",
    "contact_phone": "0788 765 432",
    "district": "Gasabo",
}


def _apply(stack: Stack, base: str, unique: str, phone: str, name: str) -> tuple[dict, str]:
    seller = register(stack, base, email=f"seller.{name}.{unique}@pg.test", phone=phone)
    res = HTTP.post(
        f"{base}/seller/application",
        json={**APPLICATION, "name": f"{name} {unique}"},
        headers=seller["headers"],
    )
    assert res.status_code == 201, res.text
    return seller, res.json()["id"]


def test_concurrent_decisions_across_processes_have_one_winner(
    stack: Stack, admin: dict, unique: str, phone_factory
):
    _, store_id = _apply(stack, stack.servers[0], unique, phone_factory(), "race")
    bodies = [
        {"status": "approved"},
        {"status": "rejected", "reason": "Rejected in a concurrency test."},
    ] * 4

    def decide(i: int):
        return HTTP.patch(
            f"{stack.servers[i % 2]}/staff/sellers/{store_id}/status",
            json=bodies[i],
            headers=admin,
        )

    results = parallel(decide, range(len(bodies)), workers=8)
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1, [r.text for r in results]
    assert set(codes) == {200, 409}
    assert all(
        r.json()["error"]["code"] == "invalid_store_transition"
        for r in results
        if r.status_code == 409
    )
    with stack.owner() as conn:
        rows = conn.execute(
            "SELECT status FROM store_status_history WHERE store_id = %s ORDER BY created_at",
            (store_id,),
        ).fetchall()
    assert len(rows) == 2 and rows[0][0] == "pending"


def test_a_suspension_blocks_the_existing_session_on_another_process(
    stack: Stack, admin: dict, unique: str, phone_factory
):
    seller, store_id = _apply(stack, stack.servers[0], unique, phone_factory(), "halt")
    approved = HTTP.patch(
        f"{stack.servers[0]}/staff/sellers/{store_id}/status",
        json={"status": "approved"},
        headers=admin,
    )
    assert approved.status_code == 200, approved.text
    assert (
        HTTP.get(f"{stack.servers[1]}/seller/store", headers=seller["headers"]).status_code == 200
    )
    suspended = HTTP.patch(
        f"{stack.servers[1]}/staff/sellers/{store_id}/status",
        json={"status": "suspended", "reason": "Suspended across processes."},
        headers=admin,
    )
    assert suspended.status_code == 200, suspended.text
    for base in stack.servers:
        res = HTTP.get(f"{base}/seller/store", headers=seller["headers"])
        assert res.status_code == 403 and res.json()["error"]["code"] == "seller_not_approved"


def test_case_insensitive_names_hold_under_concurrent_applications(
    stack: Stack, unique: str, phone_factory
):
    sellers = [
        register(stack, stack.servers[0], email=f"same.{i}.{unique}@pg.test", phone=phone_factory())
        for i in range(4)
    ]
    names = [
        f"Same Name {unique}",
        f"SAME NAME {unique}",
        f"same name {unique}",
        f"Same name {unique}",
    ]

    def submit(i: int):
        return HTTP.post(
            f"{stack.servers[i % 2]}/seller/application",
            json={**APPLICATION, "name": names[i]},
            headers=sellers[i]["headers"],
        )

    results = parallel(submit, range(4), workers=4)
    assert sorted(r.status_code for r in results) == [201, 409, 409, 409], [r.text for r in results]
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {
        "store_name_taken"
    }


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM stores WHERE false",
        "DELETE FROM store_status_history WHERE false",
        "UPDATE store_status_history SET reason = NULL WHERE false",
    ],
)
def test_runtime_role_cannot_delete_stores_or_rewrite_their_history(stack: Stack, statement: str):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)
