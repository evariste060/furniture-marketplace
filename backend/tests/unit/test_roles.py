"""The approved permission matrix (ADR-006; stock and order access and catalog:manage
2026-10-23; delivery and settings, RE-026 B6 and plan §3; the finance role 2026-10-25; the final
staff matrix with catalog:read and content:manage 2026-10-26; reviews:moderate for sales and
administrator, SC-01 2026-10-27). Changes need approval."""

from app.core.roles import ROLE_PERMISSIONS, effective_permissions, has_permission, staff_role
from app.models.identity import StaffRoleAssignment, User


def _user(is_staff: bool, role: str | None) -> User:
    user = User(email="x@example.com", is_staff=is_staff, is_active=True)
    if role:
        user.staff_roles.append(StaffRoleAssignment(role=role))
    return user


def test_matrix_matches_approved_policy():
    assert {role: sorted(perms) for role, perms in ROLE_PERMISSIONS.items()} == {
        "customer": [],
        "sales": [
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
        ],
        "operations": [
            "catalog:read",
            "delivery:read",
            "inventory:adjust",
            "inventory:read",
            "orders:fulfil",
            "orders:read",
            "staff:self_read",
        ],
        "management": [
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
        ],
        "finance": [
            "audit:read",
            "orders:read",
            "payments:read",
            "reports:read",
            "staff:self_read",
        ],
        "administrator": [
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
        ],
    }


def test_customer_has_no_permissions():
    customer = _user(False, None)
    assert effective_permissions(customer) == [] and staff_role(customer) is None


def test_role_assignment_ignored_without_staff_flag():
    flagged_off = _user(False, "administrator")
    assert staff_role(flagged_off) is None
    assert not has_permission(flagged_off, "staff:manage")


def test_only_administrators_manage_staff_and_only_they_and_finance_read_audit():
    for role in ("sales", "operations", "management", "finance"):
        user = _user(True, role)
        assert has_permission(user, "staff:self_read")
        assert not has_permission(user, "staff:manage")
        assert not has_permission(user, "staff:read")
        assert has_permission(user, "audit:read") == (role == "finance")
    admin = _user(True, "administrator")
    assert all(has_permission(admin, p) for p in ROLE_PERMISSIONS["administrator"])


def test_stock_and_order_access_follows_the_approved_split():
    expected = {
        "sales": {"inventory:read": True, "inventory:adjust": True, "orders:fulfil": False},
        "operations": {"inventory:read": True, "inventory:adjust": True, "orders:fulfil": True},
        "management": {"inventory:read": True, "inventory:adjust": False, "orders:fulfil": False},
        "finance": {"inventory:read": False, "inventory:adjust": False, "orders:fulfil": False},
    }
    for role, permissions in expected.items():
        user = _user(True, role)
        assert {p: has_permission(user, p) for p in permissions} == permissions, role
    customer = _user(False, None)
    assert not any(has_permission(customer, p) for p in expected["sales"])


def test_only_administrators_and_sales_manage_the_catalogue_and_finance_cannot_read_it():
    manage = {"administrator": True, "sales": True, "operations": False, "management": False}
    assert {role: has_permission(_user(True, role), "catalog:manage") for role in manage} == (
        manage
    )
    read = {**{role: True for role in manage}, "finance": False}
    assert {role: has_permission(_user(True, role), "catalog:read") for role in read} == read
    assert not has_permission(_user(False, None), "catalog:manage")


def test_only_administrators_change_delivery_and_settings():
    # RE-026 B6 and plan section 3; operations views delivery zones since 2026-10-26.
    for role, delivery_view, settings_view in (
        ("administrator", True, True),
        ("management", True, True),
        ("operations", True, False),
        ("sales", False, False),
        ("finance", False, False),
    ):
        user = _user(True, role)
        assert has_permission(user, "delivery:read") is delivery_view, role
        assert has_permission(user, "settings:read") is settings_view, role
        can_change = role == "administrator"
        for permission in ("delivery:manage", "settings:manage"):
            assert has_permission(user, permission) is can_change, (role, permission)
    customer = _user(False, None)
    assert not any(
        has_permission(customer, p)
        for p in ("delivery:read", "delivery:manage", "settings:read", "settings:manage")
    )


def test_content_and_reports_follow_the_final_matrix():
    for role, content, reports in (
        ("administrator", True, True),
        ("management", True, True),
        ("finance", False, True),
        ("sales", False, False),
        ("operations", False, False),
    ):
        user = _user(True, role)
        assert has_permission(user, "content:manage") is content, role
        assert has_permission(user, "reports:read") is reports, role


def test_finance_reads_orders_payments_reports_and_audit_but_changes_nothing():
    finance = _user(True, "finance")
    assert staff_role(finance) == "finance"
    assert effective_permissions(finance) == [
        "audit:read",
        "orders:read",
        "payments:read",
        "reports:read",
        "staff:self_read",
    ]
    # Every permission finance holds is a read.
    assert all(p.endswith((":read", ":self_read")) for p in effective_permissions(finance))
