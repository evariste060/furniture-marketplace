"""Code-defined role -> permission mapping over the upstream identity schema.

Staff roles come from staff_role_assignments (administrator, sales, operations, management,
finance) and only count when users.is_staff is true. Each staff user holds exactly one role
(unique per user in the database). A user with no effective staff role is a customer.

Approved minimal matrix (ADR-006, project owner, 2026-10-22): permissions exist only for
features that are built. Built features add narrowly scoped permissions here; administrator
continues to receive every declared permission. Stock and order permissions for sales and
operations were approved by the project owner on 2026-10-23 (docs/IMPLEMENTATION_PLAN.md, §3),
as was catalog:manage for administrator and sales (added with module 5, categories and brands).
Delivery and settings permissions (module 12) and promotion permissions (module 13) follow
RE-026 B6: only administrators change delivery zones, fees, the free-delivery threshold and
promotions; management may view them. invoices:recover (module 16) was added on the project
owner's instruction to prefer a dedicated permission for invoice recovery; following the
convention above it is held by administrator only, and no other role receives it without a
recorded approval. The finance role (approved by the project owner on 2026-10-25, plan §3)
reads orders, payments, reports and the audit trail.

Final staff matrix (approved by the project owner on 2026-10-26, checkpoint 1b; plan §3):
catalog:read for every role that sees the staff catalogue without changing it, inventory:adjust
for operations, inventory, order and report access for management, promotions:read for sales,
delivery:read for operations, and content:manage (storefront banners) for administrator and
management. Finance changes nothing.

reviews:moderate (module 20, scope change SC-01 approved by the project owner on 2026-10-27):
administrator and sales.

quotes:manage (module 19, approved by the project owner on 2026-10-29): business quote requests
from the Contact page, for administrator and sales. content:manage also covers the policy pages
(module 19).

notifications:manage (module 17: the notification log and retry) is administrator only, as
listed in the final matrix (docs/IMPLEMENTATION_PLAN.md, §3); finance does not receive it.
"""

from enum import StrEnum
from typing import Literal

from app.models.identity import User


class Role(StrEnum):
    CUSTOMER = "customer"
    ADMINISTRATOR = "administrator"
    SALES = "sales"
    OPERATIONS = "operations"
    MANAGEMENT = "management"
    FINANCE = "finance"


class Permission(StrEnum):
    STAFF_SELF_READ = "staff:self_read"  # read own staff identity and permissions
    STAFF_READ = "staff:read"  # list and view staff accounts
    STAFF_MANAGE = "staff:manage"  # create staff, edit details, change role or status
    AUDIT_READ = "audit:read"  # read the security audit trail
    ORDER_FULFIL = "orders:fulfil"  # update order status and assign fulfilment responsibility
    ORDER_READ = "orders:read"  # staff order list and detail (module 14; plan §3)
    INVENTORY_READ = "inventory:read"  # view stock figures for a SKU
    INVENTORY_ADJUST = "inventory:adjust"  # receipts, adjustments and inspected returns
    # categories, brands (module 5), products, variants (6), images (7), imports (8)
    CATALOG_MANAGE = "catalog:manage"
    CATALOG_READ = "catalog:read"  # staff product list and detail, drafts included (2026-10-26)
    # Delivery zones, fees and settings (module 12; RE-026 B6)
    DELIVERY_READ = "delivery:read"  # view zones, fees and fee history
    DELIVERY_MANAGE = "delivery:manage"  # create and edit zones, change fees
    SETTINGS_READ = "settings:read"  # view settings such as the free-delivery threshold
    SETTINGS_MANAGE = "settings:manage"  # change settings
    # Promotion codes (module 13; RE-026 B6)
    PROMOTIONS_READ = "promotions:read"  # list and view promotions and their usage
    PROMOTIONS_MANAGE = "promotions:manage"  # create, edit, activate and disable promotions
    # Payments (module 15; plan §3)
    PAYMENTS_READ = "payments:read"  # payment attempts, events and reconciliation list
    PAYMENTS_MANAGE = "payments:manage"  # any change to payment data (e.g. COD cash collected)
    # Invoices (module 16): issue a paid order's missing invoice (recovery). Administrator only.
    INVOICES_RECOVER = "invoices:recover"
    # Reports and exports (module 18). Declared with the finance role (approved 2026-10-25) so
    # the role is complete when the reports endpoints land; nothing requires it yet.
    REPORTS_READ = "reports:read"
    # Storefront content: homepage banners (approved 2026-10-26) and policy pages (module 19).
    CONTENT_MANAGE = "content:manage"
    # Business quote requests from the Contact page (module 19, approved 2026-10-29).
    QUOTES_MANAGE = "quotes:manage"
    # Product reviews (module 20, SC-01 approved 2026-10-27): list, approve and reject reviews.
    REVIEWS_MODERATE = "reviews:moderate"
    # Customer support messages (approved 2026-11-11): read the conversations; reply to and
    # close them.
    SUPPORT_READ = "support:read"
    SUPPORT_REPLY = "support:reply"
    # Notifications (module 17; plan §3): the notification log and retries. Administrator only.
    NOTIFICATIONS_MANAGE = "notifications:manage"
    # Technical services (ADR-013, 2026-11-17): the service pages and their requests.
    SERVICES_READ = "services:read"  # staff service list and service requests
    SERVICES_MANAGE = "services:manage"  # edit services, follow up requests


StaffRoleName = Literal["administrator", "sales", "operations", "management", "finance"]
STAFF_ROLE_NAMES: tuple[StaffRoleName, ...] = (
    "administrator",
    "sales",
    "operations",
    "management",
    "finance",
)
STAFF_ROLES = frozenset(STAFF_ROLE_NAMES)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.CUSTOMER.value: frozenset(),
    Role.SALES.value: frozenset(
        {
            Permission.STAFF_SELF_READ.value,
            Permission.INVENTORY_READ.value,
            Permission.INVENTORY_ADJUST.value,
            Permission.CATALOG_MANAGE.value,
            Permission.CATALOG_READ.value,
            Permission.ORDER_READ.value,
            Permission.PROMOTIONS_READ.value,
            Permission.REVIEWS_MODERATE.value,
            Permission.QUOTES_MANAGE.value,
            Permission.SUPPORT_READ.value,
            Permission.SUPPORT_REPLY.value,
            Permission.SERVICES_READ.value,
            Permission.SERVICES_MANAGE.value,
        }
    ),
    Role.OPERATIONS.value: frozenset(
        {
            Permission.STAFF_SELF_READ.value,
            Permission.CATALOG_READ.value,
            Permission.INVENTORY_READ.value,
            Permission.INVENTORY_ADJUST.value,
            Permission.ORDER_FULFIL.value,
            Permission.ORDER_READ.value,
            Permission.DELIVERY_READ.value,
        }
    ),
    Role.MANAGEMENT.value: frozenset(
        {
            Permission.STAFF_SELF_READ.value,
            Permission.CATALOG_READ.value,
            Permission.INVENTORY_READ.value,
            Permission.ORDER_READ.value,
            Permission.DELIVERY_READ.value,
            Permission.PROMOTIONS_READ.value,
            Permission.PAYMENTS_READ.value,
            Permission.CONTENT_MANAGE.value,
            Permission.SETTINGS_READ.value,
            Permission.REPORTS_READ.value,
            Permission.SUPPORT_READ.value,
            Permission.SERVICES_READ.value,
        }
    ),
    Role.FINANCE.value: frozenset(
        {
            Permission.STAFF_SELF_READ.value,
            Permission.ORDER_READ.value,
            Permission.PAYMENTS_READ.value,
            Permission.REPORTS_READ.value,
            Permission.AUDIT_READ.value,
        }
    ),
    Role.ADMINISTRATOR.value: frozenset(p.value for p in Permission),
}


def staff_roles(user: User) -> list[StaffRoleName]:
    """Sorted effective staff roles; empty unless the account is flagged as staff."""
    if not user.is_staff:
        return []
    return sorted(
        {
            role_name
            for assignment in user.staff_roles
            for role_name in STAFF_ROLE_NAMES
            if assignment.role == role_name
        }
    )


def staff_role(user: User) -> StaffRoleName | None:
    """The single effective staff role, or None for customers."""
    roles = staff_roles(user)
    return roles[0] if roles else None


def effective_roles(user: User) -> frozenset[str]:
    roles = staff_roles(user)
    return frozenset(roles) if roles else frozenset({Role.CUSTOMER.value})


def effective_permissions(user: User) -> list[str]:
    """Sorted permissions granted by the user's roles, from this trusted backend mapping only."""
    granted: set[str] = set()
    for role in effective_roles(user):
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return sorted(granted)


def has_permission(user: User, permission: str) -> bool:
    return permission in effective_permissions(user)
