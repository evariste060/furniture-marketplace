import { Suspense } from "react";
import { SellerOrdersView } from "@/features/seller/orders";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("orders");

export default function SellerOrdersPage() {
  return (
    <SellerPage>
      <Suspense>
        <SellerOrdersView />
      </Suspense>
    </SellerPage>
  );
}
