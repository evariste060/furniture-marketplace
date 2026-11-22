"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { must } from "@/features/admin/ui";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

/** The seller's own seller orders and earnings (ADR-014 phase 4, backend phase 3). The backend
 * limits every call to the caller's store; another store's order answers 404. */

export type SellerOrderSummary = components["schemas"]["SellerOrderSummary"];
export type SellerOrderDetail = components["schemas"]["SellerOrderDetail"];
export type SellerOrderStatus = SellerOrderSummary["status"];
export type SellerMove = components["schemas"]["SellerOrderStatusRequest"]["status"];
export type SellerEarnings = components["schemas"]["SellerEarningsResponse"];

export const SELLER_ORDER_STATUSES: SellerOrderStatus[] = ["pending", "confirmed", "processing", "dispatched", "delivered", "cancelled"];

/** The one step a seller can take next (the backend's SELLER_ORDER_TRANSITIONS); null at the end. */
export function nextSellerStep(status: SellerOrderStatus): SellerMove | null {
  switch (status) {
    case "pending":
      return "confirmed";
    case "confirmed":
      return "processing";
    case "processing":
      return "dispatched";
    case "dispatched":
      return "delivered";
    default:
      return null;
  }
}

/** The message key of a refused move's code, by the backend's 409 codes. */
export function moveErrorKey(error: unknown): "awaitingPayment" | "awaitingOtherStores" | "invalid" | "inventory" | "failed" {
  if (!(error instanceof ApiError)) return "failed";
  switch (error.code) {
    case "seller_order_awaiting_payment":
      return "awaitingPayment";
    case "seller_order_awaiting_other_stores":
      return "awaitingOtherStores";
    case "invalid_transition":
      return "invalid";
    case "inventory_conflict":
      return "inventory";
    default:
      return "failed";
  }
}

export function isSellerOrderStatus(value: string): value is SellerOrderStatus {
  return (SELLER_ORDER_STATUSES as string[]).includes(value);
}

export function useSellerOrders(query: { status?: SellerOrderStatus; q?: string; page: number; size: number }) {
  return useQuery({
    queryKey: ["seller", "orders", query],
    queryFn: () => must(browserApi.GET("/api/v1/seller/orders", { params: { query } })),
    placeholderData: keepPreviousData,
  });
}

export function useSellerOrder(id: string) {
  return useQuery({
    queryKey: ["seller", "order", id],
    queryFn: () => must(browserApi.GET("/api/v1/seller/orders/{seller_order_id}", { params: { path: { seller_order_id: id } } })),
    retry: (count, error) => !(error instanceof ApiError && [404, 422].includes(error.status)) && count < 2,
  });
}

export function useSellerEarnings() {
  return useQuery({
    queryKey: ["seller", "earnings"],
    queryFn: () => must(browserApi.GET("/api/v1/seller/earnings")),
  });
}

/** One step of the seller's own order. Every seller query is refreshed afterwards: the badge,
 * the lists, the earnings and stock (dispatching issues this store's stock). */
export function useMoveSellerOrder(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { status: SellerMove; reason?: string | null }) =>
      must(browserApi.PATCH("/api/v1/seller/orders/{seller_order_id}/status", { params: { path: { seller_order_id: id } }, body })),
    onSuccess: (detail) => client.setQueryData(["seller", "order", id], detail),
    onSettled: () => client.invalidateQueries({ queryKey: ["seller"] }),
  });
}
