"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { Permission } from "./nav";

export type ClientStaffAccess = {
  id: string;
  fullName: string;
  role: string;
  permissions: string[];
};

type AccessValue = ClientStaffAccess & {
  can: (permission: Permission) => boolean;
};

const AccessContext = createContext<AccessValue | null>(null);

/** The staff member's identity and permissions, read on the server by the admin layout. They only
 * decide what the admin shows; the backend checks every request again. */
export function StaffAccessProvider({ access, children }: { access: ClientStaffAccess; children: ReactNode }) {
  const value = useMemo(() => {
    const held = new Set(access.permissions);
    return { ...access, can: (permission: Permission) => held.has(permission) };
  }, [access]);
  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>;
}

export function useStaffAccess(): AccessValue {
  const value = useContext(AccessContext);
  if (!value) throw new Error("useStaffAccess is used outside the admin shell");
  return value;
}
