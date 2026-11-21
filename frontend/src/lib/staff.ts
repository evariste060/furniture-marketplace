import "server-only";
import { cache } from "react";
import { hasSession, sessionApi } from "@/lib/api/server";

/** The signed-in staff member and their permissions, checked on the server for every admin page.
 * The backend enforces every permission again; this only decides what the admin shows. */
export type StaffAccess = {
  id: string;
  fullName: string;
  role: string;
  permissions: string[];
};

export type AdminVisitor = { kind: "signed-out" } | { kind: "not-staff" } | { kind: "staff"; access: StaffAccess };

/** Read once per request (the layout and the page both ask). */
export const getAdminVisitor = cache(async (): Promise<AdminVisitor> => {
  if (!(await hasSession())) return { kind: "signed-out" };
  const api = await sessionApi();
  const [me, perms] = await Promise.all([api.GET("/api/v1/staff/me"), api.GET("/api/v1/staff/me/permissions")]);
  if (me.response.status === 401 || perms.response.status === 401) return { kind: "signed-out" };
  if (!me.data || !perms.data) return { kind: "not-staff" }; // 403: a customer session
  return {
    kind: "staff",
    access: { id: me.data.id, fullName: me.data.full_name ?? "", role: me.data.role, permissions: perms.data.permissions },
  };
});

export async function getStaffAccess(): Promise<StaffAccess | null> {
  const visitor = await getAdminVisitor();
  return visitor.kind === "staff" ? visitor.access : null;
}

export function can(access: StaffAccess | null, permission: string): boolean {
  return access?.permissions.includes(permission) ?? false;
}
