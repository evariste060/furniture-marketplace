import { SellerPage, sellerMetadata } from "@/features/seller/page";
import { StoreProfileView } from "@/features/seller/store-profile";

export const generateMetadata = sellerMetadata("store");

export default function SellerStorePage() {
  return (
    <SellerPage>
      <StoreProfileView />
    </SellerPage>
  );
}
