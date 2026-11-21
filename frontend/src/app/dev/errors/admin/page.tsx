"use client";

import { AdminErrorCard } from "@/features/admin/error-card";

const SAMPLE = Object.assign(new Error("Preview of the error page"), { digest: "1234567890" });

/** Development only: the admin error card, drawn for review and the browser tests. */
export default function AdminErrorPreview() {
  return (
    <main className="min-h-dvh bg-page p-4">
      <AdminErrorCard error={SAMPLE} reset={() => undefined} />
    </main>
  );
}
