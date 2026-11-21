"""Customer password change and log out on all devices (frontend phase 5, approved by the project
owner 2026-10-28)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operations import AuditRecord
from tests.conftest import make_staff

API = "/api/v1/auth"
OLD = "SecurePassword123!"
NEW = "Brand-New-Pass-42"
EMAIL = "customer.a@example.com"


def _login(client, password: str, identifier: str = EMAIL):
    return client.post(f"{API}/login", json={"identifier": identifier, "password": password})


def _audit(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def _change(client, headers: dict, current: str = OLD, new: str = NEW):
    return client.post(
        f"{API}/change-password",
        json={"current_password": current, "new_password": new},
        headers=headers,
    )


def test_a_customer_changes_the_password_and_other_sessions_end(client, db, customer_auth):
    other = _login(client, OLD).json()["session_token"]
    other_headers = {"Authorization": f"Bearer {other}"}

    res = _change(client, customer_auth["headers"])
    assert res.status_code == 200, res.text

    # This session stays; the other one is revoked.
    assert client.get(f"{API}/me", headers=customer_auth["headers"]).status_code == 200
    assert client.get(f"{API}/me", headers=other_headers).status_code == 401
    assert _login(client, OLD).status_code == 401
    assert _login(client, NEW).status_code == 200
    [record] = [
        r for r in _audit(db, "auth.password_change") if r.change_summary["status"] == "success"
    ]
    assert record.change_summary["sessions_revoked"] == 1
    assert NEW not in str(record.change_summary) and OLD not in str(record.change_summary)


def test_a_wrong_current_password_is_refused_and_counts_as_a_failed_login(
    client, db, customer_auth
):
    for _ in range(5):
        res = _change(client, customer_auth["headers"], current="Wrong-Pass-1")
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "current_password_invalid"
    # The login limit for this account is now reached, for the form and for login.
    limited = _change(client, customer_auth["headers"])
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert _login(client, OLD).status_code == 429
    assert len(_audit(db, "auth.password_change")) == 5


def test_the_new_password_must_be_strong(client, customer_auth):
    res = _change(client, customer_auth["headers"], new="weakpass")
    assert res.status_code == 422
    assert _login(client, OLD).status_code == 200


def test_staff_and_anonymous_callers_cannot_change_passwords(client, db):
    staff = make_staff(db, "administrator", "admin@example.com", "+250788000001")
    res = _change(client, staff["headers"], current=staff["password"])
    assert res.status_code == 403 and res.json()["error"]["code"] == "staff_password_managed"
    assert _change(client, {}).status_code == 401


def test_logging_out_everywhere_ends_every_session(client, db, customer_auth):
    other = _login(client, OLD).json()["session_token"]
    res = client.post(f"{API}/logout-all", headers=customer_auth["headers"])
    assert res.status_code == 200, res.text
    assert client.get(f"{API}/me", headers=customer_auth["headers"]).status_code == 401
    assert client.get(f"{API}/me", headers={"Authorization": f"Bearer {other}"}).status_code == 401
    [record] = _audit(db, "auth.logout_all")
    assert record.change_summary["sessions_revoked"] == 2
    assert client.post(f"{API}/logout-all").status_code == 401
