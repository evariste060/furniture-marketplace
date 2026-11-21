"use client";

import { useQuery } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/client";

/** The store's public contact details (GET /settings, module 19) for client components. The
 * server caches the answer for a minute, so one request per visit is enough. `contact` is
 * undefined while loading or when the request failed (`settled` tells them apart): callers then
 * leave the contact line out. */
export function useStoreContact() {
  const query = useQuery({
    queryKey: ["store-contact"],
    queryFn: async () => {
      const { data } = await browserApi.GET("/api/v1/settings");
      if (!data) throw new Error("settings unavailable");
      return data;
    },
    staleTime: 5 * 60_000,
    retry: 1,
  });
  return { contact: query.data, settled: query.isSuccess || query.isError };
}
