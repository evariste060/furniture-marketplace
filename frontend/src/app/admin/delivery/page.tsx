import { AdminPage } from "@/features/admin/guard";
import { DeliveryView } from "@/features/admin/delivery";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("delivery");

export default function DeliveryPage() {
  return (
    <AdminPage area="delivery">
      <DeliveryView />
    </AdminPage>
  );
}
