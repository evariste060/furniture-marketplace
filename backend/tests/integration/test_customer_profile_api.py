from fastapi.testclient import TestClient


def test_customer_profile_retrieval(client: TestClient, customer_auth: dict):
    response = client.get("/api/v1/customers/me", headers=customer_auth["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "customer.a@example.com"
    assert data["full_name"] == "Customer Alice"
    assert data["roles"] == ["customer"]
    assert "password_hash" not in data


def test_customer_profile_valid_update(client: TestClient, customer_auth: dict):
    payload = {
        "full_name": "Alice In Kigali",
        "phone": "+250788777888",
    }
    response = client.patch("/api/v1/customers/me", json=payload, headers=customer_auth["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Alice In Kigali"
    assert data["phone"] == "+250788777888"


def test_customer_profile_rejects_extra_protected_fields(client: TestClient, customer_auth: dict):
    # Customer attempts to escalate role or change email via profile patch
    payload = {
        "role": "admin",
        "email": "hacked@example.com",
    }
    response = client.patch("/api/v1/customers/me", json=payload, headers=customer_auth["headers"])
    assert response.status_code == 422


def test_customer_profile_unauthenticated(client: TestClient):
    response = client.get("/api/v1/customers/me")
    assert response.status_code == 401


def test_customer_profile_duplicate_phone_rejected(
    client: TestClient, customer_auth: dict, second_customer_auth: dict
):
    # Customer B attempts to update phone to Customer A's phone
    payload = {"phone": customer_auth["user"]["phone"]}
    response = client.patch(
        "/api/v1/customers/me", json=payload, headers=second_customer_auth["headers"]
    )
    assert response.status_code == 409
