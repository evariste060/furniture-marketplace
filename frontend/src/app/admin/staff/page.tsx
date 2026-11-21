import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { StaffView } from "@/features/admin/staff";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("staff");

export default function StaffPage() {
  return (
    <AdminPage area="staff">
      <Suspense>
        <StaffView />
      </Suspense>
    </AdminPage>
  );
}
