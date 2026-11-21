import matrix from "./role-permissions.json";
import type { Permission } from "./nav";

export const STAFF_ROLES = ["administrator", "sales", "operations", "finance", "management"] as const;
export type StaffRole = (typeof STAFF_ROLES)[number];

/** Whether a role holds a permission (administrator holds every one). */
export function roleHas(role: StaffRole, permission: Permission): boolean {
  if (role === "administrator") return true;
  return (matrix[role] as string[]).includes(permission);
}

/** The roles that can open a page needing any of these permissions, in table order. */
export function rolesFor(anyOf: readonly Permission[]): StaffRole[] {
  return STAFF_ROLES.filter((role) => anyOf.some((p) => roleHas(role, p)));
}
