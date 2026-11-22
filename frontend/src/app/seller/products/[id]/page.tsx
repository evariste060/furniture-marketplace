import { ProductEditorView } from "@/features/admin/product-editor";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("product");

export default function SellerProductPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <SellerPage>
      <Editor params={params} />
    </SellerPage>
  );
}

/** Reads the URL inside SellerPage's Suspense boundary. */
async function Editor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProductEditorView productId={id} />;
}
