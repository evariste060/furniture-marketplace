import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { ServicesView } from "@/features/admin/services";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("services");

export default function ServicesPage() {
  return (
    <AdminPage area="services">
      <Suspense>
        <ServicesView />
      </Suspense>
    </AdminPage>
  );
}
