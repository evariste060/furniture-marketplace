import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { SellersView } from "@/features/admin/sellers";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("sellers");

export default function SellersPage() {
  return (
    <AdminPage area="sellers">
      <Suspense>
        <SellersView />
      </Suspense>
    </AdminPage>
  );
}
