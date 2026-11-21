import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { PaymentsView } from "@/features/admin/payments";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("payments");

export default function PaymentsPage() {
  return (
    <AdminPage area="payments">
      <Suspense>
        <PaymentsView />
      </Suspense>
    </AdminPage>
  );
}
