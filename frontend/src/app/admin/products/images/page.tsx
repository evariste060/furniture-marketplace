import { AdminPage } from "@/features/admin/guard";
import { BulkImagesView } from "@/features/admin/bulk-images";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("productPhotos");

export default function BulkImagesPage() {
  return (
    <AdminPage area="bulkImages">
      <BulkImagesView />
    </AdminPage>
  );
}
