"use client";

import { useTranslations } from "next-intl";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { SellerOrderStatus } from "./orders-api";

/** A seller order's status colours, matching the admin's order badges. */
export const SELLER_ORDER_TONE: Record<SellerOrderStatus, BadgeTone> = {
  pending: "soft-warn",
  confirmed: "soft-ok",
  processing: "soft-info",
  dispatched: "soft-purple",
  delivered: "soft-ok",
  cancelled: "soft-err",
};

export function SellerOrderBadge({ status }: { status: SellerOrderStatus }) {
  const t = useTranslations("admin.status.sellerOrder");
  return <Badge tone={SELLER_ORDER_TONE[status]}>{t(status)}</Badge>;
}
