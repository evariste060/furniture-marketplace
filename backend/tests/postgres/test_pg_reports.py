"""Module 18 reports over real HTTP on the least-privilege runtime role, in two API processes.

Proves the existing grants suffice (reports only read: orders, payment_attempts, order_items,
products, product_variants, inventory_balances, stock_reservations) and that a delivered
cash-on-delivery order placed and fulfilled through one process is reported, and exported, by
the other. The sale is dated to a day no other test uses, as this database is shared.
"""

import io

from openpyxl import load_workbook

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_checkout import ADDRESS, delivery  # noqa: F401
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DAY = "2001-02-03"  # 10:00 in Kigali; the shared test database has no other sale that day


def test_a_delivered_cod_order_is_reported_and_exported_on_the_runtime_role(
    stack: Stack,
    delivery,  # noqa: F811
    admin: dict,
    unique: str,
):
    buyer = register(stack, stack.servers[0], f"report.{unique}@pg.test")
    variant_id, sku, _ = seed_sku(stack, on_hand=3)
    added = HTTP.post(
        f"{stack.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 2},
        headers=buyer["headers"],
    )
    assert added.status_code == 200, added.text
    placed = HTTP.post(
        f"{stack.servers[0]}/checkout",
        json={"address": ADDRESS, "payment_method": "cash_on_delivery"},
        headers={**buyer["headers"], "Idempotency-Key": f"report-{unique}"},
    )
    assert placed.status_code == 201, placed.text
    order = placed.json()["order"]
    for status in ("confirmed", "processing", "dispatched", "delivered"):
        res = HTTP.patch(
            f"{stack.servers[0]}/staff/orders/{order['id']}/status",
            json={"status": status},
            headers=admin,
        )
        assert res.status_code == 200, (status, res.text)
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT status FROM payment_attempts WHERE order_id = %s",
            order["id"],
        ) == ("succeeded",)  # §7 Q14: delivery marks the cash-on-delivery payment succeeded
        conn.execute(
            "UPDATE payment_attempts SET succeeded_at = %s WHERE order_id = %s",
            (f"{DAY}T10:00:00+02:00", order["id"]),
        )

    reports = f"{stack.servers[1]}/staff/reports"
    window = {"from": DAY, "to": DAY}
    sales = HTTP.get(f"{reports}/sales", params={**window, "group_by": "day"}, headers=admin)
    assert sales.status_code == 200, sales.text
    [period] = sales.json()["periods"]
    assert (period["period_start"], period["orders"], period["total"]) == (DAY, 1, order["total"])
    top = HTTP.get(f"{reports}/top-products", params=window, headers=admin)
    assert top.status_code == 200, top.text
    [item] = top.json()["items"]
    assert (item["units"], item["orders"]) == (2, 1)
    stock = HTTP.get(f"{reports}/stock", params={"size": 100}, headers=admin)
    assert stock.status_code == 200, stock.text
    assert stock.json()["totals"]["skus"] == stock.json()["total"] >= 1

    exported = HTTP.get(
        f"{reports}/sales/export", params={**window, "group_by": "week"}, headers=admin
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == XLSX
    rows = list(load_workbook(io.BytesIO(exported.content))["Sales"].iter_rows(values_only=True))
    assert rows[-1][0] == "Total" and rows[-1][2] == 1 and rows[-1][7] == order["total"]
    stock_file = HTTP.get(f"{reports}/stock/export", headers=admin)
    assert stock_file.status_code == 200, stock_file.text
    skus = [
        row[0]
        for row in load_workbook(io.BytesIO(stock_file.content))["Stock"].iter_rows(
            min_row=2, values_only=True
        )
    ]
    assert sku in skus
