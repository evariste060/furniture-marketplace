"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Cart = components["schemas"]["CartResponse"];
export type CartLine = components["schemas"]["CartLine"];

export const CART_KEY = ["cart"] as const;

async function readCart(zone?: string): Promise<Cart> {
  const query = zone ? { zone } : {};
  let result = await browserApi.GET("/api/v1/cart", { params: { query } });
  // A guest cart that expired or became an order: the proxy has forgotten its token, so a
  // second read starts afresh (an empty cart).
  if (!result.data && result.response.status === 404) result = await browserApi.GET("/api/v1/cart", { params: { query } });
  if (!result.data) throw ApiError.from(result.response.status, result.error);
  return result.data;
}

/** The visitor's cart (guest or customer) through the proxy; the backend prices it. With a
 * delivery zone code the cart also carries the delivery quote and the grand total. */
export function useCart(zone?: string | null, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: zone ? [...CART_KEY, zone] : CART_KEY,
    queryFn: () => readCart(zone ?? undefined),
    enabled,
  });
}

/** The cart a change returned replaces the cached one; zone quotes are read again. */
function store(client: QueryClient, cart: Cart | null) {
  if (cart) client.setQueryData(CART_KEY, cart);
  return client.invalidateQueries({
    queryKey: CART_KEY,
    predicate: (query) => query.queryKey.length > 1 || cart === null,
  });
}

/** The cart's limit per line (backend MAX_LINE_QUANTITY, plan §7 Q10). */
export const MAX_LINE_QUANTITY = 99;

/** Adds units of a variant (one unless a quantity is given). The returned cart replaces the
 * cached one (the count updates). */
export function useAddToCart() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: string | { variantId: string; quantity: number }) => {
      const { variantId, quantity } = typeof input === "string" ? { variantId: input, quantity: 1 } : input;
      const { data, error, response } = await browserApi.POST("/api/v1/cart/items", {
        body: { variant_id: variantId, quantity },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (cart) => store(client, cart),
  });
}

export function useSetQuantity() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ lineId, quantity }: { lineId: string; quantity: number }) => {
      const { data, error, response } = await browserApi.PATCH("/api/v1/cart/items/{item_id}", {
        params: { path: { item_id: lineId } },
        body: { quantity },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (cart) => store(client, cart),
    onError: () => store(client, null),
  });
}

export function useRemoveLine() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (lineId: string) => {
      const { error, response } = await browserApi.DELETE("/api/v1/cart/items/{item_id}", {
        params: { path: { item_id: lineId } },
      });
      if (!response.ok) throw ApiError.from(response.status, error);
    },
    onSettled: () => store(client, null),
  });
}

export function useApplyCode() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (code: string) => {
      const { data, error, response } = await browserApi.POST("/api/v1/cart/apply-code", { body: { code } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (cart) => store(client, cart),
  });
}

export function useRemoveCode() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await browserApi.DELETE("/api/v1/cart/code");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (cart) => store(client, cart),
  });
}

/** "Accept changes": the customer has seen the new prices (display only; totals always use
 * today's prices). */
export function useAcceptPrices() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await browserApi.POST("/api/v1/cart/accept-prices");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (cart) => store(client, cart),
  });
}

/** Lines that can be ordered, and those that block checkout until removed or fixed. */
export function splitLines(cart: Pick<Cart, "lines">) {
  return {
    available: cart.lines.filter((line) => line.status === "available"),
    blocked: cart.lines.filter((line) => line.status !== "available"),
  };
}
