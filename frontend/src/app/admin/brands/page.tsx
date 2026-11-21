import { AdminPage } from "@/features/admin/guard";
import { BrandsView } from "@/features/admin/categories";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("brands");

/** The Brands tab of Categories & brands (Categories.dc.html, redesigned 2026-11-16). */
export default function BrandsPage() {
  return (
    <AdminPage area="categories">
      <BrandsView />
    </AdminPage>
  );
}
