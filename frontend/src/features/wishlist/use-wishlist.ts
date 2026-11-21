"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useSession } from "@/features/session/use-session";

export const WISHLIST_IDS_KEY = ["wishlist", "ids"] as const;
/** Under "customer", so signing out drops it with the rest of the account data. */
export const WISHLIST_KEY = ["customer", "wishlist"] as const;
export const WISHLIST_PAGE_SIZE = 24;
type Ids = { product_ids: string[]; count: number; limit: number };

/** The signed-in customer's saved product IDs. The catalogue is the same for everyone, so the
 * hearts are marked here, in the browser. Guests and staff have no wishlist. */
export function useWishlistIds() {
  const { data: user } = useSession();
  return useQuery({
    queryKey: WISHLIST_IDS_KEY,
    enabled: Boolean(user?.is_customer),
    queryFn: async (): Promise<Ids> => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/wishlist/ids");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
}

/** /account/wishlist: the saved products, newest first. A product no longer sold comes back with
 * only its name, slug and first image (available: false). */
export function useWishlist(page: number) {
  return useQuery({
    queryKey: [...WISHLIST_KEY, page],
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/wishlist", {
        params: { query: { page, size: WISHLIST_PAGE_SIZE } },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    placeholderData: keepPreviousData,
  });
}

/** Saves or removes a product (PUT and DELETE are idempotent), updating the hearts at once and
 * rolling back if the backend refuses (e.g. wishlist_full). */
export function useToggleWishlist() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ productId, save }: { productId: string; save: boolean }) => {
      const params = { path: { product_id: productId } };
      const { data, error, response } = save
        ? await browserApi.PUT("/api/v1/customers/me/wishlist/{product_id}", { params })
        : await browserApi.DELETE("/api/v1/customers/me/wishlist/{product_id}", { params });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onMutate: async ({ productId, save }) => {
      await client.cancelQueries({ queryKey: WISHLIST_IDS_KEY });
      const before = client.getQueryData<Ids>(WISHLIST_IDS_KEY);
      if (before) {
        const ids = save ? [...new Set([productId, ...before.product_ids])] : before.product_ids.filter((id) => id !== productId);
        client.setQueryData<Ids>(WISHLIST_IDS_KEY, { ...before, product_ids: ids, count: ids.length });
      }
      return { before };
    },
    onError: (_error, _vars, context) => {
      if (context?.before) client.setQueryData(WISHLIST_IDS_KEY, context.before);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: WISHLIST_IDS_KEY });
      void client.invalidateQueries({ queryKey: WISHLIST_KEY });
    },
  });
}

/** Where a guest's heart click goes: sign in, then the login page saves the product and returns
 * (the login page is built in frontend phase 5). */
export function loginForWishlist(returnTo: string, productId: string): string {
  const q = new URLSearchParams({ returnTo, wishlist: productId });
  return `/login?${q.toString()}`;
}
