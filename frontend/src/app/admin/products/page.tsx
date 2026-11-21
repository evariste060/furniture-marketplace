import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { ProductsView } from "@/features/admin/products";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("products");

export default function ProductsPage() {
  return (
    <AdminPage area="products">
      <Suspense>
        <ProductsView />
      </Suspense>
    </AdminPage>
  );
}
