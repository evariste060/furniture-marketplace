import { AdminPage } from "@/features/admin/guard";
import { ImportView } from "@/features/admin/import";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("import");

export default function ImportPage() {
  return (
    <AdminPage area="import">
      <ImportView />
    </AdminPage>
  );
}
