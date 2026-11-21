import { Suspense, type ReactNode } from "react";
import { getStaffAccess } from "@/lib/staff";
import { AccessDenied } from "./access-denied";
import { canOpen, NAV, type NavKey } from "./nav";

/** Each admin page's server-side check: the page's nav permissions, else AccessDenied. The
 * layout has already sent visitors without a staff session away. The page streams in its own
 * Suspense boundary, so navigating between admin pages stays instant. */
export function AdminPage({ area, children }: { area: NavKey; children: ReactNode }) {
  return (
    <Suspense fallback={<div aria-busy="true" className="min-h-[60vh]" />}>
      <Check area={area}>{children}</Check>
    </Suspense>
  );
}

async function Check({ area, children }: { area: NavKey; children: ReactNode }) {
  const access = await getStaffAccess();
  const item = NAV.flatMap((g) => g.items).find((i) => i.key === area);
  if (!access || !item || !canOpen(access.permissions, item.anyOf)) return <AccessDenied area={area} />;
  return <>{children}</>;
}
