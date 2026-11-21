import { AdminPage } from "@/features/admin/guard";
import { OrderDetailView } from "@/features/admin/order-detail";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("order");

export default function OrderDetailPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <AdminPage area="orders">
      <OrderDetail params={params} />
    </AdminPage>
  );
}

/** Reads the URL inside AdminPage's Suspense boundary. */
async function OrderDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <OrderDetailView orderId={id} />;
}
