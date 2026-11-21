import uuid

from fastapi.testclient import TestClient


def test_address_creation_auto_default(client: TestClient, customer_auth: dict):
    payload = {
        "recipient_name": "Alice Receiver",
        "phone": "+250788123456",
        "district": "Gasabo",
        "sector": "Kimironko",
        "cell": "Bibare",
        "street_address": "KG 11 Ave, House 42",
        "delivery_instructions": "Gate is black, call on arrival",
        "is_default": False,  # Should auto-become default because it's first address
    }
    response = client.post(
        "/api/v1/customers/me/addresses", json=payload, headers=customer_auth["headers"]
    )
    assert response.status_code == 201
    data = response.json()
    assert data["recipient_name"] == "Alice Receiver"
    assert data["district"] == "Gasabo"
    assert data["is_default"] is True  # Auto-default verified
    assert "id" in data
    assert data["user_id"] == customer_auth["user"]["id"]


def test_address_listing(client: TestClient, customer_auth: dict):
    # Create two addresses
    client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Address 1",
            "phone": "+250788123001",
            "district": "Gasabo",
            "street_address": "Street 1",
        },
        headers=customer_auth["headers"],
    )
    client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Address 2",
            "phone": "+250788123002",
            "district": "Nyarugenge",
            "street_address": "Street 2",
        },
        headers=customer_auth["headers"],
    )

    response = client.get("/api/v1/customers/me/addresses", headers=customer_auth["headers"])
    assert response.status_code == 200
    addresses = response.json()
    assert len(addresses) == 2


def test_address_retrieval_and_update(client: TestClient, customer_auth: dict):
    create_res = client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Before Update",
            "phone": "+250788111222",
            "district": "Gasabo",
            "street_address": "Street Original",
        },
        headers=customer_auth["headers"],
    )
    address_id = create_res.json()["id"]

    # Retrieve
    get_res = client.get(
        f"/api/v1/customers/me/addresses/{address_id}",
        headers=customer_auth["headers"],
    )
    assert get_res.status_code == 200
    assert get_res.json()["recipient_name"] == "Before Update"

    # Update
    update_res = client.put(
        f"/api/v1/customers/me/addresses/{address_id}",
        json={"recipient_name": "After Update", "district": "Kicukiro"},
        headers=customer_auth["headers"],
    )
    assert update_res.status_code == 200
    assert update_res.json()["recipient_name"] == "After Update"
    assert update_res.json()["district"] == "Kicukiro"


def test_default_address_switch_consistency(client: TestClient, customer_auth: dict):
    # Create address 1 (auto default)
    res1 = client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Addr 1",
            "phone": "+250788111001",
            "district": "Gasabo",
            "street_address": "KG 1",
        },
        headers=customer_auth["headers"],
    )
    addr1_id = res1.json()["id"]
    assert res1.json()["is_default"] is True

    # Create address 2 (set is_default=True)
    res2 = client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Addr 2",
            "phone": "+250788111002",
            "district": "Kicukiro",
            "street_address": "KK 2",
            "is_default": True,
        },
        headers=customer_auth["headers"],
    )
    addr2_id = res2.json()["id"]
    assert res2.json()["is_default"] is True

    # Verify address 1 is no longer default
    addr1_check = client.get(
        f"/api/v1/customers/me/addresses/{addr1_id}",
        headers=customer_auth["headers"],
    ).json()
    assert addr1_check["is_default"] is False

    # Switch default back to address 1 using dedicated default endpoint
    set_def_res = client.post(
        f"/api/v1/customers/me/addresses/{addr1_id}/default",
        headers=customer_auth["headers"],
    )
    assert set_def_res.status_code == 200
    assert set_def_res.json()["is_default"] is True

    # Verify address 2 is now not default
    addr2_check = client.get(
        f"/api/v1/customers/me/addresses/{addr2_id}",
        headers=customer_auth["headers"],
    ).json()
    assert addr2_check["is_default"] is False


def test_address_deletion(client: TestClient, customer_auth: dict):
    res = client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "To Delete",
            "phone": "+250788999000",
            "district": "Nyarugenge",
            "street_address": "KN 5",
        },
        headers=customer_auth["headers"],
    )
    addr_id = res.json()["id"]

    del_res = client.delete(
        f"/api/v1/customers/me/addresses/{addr_id}",
        headers=customer_auth["headers"],
    )
    assert del_res.status_code == 200

    # Verify gone
    get_res = client.get(
        f"/api/v1/customers/me/addresses/{addr_id}",
        headers=customer_auth["headers"],
    )
    assert get_res.status_code == 404


def test_cross_customer_isolation_and_rejection(
    client: TestClient, customer_auth: dict, second_customer_auth: dict
):
    # Customer A creates address
    res = client.post(
        "/api/v1/customers/me/addresses",
        json={
            "recipient_name": "Alice Private Address",
            "phone": "+250788123456",
            "district": "Gasabo",
            "street_address": "KG 100",
        },
        headers=customer_auth["headers"],
    )
    alice_addr_id = res.json()["id"]

    # Customer B attempts to read Customer A's address -> 404 (does not leak existence)
    res_b_read = client.get(
        f"/api/v1/customers/me/addresses/{alice_addr_id}",
        headers=second_customer_auth["headers"],
    )
    assert res_b_read.status_code == 404

    # Customer B attempts to update Customer A's address -> 404
    res_b_update = client.put(
        f"/api/v1/customers/me/addresses/{alice_addr_id}",
        json={"recipient_name": "Hacked Name"},
        headers=second_customer_auth["headers"],
    )
    assert res_b_update.status_code == 404

    # Customer B attempts to delete Customer A's address -> 404
    res_b_delete = client.delete(
        f"/api/v1/customers/me/addresses/{alice_addr_id}",
        headers=second_customer_auth["headers"],
    )
    assert res_b_delete.status_code == 404

    # Customer B attempts to set default on Customer A's address -> 404
    res_b_def = client.post(
        f"/api/v1/customers/me/addresses/{alice_addr_id}/default",
        headers=second_customer_auth["headers"],
    )
    assert res_b_def.status_code == 404

    # Customer B lists addresses -> does not see Alice's address
    res_b_list = client.get(
        "/api/v1/customers/me/addresses",
        headers=second_customer_auth["headers"],
    )
    assert res_b_list.status_code == 200
    b_ids = [a["id"] for a in res_b_list.json()]
    assert alice_addr_id not in b_ids


def test_invalid_address_uuid(client: TestClient, customer_auth: dict):
    random_uuid = uuid.uuid4()
    res = client.get(
        f"/api/v1/customers/me/addresses/{random_uuid}",
        headers=customer_auth["headers"],
    )
    assert res.status_code == 404
