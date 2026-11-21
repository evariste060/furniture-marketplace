import { Suspense } from "react";
import { AdminPage } from "@/features/admin/guard";
import { SettingsView } from "@/features/admin/settings";
import { adminMetadata } from "@/features/admin/titles";

export const generateMetadata = adminMetadata("settings");

export default function SettingsPage() {
  return (
    <AdminPage area="settings">
      <Suspense>
        <SettingsView />
      </Suspense>
    </AdminPage>
  );
}
