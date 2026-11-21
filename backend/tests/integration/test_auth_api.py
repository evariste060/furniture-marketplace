from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_session_token
from app.models.session import UserSession


def test_valid_registration_both_identifiers(client: TestClient):
    payload = {
        "email": "kigali.shopper@example.com",
        "phone": "+250788123001",
        "full_name": "Kigali Shopper",
        "password": "StrongPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "kigali.shopper@example.com"
    assert data["user"]["phone"] == "+250788123001"
    assert data["user"]["roles"] == ["customer"]
    assert data["user"]["is_active"] is True
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]
    # With an email the account waits for verification (2026-11-12): no session yet.
    assert data["verification_required"] is True
    assert data["session_token"] is None and data["token_type"] is None
    assert data["expires_at"] is None


def test_valid_registration_phone_only(client: TestClient):
    payload = {
        "phone": "0788123002",
        "full_name": "Phone Only User",
        "password": "StrongPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] is None
    assert data["user"]["phone"] == "+250788123002"
    # No email to verify: signed in at once, as before (owner decision 2026-11-12).
    assert data["verification_required"] is False
    assert data["session_token"] and data["token_type"] == "bearer" and data["expires_at"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['session_token']}"})
    assert me.status_code == 200


def test_valid_registration_email_only(client: TestClient):
    payload = {
        "email": "emailonly@example.com",
        "full_name": "Email Only User",
        "password": "StrongPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "emailonly@example.com"
    assert data["user"]["phone"] is None


def test_invalid_registration_missing_identifiers(client: TestClient):
    payload = {
        "full_name": "No Identifier User",
        "password": "StrongPassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_invalid_registration_weak_password(client: TestClient):
    payload = {
        "email": "weak@example.com",
        "full_name": "Weak Pass User",
        "password": "weak",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_duplicate_registration_rejected(client: TestClient, customer_auth: dict):
    # Duplicate email
    payload_email = {
        "email": "customer.a@example.com",
        "phone": "+250788999888",
        "full_name": "Duplicate Email",
        "password": "StrongPassword123!",
    }
    res_email = client.post("/api/v1/auth/register", json=payload_email)
    assert res_email.status_code == 409
    assert res_email.json()["error"]["code"] == "email_taken"
    assert "email already exists" in res_email.json()["error"]["message"].lower()

    # Duplicate phone
    payload_phone = {
        "email": "unique.email@example.com",
        "phone": "+250788111222",
        "full_name": "Duplicate Phone",
        "password": "StrongPassword123!",
    }
    res_phone = client.post("/api/v1/auth/register", json=payload_phone)
    assert res_phone.status_code == 409
    assert res_phone.json()["error"]["code"] == "phone_taken"
    assert "phone number already exists" in res_phone.json()["error"]["message"].lower()


def test_successful_login_by_email(client: TestClient, customer_auth: dict):
    payload = {
        "identifier": "customer.a@example.com",
        "password": "SecurePassword123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "customer.a@example.com"
    assert "session_token" in data


def test_successful_login_by_phone(client: TestClient, customer_auth: dict):
    payload = {
        "identifier": "+250788111222",
        "password": "SecurePassword123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["phone"] == "+250788111222"
    assert "session_token" in data


def test_login_invalid_credentials(client: TestClient, customer_auth: dict):
    # Wrong password
    res1 = client.post(
        "/api/v1/auth/login",
        json={"identifier": "customer.a@example.com", "password": "WrongPassword!"},
    )
    assert res1.status_code == 401

    # Nonexistent user
    res2 = client.post(
        "/api/v1/auth/login",
        json={"identifier": "nonexistent@example.com", "password": "SecurePassword123!"},
    )
    assert res2.status_code == 401


def test_unauthenticated_access_rejected(client: TestClient):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_authenticated_me_retrieval(client: TestClient, customer_auth: dict):
    response = client.get("/api/v1/auth/me", headers=customer_auth["headers"])
    assert response.status_code == 200
    assert response.json()["email"] == "customer.a@example.com"


def test_logout_and_session_revocation(client: TestClient, customer_auth: dict):
    headers = customer_auth["headers"]

    # Before logout, /auth/me succeeds
    res_before = client.get("/api/v1/auth/me", headers=headers)
    assert res_before.status_code == 200

    # Logout
    res_logout = client.post("/api/v1/auth/logout", headers=headers)
    assert res_logout.status_code == 200
    assert "logged out" in res_logout.json()["message"].lower()

    # After logout, the revoked session token cannot be reused
    res_after = client.get("/api/v1/auth/me", headers=headers)
    assert res_after.status_code == 401


def test_expired_session_rejected(client: TestClient, customer_auth: dict, db: Session):
    token = customer_auth["token"]
    token_h = hash_session_token(token)

    # Force expiry in the database
    session = db.query(UserSession).filter_by(token_hash=token_h).first()
    assert session is not None
    session.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    # Attempt request with expired session
    response = client.get("/api/v1/auth/me", headers=customer_auth["headers"])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"
    assert "expired" in response.json()["error"]["message"].lower()
    assert response.headers["www-authenticate"] == "Bearer"
