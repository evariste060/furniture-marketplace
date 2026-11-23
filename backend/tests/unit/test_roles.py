"""The approved permission matrix. SC-05 (2026-11-21): the Marketplace Administrator is the only
staff role; customers, and sellers (who are customers owning a store, ADR-014), hold no
permission. SC-06 (2026-11-22): store operations are the sellers', so the administrator does not
hold the order, payment, inventory and catalogue-editing permissions, which no role holds in V1.
The permissions stay fine-grained and every staff route still requires one. Changes need
approval."""

import typing

import pytest

from app.core.roles import (
    ROLE_PERMISSIONS,
    STAFF_ROLE_NAMES,
    UNASSIGNED_PERMISSIONS,
    Permission,
    Role,
    StaffRoleName,
    effective_permissions,
    has_permission,
    staff_role,
)
from app.models.identity import StaffRoleAssignment, User

# SC-06: declared, held by no role in V1.
UNASSIGNED = [
    "catalog:edit",
    "inventory:adjust",
    "inventory:read",
    "orders:fulfil",
    "orders:read",
    "payments:manage",
    "payments:read",
]
ADMINISTRATOR_PERMISSIONS = [
    "audit:read",
    "catalog:manage",
    "catalog:read",
    "content:manage",
    "delivery:manage",
    "delivery:read",
    "invoices:recover",
    "notifications:manage",
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
REMOVED_ROLES = ("sales", "operations", "management", "finance")


def _user(is_staff: bool, role: str | None) -> User:
    user = User(email="x@example.com", is_staff=is_staff, is_active=True)
    if role:
        user.staff_roles.append(StaffRoleAssignment(role=role))
    return user


def test_matrix_matches_approved_policy():
    assert {role: sorted(perms) for role, perms in ROLE_PERMISSIONS.items()} == {
        "customer": [],
        "administrator": ADMINISTRATOR_PERMISSIONS,
    }
    assert sorted(UNASSIGNED_PERMISSIONS) == UNASSIGNED


def test_the_marketplace_administrator_is_the_only_staff_role():
    assert STAFF_ROLE_NAMES == ("administrator",)
    assert typing.get_args(StaffRoleName) == ("administrator",)
    assert {r.value for r in Role} == {"customer", "administrator"}


def test_the_administrator_holds_every_permission_but_the_store_operations():
    admin = _user(True, "administrator")
    assert staff_role(admin) == "administrator"
    assert effective_permissions(admin) == ADMINISTRATOR_PERMISSIONS
    assert sorted(ADMINISTRATOR_PERMISSIONS + UNASSIGNED) == sorted(p.value for p in Permission)


@pytest.mark.parametrize("permission", UNASSIGNED)
def test_no_role_holds_a_store_operation_permission(permission: str):
    for role in (_user(True, "administrator"), _user(False, None)):
        assert not has_permission(role, permission)


def test_customer_has_no_permissions():
    customer = _user(False, None)
    assert effective_permissions(customer) == [] and staff_role(customer) is None


def test_role_assignment_ignored_without_staff_flag():
    flagged_off = _user(False, "administrator")
    assert staff_role(flagged_off) is None
    assert not has_permission(flagged_off, "staff:manage")


@pytest.mark.parametrize("role", REMOVED_ROLES)
def test_a_removed_role_grants_nothing(role: str):
    # The database refuses these roles (migration a9d3f5b7c1e2); even an in-memory assignment
    # is no staff role and holds no permission.
    user = _user(True, role)
    assert staff_role(user) is None
    assert effective_permissions(user) == []
    assert role not in ROLE_PERMISSIONS
