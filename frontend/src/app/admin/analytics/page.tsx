import { AnalyticsView } from "@/features/admin/analytics";
import { AdminPage } from "@/features/admin/guard";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("analytics");

export default function AnalyticsPage() {
  return (
    <AdminPage area="analytics">
      <AnalyticsView />
    </AdminPage>
  );
}
