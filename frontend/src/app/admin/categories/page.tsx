import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { CategoriesView } from "@/features/admin/categories";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("categories");

export default function CategoriesPage() {
  return (
    <AdminPage area="categories">
      <Suspense>
        <CategoriesView />
      </Suspense>
    </AdminPage>
  );
}
