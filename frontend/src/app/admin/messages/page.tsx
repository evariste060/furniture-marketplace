import { Suspense } from "react";
import { MessagesView } from "@/features/admin/messages";
import { AdminPage } from "@/features/admin/guard";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("messages");

export default function MessagesPage() {
  return (
    <AdminPage area="messages">
      <Suspense>
        <MessagesView />
      </Suspense>
    </AdminPage>
  );
}
