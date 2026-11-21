import type { components } from "@/lib/api/schema";
import type { BadgeTone } from "@/components/ui/badge";

/** The delivery progress on Track and the account's order page (Track.dc.html,
 * OrderDetail.dc.html), read from the order's status and its status history. */

type Order = Pick<components["schemas"]["OrderDetailResponse"], "status" | "created_at" | "status_history" | "payment">;
export type OrderStatus = Order["status"];

const FLOW: readonly OrderStatus[] = ["received", "confirmed", "processing", "dispatched", "delivered"];

export const STATUS_TONE: Record<OrderStatus, BadgeTone> = {
  received: "soft-neutral",
  confirmed: "soft-info",
  processing: "soft-info",
  dispatched: "soft-info",
  delivered: "soft-ok",
  cancelled: "soft-err",
};

export type StepKey = "placed" | "paid" | "packed" | "dispatched" | "delivered";
export type ProgressStep = { key: StepKey; state: "done" | "now" | "todo"; at: string | null };

/** When the order last entered `status`, from its history. */
export function statusTime(order: Pick<Order, "status_history">, status: OrderStatus): string | null {
  const entries = order.status_history.filter((h) => h.status === status);
  return entries.length ? entries[entries.length - 1]!.created_at : null;
}

/** Placed → paid (or confirmed, for cash on delivery) → packed → out for delivery → delivered.
 * The first step not yet done is the current one. */
export function orderProgress(order: Order): ProgressStep[] {
  const reached = (status: OrderStatus) => order.status !== "cancelled" && FLOW.indexOf(order.status) >= FLOW.indexOf(status);
  const cash = order.payment?.method === "cash_on_delivery";
  const paid = cash ? reached("confirmed") : order.payment?.status === "succeeded" || reached("confirmed");
  const done: Array<[StepKey, boolean, string | null]> = [
    ["placed", true, order.created_at],
    ["paid", paid, statusTime(order, "confirmed")],
    ["packed", reached("processing"), statusTime(order, "processing")],
    ["dispatched", reached("dispatched"), statusTime(order, "dispatched")],
    ["delivered", reached("delivered"), statusTime(order, "delivered")],
  ];
  const current = done.findIndex(([, isDone]) => !isDone);
  return done.map(([key, isDone, at], i) => ({ key, state: isDone ? "done" : i === current ? "now" : "todo", at: isDone ? at : null }));
}
