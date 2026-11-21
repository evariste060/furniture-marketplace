"use client";

import { AdminErrorCard } from "@/features/admin/error-card";

export default function AdminError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <AdminErrorCard {...props} />;
}
