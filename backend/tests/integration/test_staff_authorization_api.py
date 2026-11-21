"""Staff identity, provisioning and administration (TC-16, PR-15; ADR-006 2026-10-22).

PostgreSQL per-test schema via the shared fixtures. Concurrency and the least-privilege runtime
role over real HTTP are covered in tests/postgres.
"""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import verify_password
from app.models.identity import StaffRoleAssignment, User
from app.models.operations import AuditRecord
from app.models.session import UserSession
from app.repositories.audit_repository import AuditRepository
from app.schemas.staff import StaffCreateRequest, StaffRoleName
from app.services.staff_service import StaffBootstrapError, StaffService
from tests.conftest import make_staff, verify_email
from tests.support.credentials import random_password

STAFF = "/api/v1/staff"
LOGIN = "/api/v1/auth/login"
SECRET_FIELDS = {"password", "password_hash", "token_hash", "session_token"}
# The final matrix (project owner, 2026-10-26; plan §3).
SALES_PERMS = [
    "catalog:manage",
    "catalog:read",
    "inventory:adjust",
    "inventory:read",
    "orders:read",
    "promotions:read",
    "quotes:manage",
    "reviews:moderate",
    "services:manage",
    "services:read",
    "staff:self_read",
    "support:read",
    "support:reply",
]
OPERATIONS_PERMS = [
    "catalog:read",
    "delivery:read",
    "inventory:adjust",
    "inventory:read",
    "orders:fulfil",
    "orders:read",
    "staff:self_read",
]
MANAGEMENT_PERMS = [
    "catalog:read",
    "content:manage",
    "delivery:read",
    "inventory:read",
    "orders:read",
    "payments:read",
    "promotions:read",
    "reports:read",
    "services:read",
    "settings:read",
    "staff:self_read",
    "support:read",
]
FINANCE_PERMS = ["audit:read", "orders:read", "payments:read", "reports:read", "staff:self_read"]
ADMIN_PERMS = [
    "audit:read",
    "catalog:manage",
    "catalog:read",
    "content:manage",
    "delivery:manage",
    "delivery:read",
    "inventory:adjust",
    "inventory:read",
    "invoices:recover",
    "notifications:manage",
    "orders:fulfil",
    "orders:read",
    "payments:manage",
    "payments:read",
    "promotions:manage",
    "promotions:read",
    "quotes:manage",
    "reports:read",
    "reviews:moderate",
    "sellers:manage",
    "sellers:read",
    "services:manage",
    "services:read",
    "settings:manage",
    "settings:read",
    "staff:manage",
    "staff:read",
    "staff:self_read",
    "support:read",
    "support:reply",
]
NEW_STAFF_PASSWORD = random_password()  # per test run; never a fixed credential


def new_staff(role: StaffRoleName = "sales", n: int = 1, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "email": f"new.staff{n}@example.com",
        "phone": f"+25078855500{n}",
        "full_name": f"New Staff {n}",
        "password": NEW_STAFF_PASSWORD,
        "role": role,
    }
    body.update(overrides)
    return body


def audit_rows(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def staff_user(db: Session, user_id: str) -> User:
    db.expire_all()
    user = db.get(User, uuid.UUID(user_id))
    assert user is not None
    return user


def login(client: TestClient, identifier: str, password: str):
    return client.post(LOGIN, json={"identifier": identifier, "password": password})


ALL_STAFF_OPS = [
    ("get", "/me", None),
    ("get", "/me/permissions", None),
    ("get", "", None),
    ("post", "", new_staff()),
    ("get", f"/{uuid.uuid4()}", None),
    ("patch", f"/{uuid.uuid4()}", {"full_name": "X Y"}),
    ("patch", f"/{uuid.uuid4()}/role", {"role": "sales"}),
    ("patch", f"/{uuid.uuid4()}/status", {"is_active": False}),
]


# ---- authentication and coarse authorization -----------------------------------------------
@pytest.mark.parametrize(("method", "path", "body"), ALL_STAFF_OPS)
def test_unauthenticated_requests_get_401(client: TestClient, method, path, body):
    res = client.request(method, STAFF + path, json=body)
    assert res.status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), ALL_STAFF_OPS)
def test_customers_get_403_on_every_staff_api(
    client: TestClient, customer_auth: dict, db: Session, method, path, body
):
    res = client.request(method, STAFF + path, json=body, headers=customer_auth["headers"])
    assert res.status_code == 403
    denied = audit_rows(db, "auth.access_denied")
    assert denied and denied[-1].change_summary["user_roles"] == ["customer"]


@pytest.mark.parametrize(
    ("fixture", "role", "permissions"),
    [
        ("admin_auth", "administrator", ADMIN_PERMS),
        ("sales_auth", "sales", SALES_PERMS),
        ("operations_auth", "operations", OPERATIONS_PERMS),
        ("management_auth", "management", MANAGEMENT_PERMS),
        ("finance_auth", "finance", FINANCE_PERMS),
    ],
)
def test_every_staff_role_reads_own_identity_and_permissions(
    client: TestClient, request, fixture, role, permissions
):
    auth = request.getfixturevalue(fixture)
    me = client.get(f"{STAFF}/me", headers=auth["headers"])
    assert me.status_code == 200
    body = me.json()
    assert body["id"] == str(auth["user"].id)
    assert body["role"] == role and body["permissions"] == permissions
    assert body["is_active"] is True
    assert not SECRET_FIELDS & set(body)
    perms = client.get(f"{STAFF}/me/permissions", headers=auth["headers"])
    assert perms.json() == {"role": role, "permissions": permissions}


@pytest.mark.parametrize(
    "fixture", ["sales_auth", "operations_auth", "management_auth", "finance_auth"]
)
def test_restricted_staff_cannot_use_staff_administration_or_audit(
    client: TestClient, request, admin_auth: dict, fixture
):
    h = request.getfixturevalue(fixture)["headers"]
    target = admin_auth["user"].id
    assert client.get(STAFF, headers=h).status_code == 403
    assert client.get(f"{STAFF}/{target}", headers=h).status_code == 403
    # TC-16: no restricted role can create staff (administrators included) or assign roles.
    assert client.post(STAFF, json=new_staff("administrator"), headers=h).status_code == 403
    assert (
        client.patch(f"{STAFF}/{target}", json={"full_name": "Hijack"}, headers=h).status_code
        == 403
    )
    assert (
        client.patch(f"{STAFF}/{target}/role", json={"role": "sales"}, headers=h).status_code == 403
    )
    assert (
        client.patch(f"{STAFF}/{target}/status", json={"is_active": False}, headers=h).status_code
        == 403
    )
    # The audit trail is open to administrators and finance (audit:read) only.
    expected_audit = 200 if fixture == "finance_auth" else 403
    assert client.get("/api/v1/audit-logs", headers=h).status_code == expected_audit


def test_restricted_staff_cannot_escalate_their_own_role(
    client: TestClient, sales_auth: dict, db: Session
):
    me = sales_auth["user"].id
    res = client.patch(
        f"{STAFF}/{me}/role", json={"role": "administrator"}, headers=sales_auth["headers"]
    )
    assert res.status_code == 403
    db.expire_all()
    assert db.scalar(select(StaffRoleAssignment.role).where(StaffRoleAssignment.user_id == me)) == (
        "sales"
    )


# ---- provisioning ----------------------------------------------------------------------------
def test_admin_creates_staff_atomically_with_audit(
    client: TestClient, admin_auth: dict, db: Session
):
    res = client.post(STAFF, json=new_staff("operations"), headers=admin_auth["headers"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["role"] == "operations" and body["is_active"] is True
    assert not SECRET_FIELDS & set(body)

    user = staff_user(db, body["id"])
    assert user.is_staff is True
    assert [a.role for a in user.staff_roles] == ["operations"]
    assert user.password_hash != NEW_STAFF_PASSWORD
    assert user.password_hash is not None
    assert verify_password(NEW_STAFF_PASSWORD, user.password_hash)

    (record,) = audit_rows(db, "staff.create")
    assert record.actor_user_id == admin_auth["user"].id
    assert record.entity_id == body["id"]
    assert record.change_summary["role"] == "operations"
    assert NEW_STAFF_PASSWORD not in str(record.change_summary)

    token = login(client, "new.staff1@example.com", NEW_STAFF_PASSWORD).json()["session_token"]
    me = client.get(f"{STAFF}/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "operations"


def test_admin_can_create_another_administrator(client: TestClient, admin_auth: dict):
    res = client.post(STAFF, json=new_staff("administrator"), headers=admin_auth["headers"])
    assert res.status_code == 201
    token = login(client, "new.staff1@example.com", NEW_STAFF_PASSWORD).json()["session_token"]
    assert client.get(STAFF, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_duplicate_identifiers_conflict_and_customers_are_not_promoted(
    client: TestClient, admin_auth: dict, customer_auth: dict, db: Session
):
    h = admin_auth["headers"]
    assert client.post(STAFF, json=new_staff(), headers=h).status_code == 201
    dup_email = new_staff(n=2, email="NEW.STAFF1@example.com")
    assert client.post(STAFF, json=dup_email, headers=h).status_code == 409
    dup_phone = new_staff(n=3, phone="0788555001")  # same number, other format
    assert client.post(STAFF, json=dup_phone, headers=h).status_code == 409
    customer_email = new_staff(n=4, email="customer.a@example.com")
    assert client.post(STAFF, json=customer_email, headers=h).status_code == 409
    db.expire_all()
    customer = db.scalar(select(User).where(User.email == "customer.a@example.com"))
    assert customer is not None
    assert customer.is_staff is False and customer.staff_roles == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": None, "phone": None},
        {"password": "weak"},
        {"role": "customer"},
        {"role": "superadmin"},
        {"role": None},
        {"email": "not-an-email"},
        {"phone": "12345"},
        {"full_name": "X"},
        {"is_staff": False},
        {"permissions": ["audit:read"]},
        {"roles": ["administrator", "sales"]},
    ],
)
def test_create_staff_rejects_invalid_or_unexpected_input(
    client: TestClient, admin_auth: dict, db: Session, overrides
):
    res = client.post(STAFF, json=new_staff(**overrides), headers=admin_auth["headers"])
    assert res.status_code == 422
    assert NEW_STAFF_PASSWORD not in res.text
    assert db.scalar(select(func.count(User.id)).where(User.full_name == "New Staff 1")) == 0


# ---- reads -----------------------------------------------------------------------------------
def test_list_staff_paginates_filters_and_excludes_customers(
    client: TestClient,
    admin_auth: dict,
    sales_auth: dict,
    operations_auth: dict,
    management_auth: dict,
    customer_auth: dict,
):
    h = admin_auth["headers"]
    everyone = client.get(STAFF, headers=h).json()
    assert everyone["total"] == 4 and everyone["page"] == 1 and everyone["size"] == 20
    assert {s["role"] for s in everyone["items"]} == {
        "administrator",
        "sales",
        "operations",
        "management",
    }
    assert str(customer_auth["user"]["id"]) not in {s["id"] for s in everyone["items"]}
    for item in everyone["items"]:
        assert not SECRET_FIELDS & set(item)

    page = client.get(STAFF, params={"page": 2, "size": 1}, headers=h).json()
    assert page["total"] == 4 and len(page["items"]) == 1 and page["page"] == 2
    assert page["items"][0]["id"] == everyone["items"][1]["id"]

    sales = client.get(STAFF, params={"role": "sales"}, headers=h).json()
    assert [s["id"] for s in sales["items"]] == [str(sales_auth["user"].id)]
    client.patch(
        f"{STAFF}/{operations_auth['user'].id}/status", json={"is_active": False}, headers=h
    )
    inactive = client.get(STAFF, params={"is_active": "false"}, headers=h).json()
    assert [s["id"] for s in inactive["items"]] == [str(operations_auth["user"].id)]

    for bad in ({"size": 0}, {"size": 101}, {"page": 0}, {"role": "customer"}):
        assert client.get(STAFF, params=bad, headers=h).status_code == 422


def test_get_staff_by_id_and_client_errors(
    client: TestClient, admin_auth: dict, sales_auth: dict, customer_auth: dict
):
    h = admin_auth["headers"]
    res = client.get(f"{STAFF}/{sales_auth['user'].id}", headers=h)
    assert res.status_code == 200 and res.json()["role"] == "sales"
    assert client.get(f"{STAFF}/{customer_auth['user']['id']}", headers=h).status_code == 404
    assert client.get(f"{STAFF}/{uuid.uuid4()}", headers=h).status_code == 404
    # {staff_id:uuid} path converter (module 5): a non-UUID ID matches no staff route.
    assert client.get(f"{STAFF}/not-a-uuid", headers=h).status_code == 404


# ---- details ---------------------------------------------------------------------------------
def test_admin_updates_permitted_details_with_audit(
    client: TestClient, admin_auth: dict, sales_auth: dict, db: Session
):
    target = sales_auth["user"].id
    res = client.patch(
        f"{STAFF}/{target}",
        json={"full_name": "Renamed Sales", "phone": "0788777666"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 200
    assert res.json()["full_name"] == "Renamed Sales" and res.json()["phone"] == "+250788777666"
    (record,) = audit_rows(db, "staff.update")
    assert record.change_summary["updated_fields"] == ["full_name", "phone"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"role": "administrator"},
        {"is_active": False},
        {"is_staff": False},
        {"email": "changed@example.com"},
        {"password": "AnotherSecure123!"},
        {"permissions": ["staff:manage"]},
        {"full_name": "Ok Name", "role": "administrator"},
    ],
)
def test_update_rejects_protected_fields(
    client: TestClient, admin_auth: dict, sales_auth: dict, db: Session, body
):
    target = sales_auth["user"].id
    res = client.patch(f"{STAFF}/{target}", json=body, headers=admin_auth["headers"])
    assert res.status_code == 422
    user = staff_user(db, str(target))
    assert user.full_name == "Test sales" and [a.role for a in user.staff_roles] == ["sales"]


def test_update_phone_conflict_and_customer_target(
    client: TestClient, admin_auth: dict, sales_auth: dict, customer_auth: dict
):
    h = admin_auth["headers"]
    taken = {"phone": customer_auth["user"]["phone"]}
    assert (
        client.patch(f"{STAFF}/{sales_auth['user'].id}", json=taken, headers=h).status_code == 409
    )
    customer = customer_auth["user"]["id"]
    assert (
        client.patch(f"{STAFF}/{customer}", json={"full_name": "Nope"}, headers=h).status_code
        == 404
    )


# ---- roles -----------------------------------------------------------------------------------
def test_role_change_revokes_sessions_audits_and_applies_new_permissions(
    client: TestClient, admin_auth: dict, sales_auth: dict, db: Session
):
    target = sales_auth["user"].id
    res = client.patch(
        f"{STAFF}/{target}/role", json={"role": "operations"}, headers=admin_auth["headers"]
    )
    assert res.status_code == 200 and res.json()["role"] == "operations"
    # The old session no longer works anywhere.
    assert client.get(f"{STAFF}/me", headers=sales_auth["headers"]).status_code == 401
    db.expire_all()
    assert (
        db.scalar(
            select(func.count(UserSession.id)).where(
                UserSession.user_id == target, UserSession.revoked_at.is_(None)
            )
        )
        == 0
    )
    (record,) = audit_rows(db, "staff.role_change")
    assert record.actor_user_id == admin_auth["user"].id
    assert record.change_summary["old_role"] == "sales"
    assert record.change_summary["new_role"] == "operations"
    assert record.change_summary["sessions_revoked"] == 1

    token = login(client, "sales@example.com", sales_auth["password"]).json()["session_token"]
    me = client.get(f"{STAFF}/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "operations" and me["permissions"] == OPERATIONS_PERMS


def test_promotion_to_administrator_grants_admin_permissions_after_relogin(
    client: TestClient, admin_auth: dict, sales_auth: dict
):
    target = sales_auth["user"].id
    client.patch(
        f"{STAFF}/{target}/role", json={"role": "administrator"}, headers=admin_auth["headers"]
    )
    token = login(client, "sales@example.com", sales_auth["password"]).json()["session_token"]
    assert client.get(STAFF, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_setting_same_role_is_a_no_op(
    client: TestClient, admin_auth: dict, sales_auth: dict, db: Session
):
    target = sales_auth["user"].id
    res = client.patch(
        f"{STAFF}/{target}/role", json={"role": "sales"}, headers=admin_auth["headers"]
    )
    assert res.status_code == 200
    assert client.get(f"{STAFF}/me", headers=sales_auth["headers"]).status_code == 200
    assert audit_rows(db, "staff.role_change") == []


@pytest.mark.parametrize("body", [{"role": "customer"}, {"role": "root"}, {}, {"roles": ["sales"]}])
def test_role_change_rejects_invalid_roles(
    client: TestClient, admin_auth: dict, sales_auth: dict, body
):
    res = client.patch(
        f"{STAFF}/{sales_auth['user'].id}/role", json=body, headers=admin_auth["headers"]
    )
    assert res.status_code == 422


def test_role_change_on_customer_is_not_found_and_does_not_promote(
    client: TestClient, admin_auth: dict, customer_auth: dict, db: Session
):
    customer = customer_auth["user"]["id"]
    res = client.patch(
        f"{STAFF}/{customer}/role", json={"role": "administrator"}, headers=admin_auth["headers"]
    )
    assert res.status_code == 404
    user = staff_user(db, customer)
    assert user.is_staff is False and user.staff_roles == []


def test_last_active_administrator_cannot_be_demoted_or_disabled(
    client: TestClient, admin_auth: dict, db: Session
):
    h, me = admin_auth["headers"], admin_auth["user"].id
    demote = client.patch(f"{STAFF}/{me}/role", json={"role": "sales"}, headers=h)
    assert demote.status_code == 409
    disable = client.patch(f"{STAFF}/{me}/status", json={"is_active": False}, headers=h)
    assert disable.status_code == 409
    assert client.get(STAFF, headers=h).status_code == 200  # still an administrator, session kept
    assert audit_rows(db, "staff.role_change") == [] and audit_rows(db, "staff.status_change") == []


def test_inactive_administrators_do_not_count_toward_the_last_admin_rule(
    client: TestClient, admin_auth: dict, db: Session
):
    other = make_staff(db, "administrator", "admin2@example.com", "+250788000009", "Admin2Sec123!")
    h = admin_auth["headers"]
    assert (
        client.patch(
            f"{STAFF}/{other['user'].id}/status", json={"is_active": False}, headers=h
        ).status_code
        == 200
    )
    me = admin_auth["user"].id
    assert client.patch(f"{STAFF}/{me}/role", json={"role": "sales"}, headers=h).status_code == 409


def test_admin_can_step_down_when_another_active_admin_exists(
    client: TestClient, admin_auth: dict, db: Session
):
    other = make_staff(db, "administrator", "admin2@example.com", "+250788000009", "Admin2Sec123!")
    me = admin_auth["user"].id
    res = client.patch(
        f"{STAFF}/{me}/role", json={"role": "management"}, headers=admin_auth["headers"]
    )
    assert res.status_code == 200
    assert (
        client.get(STAFF, headers=admin_auth["headers"]).status_code == 401
    )  # own session revoked
    assert client.get(STAFF, headers=other["headers"]).status_code == 200


# ---- status ----------------------------------------------------------------------------------
def test_disabling_staff_revokes_access_and_blocks_login_until_enabled(
    client: TestClient, admin_auth: dict, sales_auth: dict, db: Session
):
    target, h = sales_auth["user"].id, admin_auth["headers"]
    res = client.patch(f"{STAFF}/{target}/status", json={"is_active": False}, headers=h)
    assert res.status_code == 200 and res.json()["is_active"] is False
    assert client.get(f"{STAFF}/me", headers=sales_auth["headers"]).status_code == 401
    assert login(client, "sales@example.com", sales_auth["password"]).status_code == 403
    (record,) = audit_rows(db, "staff.status_change")
    assert record.change_summary["old_is_active"] is True
    assert record.change_summary["new_is_active"] is False
    assert record.change_summary["sessions_revoked"] == 1

    enabled = client.patch(f"{STAFF}/{target}/status", json={"is_active": True}, headers=h)
    assert enabled.status_code == 200 and enabled.json()["is_active"] is True
    assert login(client, "sales@example.com", sales_auth["password"]).status_code == 200
    assert len(audit_rows(db, "staff.status_change")) == 2


def test_disabled_administrator_cannot_manage_staff(
    client: TestClient, admin_auth: dict, db: Session
):
    other = make_staff(db, "administrator", "admin2@example.com", "+250788000009", "Admin2Sec123!")
    client.patch(
        f"{STAFF}/{other['user'].id}/status",
        json={"is_active": False},
        headers=admin_auth["headers"],
    )
    assert client.post(STAFF, json=new_staff(), headers=other["headers"]).status_code == 401


@pytest.mark.parametrize("body", [{}, {"is_active": "maybe"}, {"is_active": None}])
def test_status_change_rejects_malformed_input(
    client: TestClient, admin_auth: dict, sales_auth: dict, body
):
    res = client.patch(
        f"{STAFF}/{sales_auth['user'].id}/status", json=body, headers=admin_auth["headers"]
    )
    assert res.status_code == 422


# ---- audit atomicity -------------------------------------------------------------------------
def _break_audit(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(boom))


def test_audit_failure_rolls_back_staff_changes(
    client: TestClient, admin_auth: dict, sales_auth: dict, db: Session, monkeypatch
):
    h, target = admin_auth["headers"], sales_auth["user"].id
    _break_audit(monkeypatch)
    with pytest.raises(RuntimeError):
        client.post(STAFF, json=new_staff(), headers=h)
    with pytest.raises(RuntimeError):
        client.patch(f"{STAFF}/{target}", json={"full_name": "Rolled Back"}, headers=h)
    with pytest.raises(RuntimeError):
        client.patch(f"{STAFF}/{target}/role", json={"role": "operations"}, headers=h)
    with pytest.raises(RuntimeError):
        client.patch(f"{STAFF}/{target}/status", json={"is_active": False}, headers=h)
    monkeypatch.undo()

    db.expire_all()
    assert db.scalar(select(func.count(User.id)).where(User.email == "new.staff1@example.com")) == 0
    user = db.get(User, target)
    assert user is not None
    assert user.full_name == "Test sales" and user.is_active is True
    assert [a.role for a in user.staff_roles] == ["sales"]
    assert client.get(f"{STAFF}/me", headers=sales_auth["headers"]).status_code == 200


# ---- registration and profile cannot grant privileges ----------------------------------------
def test_public_registration_cannot_request_privileged_role(client: TestClient, db: Session):
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "sneaky@example.com",
            "full_name": "Sneaky User",
            "password": "SneakySecure123!",
            "role": "administrator",
            "roles": ["administrator"],
            "is_staff": True,
            "permissions": ["staff:manage"],
        },
    )
    assert res.status_code == 201
    assert res.json()["user"]["roles"] == ["customer"]
    # Verify the email and sign in (2026-11-12): still nothing but a customer.
    verify_email(client, "sneaky@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "sneaky@example.com", "password": "SneakySecure123!"},
    )
    assert login.status_code == 200 and login.json()["user"]["roles"] == ["customer"]
    headers = {"Authorization": f"Bearer {login.json()['session_token']}"}
    assert client.get(f"{STAFF}/me", headers=headers).status_code == 403
    assert client.get(STAFF, headers=headers).status_code == 403


@pytest.mark.parametrize(
    "body", [{"is_staff": True}, {"roles": ["administrator"]}, {"role": "administrator"}]
)
def test_customer_profile_rejects_privilege_fields(
    client: TestClient, customer_auth: dict, db: Session, body
):
    res = client.patch("/api/v1/customers/me", json=body, headers=customer_auth["headers"])
    assert res.status_code == 422
    user = staff_user(db, customer_auth["user"]["id"])
    assert user.is_staff is False and user.staff_roles == []


def test_staff_profile_endpoint_cannot_change_role(
    client: TestClient, sales_auth: dict, db: Session
):
    res = client.patch(
        "/api/v1/customers/me", json={"role": "administrator"}, headers=sales_auth["headers"]
    )
    assert res.status_code == 422
    assert [a.role for a in staff_user(db, str(sales_auth["user"].id)).staff_roles] == ["sales"]


# ---- first-administrator bootstrap -----------------------------------------------------------
def _bootstrap_req(
    *, email: str = "first.admin@example.com", role: StaffRoleName = "administrator"
) -> StaffCreateRequest:
    return StaffCreateRequest(
        email=email,
        full_name="First Admin",
        password=random_password(),
        role=role,
    )


def test_bootstrap_creates_first_administrator_with_audit(db: Session):
    user = StaffService.bootstrap_administrator(db, _bootstrap_req())
    db.expire_all()
    assert user.is_staff and user.is_active
    stored_user = db.get(User, user.id)
    assert stored_user is not None
    assert [a.role for a in stored_user.staff_roles] == ["administrator"]
    (record,) = audit_rows(db, "staff.bootstrap_administrator")
    assert record.actor_user_id is None and record.entity_id == str(user.id)
    summary = record.change_summary
    assert summary["channel"] == "cli" and summary["mode"] == "first"
    assert summary["db_role"] and summary["os_user"] is None


def test_bootstrap_refused_while_an_active_administrator_exists(db: Session, admin_auth: dict):
    with pytest.raises(StaffBootstrapError, match="active administrator already exists"):
        StaffService.bootstrap_administrator(db, _bootstrap_req())
    assert audit_rows(db, "staff.bootstrap_administrator") == []


def test_bootstrap_recovers_access_when_all_administrators_are_disabled(
    db: Session, admin_auth: dict
):
    admin_auth["user"].is_active = False
    db.commit()
    user = StaffService.bootstrap_administrator(db, _bootstrap_req(), os_user="operator1")
    assert user.is_active
    (record,) = audit_rows(db, "staff.bootstrap_administrator")
    assert record.change_summary["mode"] == "recovery"
    assert record.change_summary["os_user"] == "operator1"


def test_concurrent_bootstraps_create_exactly_one_administrator(pg_engine):
    """Two operators racing: the staff-change lock lets only one administrator be created."""
    barrier = threading.Barrier(2)

    def attempt(n: int) -> str:
        with sessionmaker(bind=pg_engine, expire_on_commit=False)() as session:
            barrier.wait()
            try:
                StaffService.bootstrap_administrator(
                    session, _bootstrap_req(email=f"racer{n}@example.com")
                )
                return "created"
            except StaffBootstrapError:
                return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, [1, 2]))
    assert outcomes == ["created", "refused"]
    with sessionmaker(bind=pg_engine)() as session:
        admins = select(func.count(StaffRoleAssignment.id)).where(
            StaffRoleAssignment.role == "administrator"
        )
        assert session.scalar(admins) == 1


def test_bootstrap_refuses_duplicates_and_non_admin_roles(db: Session, customer_auth: dict):
    with pytest.raises(StaffBootstrapError, match="email already exists"):
        StaffService.bootstrap_administrator(db, _bootstrap_req(email="customer.a@example.com"))
    with pytest.raises(StaffBootstrapError, match="administrator role"):
        StaffService.bootstrap_administrator(db, _bootstrap_req(role="sales"))
    assert db.scalar(select(func.count(User.id)).where(User.is_staff.is_(True))) == 0


# ---- validation errors never echo submitted secrets ------------------------------------------
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/v1/auth/register",
            {"email": "e@example.com", "full_name": "E F", "password": "weakpass"},
        ),
        ("/api/v1/auth/register", {"full_name": "E F", "password": "Secret-Echo-Pass1"}),
        ("/api/v1/auth/login", {"identifier": "", "password": "Secret-Echo-Pass1"}),
    ],
)
def test_validation_errors_do_not_echo_passwords(client: TestClient, path, body):
    res = client.post(path, json=body)
    assert res.status_code == 422
    assert body["password"] not in res.text
    error = res.json()["error"]
    assert error["code"] == "validation_error"
    assert all(set(err) <= {"type", "loc", "msg"} for err in error["details"])


# ---- finance changes nothing (final matrix, 2026-10-26) ------------------------------------------
def _required_permissions(dependant) -> set[str]:
    found: set[str] = set()
    for sub in dependant.dependencies:
        permission = getattr(sub.call, "required_permission", None)
        if permission is not None:
            found.add(permission)
        found |= _required_permissions(sub)
    return found


def _api_routes(routes):
    """(path, methods, dependant) of every API route, through included routers (FastAPI 0.148
    resolves those lazily, so app.routes holds them as one entry each)."""
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield route.path, route.methods, route.dependant
        elif hasattr(route, "effective_route_contexts"):
            for context in route.effective_route_contexts():
                yield context.path, set(context.methods or ()), context.dependant


def _protected_mutations() -> list[tuple[str, str, set[str]]]:
    from app.main import app

    routes = []
    for path, methods, dependant in _api_routes(app.routes):
        permissions = _required_permissions(dependant)
        for method in sorted(methods & {"POST", "PUT", "PATCH", "DELETE"}):
            if permissions:
                routes.append((method, path, permissions))
    return routes


PROTECTED_MUTATIONS = _protected_mutations()


def _concrete(path: str) -> str:
    parts = []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1].split(":")[0]  # "{staff_id:uuid}" -> "staff_id"
            part = str(uuid.uuid4()) if name.endswith("_id") else "FIN-TEST-1"
        parts.append(part)
    return "/".join(parts)


def test_every_permission_protected_mutation_is_enumerated():
    paths = {(method, path) for method, path, _ in PROTECTED_MUTATIONS}
    assert ("POST", "/api/v1/staff/products") in paths
    assert ("PATCH", "/api/v1/staff/orders/{order_id}/status") in paths
    assert ("PATCH", "/api/v1/staff/settings") in paths
    assert len(paths) >= 25


@pytest.mark.parametrize(
    ("method", "path", "permissions"),
    PROTECTED_MUTATIONS,
    ids=[f"{m} {p}" for m, p, _ in PROTECTED_MUTATIONS],
)
def test_finance_gets_403_on_every_permission_protected_mutation(
    client: TestClient, finance_auth: dict, method, path, permissions
):
    res = client.request(method, _concrete(path), json={}, headers=finance_auth["headers"])
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"
