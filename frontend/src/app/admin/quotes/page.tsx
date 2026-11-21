import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { QuotesView } from "@/features/admin/quotes";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("quotes");

export default function QuotesPage() {
  return (
    <AdminPage area="quotes">
      <Suspense>
        <QuotesView />
      </Suspense>
    </AdminPage>
  );
}
