import { AdminPage } from "@/features/admin/guard";
import { SellerDetailView } from "@/features/admin/sellers";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("seller");

export default function SellerPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <AdminPage area="sellers">
      <Detail params={params} />
    </AdminPage>
  );
}

/** Reads the URL inside AdminPage's Suspense boundary. */
async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SellerDetailView id={id} />;
}
