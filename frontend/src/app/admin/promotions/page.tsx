import { AdminPage } from "@/features/admin/guard";
import { PromotionsView } from "@/features/admin/promotions";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("promotions");

export default function PromotionsPage() {
  return (
    <AdminPage area="promotions">
      <PromotionsView />
    </AdminPage>
  );
}
