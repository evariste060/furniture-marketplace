import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { ReviewsView } from "@/features/admin/reviews";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("reviews");

export default function ReviewsPage() {
  return (
    <AdminPage area="reviews">
      <Suspense>
        <ReviewsView />
      </Suspense>
    </AdminPage>
  );
}
