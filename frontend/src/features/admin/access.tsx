"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { CatalogScopeProvider, staffScope } from "./catalog-scope";
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
  // The product, editor and stock screens are shared with the seller dashboard (ADR-014 phase 4).
  const scope = useMemo(() => staffScope(new Set(access.permissions)), [access]);
  return (
    <AccessContext.Provider value={value}>
      <CatalogScopeProvider scope={scope}>{children}</CatalogScopeProvider>
    </AccessContext.Provider>
  );
}

export function useStaffAccess(): AccessValue {
  const value = useContext(AccessContext);
  if (!value) throw new Error("useStaffAccess is used outside the admin shell");
  return value;
}
