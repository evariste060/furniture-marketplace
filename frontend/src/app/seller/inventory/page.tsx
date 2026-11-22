import { Suspense } from "react";
import { InventoryView } from "@/features/admin/inventory";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("inventory");

/** The admin's stock screen in the seller's scope: their own store's SKUs only. */
export default function SellerInventoryPage() {
  return (
    <SellerPage>
      <Suspense>
        <InventoryView />
      </Suspense>
    </SellerPage>
  );
}
