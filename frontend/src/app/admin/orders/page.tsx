import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { OrdersView } from "@/features/admin/orders";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("orders");

export default function OrdersPage() {
  return (
    <AdminPage area="orders">
      <Suspense>
        <OrdersView />
      </Suspense>
    </AdminPage>
  );
}
