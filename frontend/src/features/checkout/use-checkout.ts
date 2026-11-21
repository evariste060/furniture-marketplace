"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { CART_KEY } from "@/features/cart/use-cart";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type SavedAddress = components["schemas"]["AddressResponse"];
export type CheckoutBody = components["schemas"]["CheckoutRequest"];
export type CheckoutResult = components["schemas"]["CheckoutResponse"];

/** The signed-in customer's profile, to fill in the contact step. */
export function useProfile(enabled: boolean) {
  return useQuery({
    queryKey: ["customer", "me"],
    enabled,
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    staleTime: 60_000,
  });
}

/** The signed-in customer's saved addresses (default first, as the backend lists them). */
export function useSavedAddresses(enabled: boolean) {
  return useQuery({
    queryKey: ["customer", "addresses"],
    enabled,
    queryFn: async (): Promise<SavedAddress[]> => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/addresses");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
}

/** Saves the checkout address to the customer's account ("Save this address to my account"). */
export function useSaveAddress() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: components["schemas"]["AddressCreateRequest"]) => {
      const { data, error, response } = await browserApi.POST("/api/v1/customers/me/addresses", { body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["customer", "addresses"] }),
  });
}

function newKey(): string {
  return `web-${crypto.randomUUID()}`;
}

/** Places the order. One Idempotency-Key per order body: a retry of the same order (a lost
 * response, a double click) reuses it and gets the same order back; a changed order gets a new
 * key, since the backend refuses a reused key with a different body. The backend prices the
 * order from the cart; the page sends no amount. */
export function usePlaceOrder() {
  const client = useQueryClient();
  const last = useRef<{ key: string; body: string } | null>(null);
  return useMutation({
    mutationFn: async (body: CheckoutBody): Promise<CheckoutResult> => {
      const json = JSON.stringify(body);
      if (last.current?.body !== json) last.current = { key: newKey(), body: json };
      const { data, error, response } = await browserApi.POST("/api/v1/checkout", {
        params: { header: { "Idempotency-Key": last.current.key } },
        body,
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: () => {
      last.current = null;
      // Not awaited: the page moves on to the order at once (the cart is now empty).
      void client.invalidateQueries({ queryKey: CART_KEY });
    },
  });
}
