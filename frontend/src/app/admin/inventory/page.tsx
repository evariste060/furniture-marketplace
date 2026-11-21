import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { InventoryView } from "@/features/admin/inventory";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("inventory");

export default function InventoryPage() {
  return (
    <AdminPage area="inventory">
      <Suspense>
        <InventoryView />
      </Suspense>
    </AdminPage>
  );
}
