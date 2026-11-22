import { ProductEditorView } from "@/features/admin/product-editor";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("newProduct");

export default function SellerNewProductPage() {
  return (
    <SellerPage>
      <ProductEditorView />
    </SellerPage>
  );
}
