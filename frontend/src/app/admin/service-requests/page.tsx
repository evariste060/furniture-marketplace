import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { ServiceRequestsView } from "@/features/admin/service-requests";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("serviceRequests");

export default function ServiceRequestsPage() {
  return (
    <AdminPage area="serviceRequests">
      <Suspense>
        <ServiceRequestsView />
      </Suspense>
    </AdminPage>
  );
}
