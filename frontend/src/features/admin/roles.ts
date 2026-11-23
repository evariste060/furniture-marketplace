import type { Permission } from "./nav";

/** Staff roles (backend app/core/roles.py). SC-05 (2026-11-21): the Marketplace Administrator,
 * stored as "administrator", is the only staff role. SC-06 (2026-11-22): it holds every permission
 * but the store operations, which no role holds in V1. The backend checks the permission on every
 * call; this only explains who can open a page. */
export const STAFF_ROLES = ["administrator"] as const;
export type StaffRole = (typeof STAFF_ROLES)[number];

/** The permissions no role holds in V1 (SC-06; backend UNASSIGNED_PERMISSIONS). */
export const UNASSIGNED: readonly Permission[] = [
  "orders:read",
  "orders:fulfil",
  "payments:read",
  "payments:manage",
  "inventory:read",
  "inventory:adjust",
  "catalog:edit",
];

/** Whether a role holds a permission: the administrator holds every one but the store operations. */
export function roleHas(role: StaffRole, permission: Permission): boolean {
  return role === "administrator" && !UNASSIGNED.includes(permission);
}

/** The roles that can open a page needing any of these permissions, in table order. */
export function rolesFor(anyOf: readonly Permission[]): StaffRole[] {
  return STAFF_ROLES.filter((role) => anyOf.some((p) => roleHas(role, p)));
}
