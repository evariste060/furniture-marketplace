import { AdminPage } from "@/features/admin/guard";
import { ProductEditorView } from "@/features/admin/product-editor";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("newProduct");

export default function NewProductPage() {
  return (
    <AdminPage area="products">
      <ProductEditorView />
    </AdminPage>
  );
}
