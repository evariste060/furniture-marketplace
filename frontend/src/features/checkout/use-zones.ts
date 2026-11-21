"use client";

import { useQuery } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Zone = components["schemas"]["PublicDeliveryZone"];
export type Zones = components["schemas"]["PublicDeliveryZonesResponse"];

/** The active delivery zones and the free-delivery threshold (public; the backend prices the
 * delivery again at checkout). */
export function useZones() {
  return useQuery({
    queryKey: ["delivery", "zones"],
    queryFn: async (): Promise<Zones> => {
      const { data, error, response } = await browserApi.GET("/api/v1/delivery/zones");
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

/** True when the cart's merchandise (after discount) reaches the free-delivery threshold. */
export function freeDelivery(subtotalAfterDiscount: number, zones: Zones | undefined): boolean {
  const threshold = zones?.free_delivery_threshold;
  return threshold != null && zones!.items.length > 0 && subtotalAfterDiscount >= threshold;
}
