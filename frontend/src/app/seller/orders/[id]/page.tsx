import { SellerOrderDetailView } from "@/features/seller/order-detail";
import { SellerPage, sellerMetadata } from "@/features/seller/page";

export const generateMetadata = sellerMetadata("order");

export default function SellerOrderPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <SellerPage>
      <Order params={params} />
    </SellerPage>
  );
}

/** Reads the URL inside SellerPage's Suspense boundary. */
async function Order({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SellerOrderDetailView id={id} />;
}
