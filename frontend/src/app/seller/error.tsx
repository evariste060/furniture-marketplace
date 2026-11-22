"use client";

import { AdminErrorCard } from "@/features/admin/error-card";

export default function SellerError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <AdminErrorCard {...props} home="/seller" />;
}
