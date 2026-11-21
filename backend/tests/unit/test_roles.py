"""The approved permission matrix. SC-05 (2026-11-21): the Marketplace Administrator is the only
staff role and holds every permission; customers, and sellers (who are customers owning a
store, ADR-014), hold none. The permissions themselves stay fine-grained and every staff route
still requires one. Changes need approval."""

import typing

import pytest

from app.core.roles import (
    ROLE_PERMISSIONS,
    STAFF_ROLE_NAMES,
    Permission,
    Role,
    StaffRoleName,
    effective_permissions,
    has_permission,
    staff_role,
)
from app.models.identity import StaffRoleAssignment, User

ALL_PERMISSIONS = [
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
REMOVED_ROLES = ("sales", "operations", "management", "finance")


def _user(is_staff: bool, role: str | None) -> User:
    user = User(email="x@example.com", is_staff=is_staff, is_active=True)
    if role:
        user.staff_roles.append(StaffRoleAssignment(role=role))
    return user


def test_matrix_matches_approved_policy():
    assert {role: sorted(perms) for role, perms in ROLE_PERMISSIONS.items()} == {
        "customer": [],
        "administrator": ALL_PERMISSIONS,
    }


def test_the_marketplace_administrator_is_the_only_staff_role():
    assert STAFF_ROLE_NAMES == ("administrator",)
    assert typing.get_args(StaffRoleName) == ("administrator",)
    assert {r.value for r in Role} == {"customer", "administrator"}


def test_the_administrator_holds_every_declared_permission():
    admin = _user(True, "administrator")
    assert staff_role(admin) == "administrator"
    assert effective_permissions(admin) == sorted(p.value for p in Permission) == ALL_PERMISSIONS


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
