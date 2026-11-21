from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from tests.conftest import _register


def test_audit_logs_persisted_for_auth_lifecycle(client: TestClient, admin_auth: dict):
    # Perform register (then verify the email and sign in, 2026-11-12), profile, logout
    customer = _register(client, "audit.test@example.com", "+250788666777", "Audit Test Subject")
    token = customer["token"]
    headers = customer["headers"]

    # Profile update
    client.patch(
        "/api/v1/customers/me",
        json={"full_name": "Audit Updated Name"},
        headers=headers,
    )

    # Address creation
    client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Audit Recipient",
            "phone": "+250788666777",
            "district": "Gasabo",
            "street_address": "KG 100",
        },
        headers=headers,
    )

    # Logout
    client.post("/api/v1/auth/logout", headers=headers)

    # Admin queries audit logs
    admin_headers = admin_auth["headers"]
    audit_res = client.get("/api/v1/audit-logs", headers=admin_headers)
    assert audit_res.status_code == 200
    body = audit_res.json()
    events = body["items"]
    assert len(events) >= 4 and body["total"] >= len(events)
    assert (body["page"], body["size"]) == (1, 20)

    actions = [e["action"] for e in events]
    assert "auth.register" in actions
    assert "user.profile.update" in actions
    assert "address.create" in actions
    assert "auth.logout" in actions
    assert "auth.email_verify" in actions

    # Verify no plaintext passwords or session tokens are leaked in audit details
    for event in events:
        details_str = str(event.get("change_summary", "")).lower()
        assert "securepassword123!" not in details_str
        assert token.lower() not in details_str


def test_audit_log_access_control(
    client: TestClient,
    customer_auth: dict,
    sales_auth: dict,
    finance_auth: dict,
    admin_auth: dict,
):
    # Unauthenticated rejected
    assert client.get("/api/v1/audit-logs").status_code == 401

    # Customer rejected
    assert client.get("/api/v1/audit-logs", headers=customer_auth["headers"]).status_code == 403

    # Sales staff rejected
    assert client.get("/api/v1/audit-logs", headers=sales_auth["headers"]).status_code == 403

    # Finance (audit:read, 2026-10-25) and admin allowed
    assert client.get("/api/v1/audit-logs", headers=finance_auth["headers"]).status_code == 200
    assert client.get("/api/v1/audit-logs", headers=admin_auth["headers"]).status_code == 200


def test_audit_records_immutable_no_modification_endpoints(client: TestClient, admin_auth: dict):
    headers = admin_auth["headers"]
    fake_id = "00000000-0000-0000-0000-000000000000"

    # PUT/PATCH/DELETE endpoints do NOT exist on /audit-logs
    res_put = client.put(f"/api/v1/audit-logs/{fake_id}", json={}, headers=headers)
    assert res_put.status_code in (404, 405)

    res_patch = client.patch(f"/api/v1/audit-logs/{fake_id}", json={}, headers=headers)
    assert res_patch.status_code in (404, 405)

    res_delete = client.delete(f"/api/v1/audit-logs/{fake_id}", headers=headers)
    assert res_delete.status_code in (404, 405)


def test_audit_log_pages_are_consistent(client: TestClient, admin_auth: dict, customer_auth: dict):
    headers = admin_auth["headers"]
    for _ in range(3):  # each successful login writes an auth.login audit record
        login = {"identifier": "customer.a@example.com", "password": "SecurePassword123!"}
        assert client.post("/api/v1/auth/login", json=login).status_code == 200
    everything = client.get("/api/v1/audit-logs", params={"size": 100}, headers=headers).json()
    assert everything["total"] == len(everything["items"]) >= 3

    second = client.get("/api/v1/audit-logs", params={"page": 2, "size": 1}, headers=headers)
    assert second.status_code == 200
    body = second.json()
    assert (body["total"], body["page"], body["size"]) == (everything["total"], 2, 1)
    assert [e["id"] for e in body["items"]] == [everything["items"][1]["id"]]

    beyond = client.get("/api/v1/audit-logs", params={"page": 999}, headers=headers).json()
    assert beyond["items"] == [] and beyond["total"] == everything["total"]

    for bad in ({"page": 0}, {"size": 0}, {"size": 101}, {"limit": 5}):
        res = client.get("/api/v1/audit-logs", params=bad, headers=headers)
        if "limit" in bad:  # the old parameter is simply not recognised any more
            assert res.status_code == 200 and res.json()["size"] == 20
        else:
            assert res.status_code == 422
            assert res.json()["error"]["code"] == "validation_error"


def _login_three_times(client: TestClient) -> None:
    # A phone-only customer: registration signs in without a login, so these are the only three.
    body = {"phone": "0788123999", "full_name": "Login Subject", "password": "SecurePassword123!"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    login = {"identifier": "0788123999", "password": "SecurePassword123!"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=login).status_code == 200


def _logins(client: TestClient, headers: dict, **params) -> list[dict]:
    res = client.get(
        "/api/v1/audit-logs",
        params={"action": "auth.login", "size": 100, **params},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["items"]


def test_audit_log_date_range_is_inclusive_and_combines_with_filters(
    client: TestClient, admin_auth: dict
):
    _login_three_times(client)
    headers = admin_auth["headers"]
    logins = _logins(client, headers)  # newest first
    assert len(logins) == 3
    newest, middle, oldest = logins
    t = datetime.fromisoformat(middle["created_at"])

    since = _logins(client, headers, **{"from": t.isoformat()})
    assert [e["id"] for e in since] == [newest["id"], middle["id"]]  # from is inclusive
    until = _logins(client, headers, to=t.isoformat())
    assert [e["id"] for e in until] == [middle["id"], oldest["id"]]  # to is inclusive
    exact = _logins(client, headers, **{"from": t.isoformat(), "to": t.isoformat()})
    assert [e["id"] for e in exact] == [middle["id"]]

    just_after = (t + timedelta(microseconds=1)).isoformat()
    assert [e["id"] for e in _logins(client, headers, **{"from": just_after})] == [newest["id"]]

    # The same instant written with Kigali's offset selects the same records.
    kigali = t.astimezone(timezone(timedelta(hours=2))).isoformat()
    assert [e["id"] for e in _logins(client, headers, to=kigali)] == [middle["id"], oldest["id"]]


def test_audit_log_date_range_is_validated(client: TestClient, admin_auth: dict):
    headers = admin_auth["headers"]
    reversed_range = client.get(
        "/api/v1/audit-logs",
        params={"from": "2026-10-23T12:00:00+02:00", "to": "2026-10-23T11:00:00+02:00"},
        headers=headers,
    )
    assert reversed_range.status_code == 422
    error = reversed_range.json()["error"]
    assert error["code"] == "validation_error" and error["details"][0]["loc"] == ["query", "from"]

    for bad in ({"from": "2026-10-23T12:00:00"}, {"to": "yesterday"}, {"from": "2026-13-01"}):
        res = client.get("/api/v1/audit-logs", params=bad, headers=headers)
        assert res.status_code == 422, bad
        assert res.json()["error"]["code"] == "validation_error"


def test_audit_log_date_filter_stays_administrator_only(
    client: TestClient, sales_auth: dict, management_auth: dict
):
    params = {"from": "2026-01-01T00:00:00+00:00"}
    for who in (sales_auth, management_auth):
        res = client.get("/api/v1/audit-logs", params=params, headers=who["headers"])
        assert res.status_code == 403
