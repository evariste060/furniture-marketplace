"""Module 16 invoices over real HTTP on the least-privilege runtime role, in two API processes.

Proves the grants (invoices SELECT/INSERT, invoice_counters SELECT/INSERT/UPDATE): a verified
payment success issues the invoice, the customer downloads it from the other process, and the
runtime role can neither change nor delete an invoice, nor delete a counter.
"""

import json
import uuid

import psycopg
import pytest

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_checkout import delivery  # noqa: F401
from tests.postgres.test_pg_http import HTTP, one
from tests.postgres.test_pg_payments import paid_order, send

SELLER = {
    "seller.legal_name": "PG Test Electronics Ltd",
    "seller.tin": "PG-TIN-0001",
    "seller.address": "KG 7 Ave\nKigali",
}


@pytest.fixture
def seller(stack: Stack, admin: dict) -> None:
    res = HTTP.patch(f"{stack.servers[0]}/staff/settings", json=SELLER, headers=admin)
    assert res.status_code == 200, res.text


def test_a_paid_order_is_invoiced_and_downloadable_on_the_runtime_role(
    stack: Stack,
    delivery,  # noqa: F811
    seller,
    unique: str,
):
    buyer, order, started = paid_order(stack, unique, "inv")
    payload = json.dumps(
        {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "reference": started["reference"],
            "status": "succeeded",
            "amount": order["total"],
            "currency": "RWF",
        }
    ).encode()
    assert send(stack.servers[0], payload).status_code == 200
    with stack.owner() as conn:
        number, total, vat = one(
            conn,
            "SELECT invoice_number, total, vat_amount FROM invoices WHERE order_id = %s",
            order["id"],
        )
    assert number.startswith("INV-") and total == order["total"]
    res = HTTP.get(
        f"{stack.servers[1]}/customers/me/orders/{order['id']}/invoice", headers=buyer["headers"]
    )
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert res.headers["content-disposition"] == f'attachment; filename="{number}.pdf"'


def test_a_refused_invoice_is_recovered_once_on_the_runtime_role(
    stack: Stack,
    delivery,  # noqa: F811
    admin: dict,
    unique: str,
):
    with stack.owner() as conn:  # the seller details are unset while the payment succeeds
        conn.execute("DELETE FROM settings WHERE key LIKE 'seller.%'")
    _, order, started = paid_order(stack, unique, "rec")
    payload = json.dumps(
        {
            "event_id": f"evt-{uuid.uuid4().hex}",
            "reference": started["reference"],
            "status": "succeeded",
            "amount": order["total"],
            "currency": "RWF",
        }
    ).encode()
    assert send(stack.servers[0], payload).status_code == 200
    with stack.owner() as conn:
        (count,) = one(conn, "SELECT count(*) FROM invoices WHERE order_id = %s", order["id"])
    assert count == 0
    res = HTTP.patch(f"{stack.servers[0]}/staff/settings", json=SELLER, headers=admin)
    assert res.status_code == 200, res.text
    url = f"/staff/orders/{order['id']}/invoice"
    first = HTTP.post(f"{stack.servers[1]}{url}", headers=admin)
    assert first.status_code == 201 and first.json()["issued"] is True, first.text
    again = HTTP.post(f"{stack.servers[0]}{url}", headers=admin)
    assert again.status_code == 200 and again.json()["issued"] is False
    assert again.json()["invoice_number"] == first.json()["invoice_number"]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE invoices SET total = 0",
        "DELETE FROM invoices WHERE false",
        "DELETE FROM invoice_counters WHERE false",
    ],
)
def test_the_runtime_role_cannot_change_or_remove_invoices(stack: Stack, statement: str):
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)
