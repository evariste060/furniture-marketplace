import { Suspense } from "react";
import { AuditView } from "@/features/admin/audit";
import { AdminPage } from "@/features/admin/guard";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("audit");

export default function AuditPage() {
  return (
    <AdminPage area="audit">
      <Suspense>
        <AuditView />
      </Suspense>
    </AdminPage>
  );
}
