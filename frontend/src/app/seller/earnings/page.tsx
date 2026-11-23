import { Suspense } from "react";
import { SellerEarningsView } from "@/features/seller/earnings";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("earnings");

export default function SellerEarningsPage() {
  return (
    <SellerPage>
      <Suspense>
        <SellerEarningsView />
      </Suspense>
    </SellerPage>
  );
}
