"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

/** The signed-in customer's orders, addresses and profile (frontend phase 5). The backend
 * checks the session and ownership on every call. */

export type OrderSummary = components["schemas"]["OrderSummaryResponse"];
export type OrderDetail = components["schemas"]["OrderDetailResponse"];
export type Address = components["schemas"]["AddressResponse"];
export type AddressBody = components["schemas"]["AddressCreateRequest"];
export type Profile = components["schemas"]["CustomerProfileResponse"];

export const PROFILE_KEY = ["customer", "me"] as const;
export const ADDRESSES_KEY = ["customer", "addresses"] as const;
export const ORDERS_PAGE_SIZE = 10;

export function useOrders(page: number, size = ORDERS_PAGE_SIZE) {
  return useQuery({
    queryKey: ["customer", "orders", page, size],
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/orders", { params: { query: { page, size } } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    placeholderData: keepPreviousData,
  });
}

export function useOrder(number: string) {
  return useQuery({
    queryKey: ["customer", "order", number],
    queryFn: async (): Promise<OrderDetail> => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/orders/number/{order_number}", {
        params: { path: { order_number: number } },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });
}

/** A single-use review link for a delivered item; the review page is /review/{token}. */
export function useReviewLink() {
  return useMutation({
    mutationFn: async ({ orderId, itemId }: { orderId: string; itemId: string }) => {
      const { data, error, response } = await browserApi.POST("/api/v1/customers/me/orders/{order_id}/items/{order_item_id}/review-link", {
        params: { path: { order_id: orderId, order_item_id: itemId } },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
}

export function useUpdateProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: components["schemas"]["CustomerUpdateRequest"]) => {
      const { data, error, response } = await browserApi.PATCH("/api/v1/customers/me", { body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (profile) => {
      client.setQueryData(PROFILE_KEY, profile);
      return client.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

/** How the account can sign in (GET /auth/me: google_linked, has_password), for Profile's
 * Connected accounts. Under "customer", so signing out drops it with the other account data. */
export type SignInMethods = components["schemas"]["MeResponse"];
export const SIGN_IN_METHODS_KEY = ["customer", "sign-in-methods"] as const;

export function useSignInMethods() {
  return useQuery({
    queryKey: SIGN_IN_METHODS_KEY,
    queryFn: async (): Promise<SignInMethods> => {
      const { data, error, response } = await browserApi.GET("/api/v1/auth/me");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: async (body: components["schemas"]["ChangePasswordRequest"]) => {
      const { data, error, response } = await browserApi.POST("/api/v1/auth/change-password", { body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
}

/** Add, edit, delete and make default: each refreshes the list (the backend keeps exactly one
 * default, so a change can move the badge to another address). */
export function useAddressMutations() {
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries({ queryKey: ADDRESSES_KEY });
  const create = useMutation({
    mutationFn: async (body: AddressBody) => {
      const { data, error, response } = await browserApi.POST("/api/v1/customers/me/addresses", { body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSettled: refresh,
  });
  const update = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: components["schemas"]["AddressUpdateRequest"] }) => {
      const { data, error, response } = await browserApi.PUT("/api/v1/customers/me/addresses/{address_id}", { params: { path: { address_id: id } }, body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      const { error, response } = await browserApi.DELETE("/api/v1/customers/me/addresses/{address_id}", { params: { path: { address_id: id } } });
      if (!response.ok) throw ApiError.from(response.status, error);
    },
    onSettled: refresh,
  });
  const makeDefault = useMutation({
    mutationFn: async (id: string) => {
      const { data, error, response } = await browserApi.POST("/api/v1/customers/me/addresses/{address_id}/default", { params: { path: { address_id: id } } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSettled: refresh,
  });
  return { create, update, remove, makeDefault };
}
