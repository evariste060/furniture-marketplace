import { AdminPage } from "@/features/admin/guard";
import { ProductEditorView } from "@/features/admin/product-editor";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("product");

export default function ProductEditorPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <AdminPage area="products">
      <Editor params={params} />
    </AdminPage>
  );
}

/** Reads the URL inside AdminPage's Suspense boundary. */
async function Editor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProductEditorView productId={id} />;
}
