"""Code-defined role -> permission mapping over the upstream identity schema.

SC-05 (approved by the project owner on 2026-11-21): FurniHub is a multi-vendor marketplace, so
the only staff role is the Marketplace Administrator (stored as 'administrator'). The sales,
operations, management and finance roles of the original single-business shop are removed; the
fine-grained permissions below stay, every staff route still requires one, and the administrator
held them all until SC-06 (below). Sellers are store owners, not staff, and hold none (ADR-014).

The staff role comes from staff_role_assignments and only counts when users.is_staff is true.
Each staff user holds exactly one role (unique per user in the database). A user with no
effective staff role is a customer.

History of the matrix before SC-05, kept for the record:

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

sellers:read and sellers:manage (ADR-014 phase 1, approved by the project owner on 2026-11-21):
seller applications, stores and their owners' contact details. Administrator only in V1; no
other staff role receives them. Sellers are store owners, not staff: they hold no permission
here, and their access is scoped to their own approved store (app.core.dependencies
require_approved_seller).

SC-06 (approved by the project owner on 2026-11-22, ADR-014 phase 7): the administrator runs the
marketplace, not the stores. Store operations belong to sellers, so the administrator no longer
holds orders:read, orders:fulfil (whole-order cancellation included), payments:read,
payments:manage, inventory:read, inventory:adjust or the new catalog:edit (a product's content,
variants and images, bulk images, bulk activation and the catalogue import). These stay declared
and their routes stay in place, held by no role in V1: granting one again is a recorded scope
change. catalog:manage now covers the shared catalogue (categories, brands) and product
moderation (status and the featured flag) only.
"""

from enum import StrEnum
from typing import Literal

from app.models.identity import User


class Role(StrEnum):
    CUSTOMER = "customer"
    ADMINISTRATOR = "administrator"


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
    # A product's content, variants and images, bulk images, bulk activation and the catalogue
    # import (SC-06, 2026-11-22). Held by no role in V1: sellers edit their own products.
    CATALOG_EDIT = "catalog:edit"
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
    # Reports and exports (module 18).
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
    # Marketplace sellers (ADR-014 phase 1, 2026-11-21).
    SELLERS_READ = "sellers:read"  # seller applications, stores and owner contact details
    SELLERS_MANAGE = "sellers:manage"  # approve, reject, suspend, reinstate; commission override


# The Marketplace Administrator (SC-05). Adding a role later is a recorded scope change: extend
# this literal, ROLE_PERMISSIONS, the staff_role_assignments check constraint (with a
# migration) and the admin frontend's roles.
StaffRoleName = Literal["administrator"]
STAFF_ROLE_NAMES: tuple[StaffRoleName, ...] = ("administrator",)
STAFF_ROLES = frozenset(STAFF_ROLE_NAMES)

# Declared permissions that no role holds in V1 (SC-06): store operations are the sellers'.
UNASSIGNED_PERMISSIONS: frozenset[str] = frozenset(
    p.value
    for p in (
        Permission.ORDER_READ,
        Permission.ORDER_FULFIL,
        Permission.PAYMENTS_READ,
        Permission.PAYMENTS_MANAGE,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_ADJUST,
        Permission.CATALOG_EDIT,
    )
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.CUSTOMER.value: frozenset(),
    Role.ADMINISTRATOR.value: frozenset(p.value for p in Permission) - UNASSIGNED_PERMISSIONS,
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
