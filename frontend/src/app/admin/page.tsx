import { Dashboard } from "@/features/admin/dashboard";
import { AdminPage } from "@/features/admin/guard";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("dashboard");

export default function DashboardPage() {
  return (
    <AdminPage area="dashboard">
      <Dashboard />
    </AdminPage>
  );
}
