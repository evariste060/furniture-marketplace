import { Suspense } from "react";
import { ProductsView } from "@/features/admin/products";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("products");

/** The admin's product list in the seller's scope: their own store's products only. */
export default function SellerProductsPage() {
  return (
    <SellerPage>
      <Suspense>
        <ProductsView />
      </Suspense>
    </SellerPage>
  );
}
