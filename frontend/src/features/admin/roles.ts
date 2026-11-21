import type { Permission } from "./nav";

/** Staff roles (backend app/core/roles.py). SC-05 (2026-11-21): the Marketplace Administrator,
 * stored as "administrator", is the only staff role and holds every permission. The backend
 * checks the permission on every call; this only explains who can open a page. */
export const STAFF_ROLES = ["administrator"] as const;
export type StaffRole = (typeof STAFF_ROLES)[number];

/** Whether a role holds a permission: the administrator holds every one. */
export function roleHas(role: StaffRole, permission: Permission): boolean {
  void permission;
  return role === "administrator";
}

/** The roles that can open a page needing any of these permissions, in table order. */
export function rolesFor(anyOf: readonly Permission[]): StaffRole[] {
  return STAFF_ROLES.filter((role) => anyOf.some((p) => roleHas(role, p)));
}
