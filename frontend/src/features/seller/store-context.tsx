"use client";

import { createContext, useContext, type ReactNode } from "react";

/** The seller's own store as the layout read it on the server (ADR-014 phase 4). It only decides
 * what the dashboard shows; the backend resolves the store again on every call. */
export type ClientSellerStore = {
  id: string;
  name: string;
  slug: string;
  commissionRateBps: number;
};

const StoreContext = createContext<ClientSellerStore | null>(null);

export function SellerStoreProvider({ store, children }: { store: ClientSellerStore; children: ReactNode }) {
  return <StoreContext.Provider value={store}>{children}</StoreContext.Provider>;
}

export function useSellerStore(): ClientSellerStore {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useSellerStore is used outside the seller dashboard");
  return store;
}

/** Basis points as a percentage for display: 1000 → "10", 1250 → "12.5". */
export function percent(bps: number): string {
  return String(Math.round(bps) / 100);
}
