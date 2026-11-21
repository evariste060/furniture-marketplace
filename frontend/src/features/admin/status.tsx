"use client";

import { useTranslations } from "next-intl";
import { PaymentMark } from "@/features/checkout/payment-mark";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import type { components } from "@/lib/api/schema";

export type OrderStatus = components["schemas"]["StaffOrderDetailResponse"]["status"];
export type PaymentStatus = components["schemas"]["StaffPaymentItem"]["status"];
export type PaymentMethod = components["schemas"]["StaffPaymentItem"]["method"];

export const ORDER_STATUSES: OrderStatus[] = ["received", "confirmed", "processing", "dispatched", "delivered", "cancelled"];
export const PAYMENT_METHODS: PaymentMethod[] = ["mtn_momo", "airtel_money", "card", "cash_on_delivery"];

/** Orders.dc.html badge colours, by the backend's order statuses. */
export const ORDER_TONE: Record<OrderStatus, BadgeTone> = {
  received: "soft-warn",
  confirmed: "soft-ok",
  processing: "soft-info",
  dispatched: "soft-purple",
  delivered: "soft-ok",
  cancelled: "soft-err",
};

const PAYMENT_TONE: Record<PaymentStatus, BadgeTone> = {
  created: "soft-neutral",
  pending: "soft-warn",
  succeeded: "soft-ok",
  failed: "soft-err",
  cancelled: "soft-neutral",
  expired: "soft-err",
  refunded: "soft-neutral",
  partially_refunded: "soft-neutral",
};

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const t = useTranslations("admin.status.order");
  return <Badge tone={ORDER_TONE[status]}>{t(status)}</Badge>;
}

/** A pending cash-on-delivery payment reads "On delivery" (Orders.dc.html). */
export function PaymentStatusBadge({ status, method }: { status: PaymentStatus; method?: PaymentMethod | null }) {
  const t = useTranslations("admin.status.payment");
  const cod = method === "cash_on_delivery" && status === "pending";
  return <Badge tone={cod ? "soft-neutral" : PAYMENT_TONE[status]}>{t(cod ? "cod_pending" : status)}</Badge>;
}

/** Payments.dc.html method badges: the checkout provider marks, and a navy "Card" mark. */
export function MethodMark({ method }: { method: PaymentMethod }) {
  const t = useTranslations("admin.status.method");
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      {method === "card" ? (
        <span aria-hidden="true" className="inline-flex h-5 items-center rounded-sm bg-navy px-2 text-cap font-semibold text-white">
          Card
        </span>
      ) : (
        <PaymentMark method={method} size="sm" />
      )}
      <span className="text-sm text-tx2">{t(method)}</span>
    </span>
  );
}
