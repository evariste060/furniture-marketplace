import "server-only";
import { cache } from "react";
import type { components } from "@/lib/api/schema";
import { hasSession, sessionApi } from "@/lib/api/server";

/** Who opened the seller dashboard (ADR-014 phase 4), checked on the server for every /seller
 * page. Seller rights come only from owning an approved store; the backend resolves the store
 * again on every call, so this only decides what the dashboard shows. */
export type SellerStore = components["schemas"]["SellerStoreResponse"];

export type SellerVisitor =
  | { kind: "signed-out" }
  /** Staff accounts cannot sell (they have the admin). */
  | { kind: "staff" }
  /** A customer who has not applied. */
  | { kind: "no-store" }
  /** A customer whose store is pending, rejected or suspended. */
  | { kind: "not-approved"; store: SellerStore }
  | { kind: "seller"; store: SellerStore; fullName: string };

/** Read once per request (the layout and the page both ask). */
export const getSellerVisitor = cache(async (): Promise<SellerVisitor> => {
  if (!(await hasSession())) return { kind: "signed-out" };
  const api = await sessionApi();
  const me = await api.GET("/api/v1/auth/me");
  if (!me.data) return { kind: "signed-out" };
  if (me.data.is_staff) return { kind: "staff" };
  const store = await api.GET("/api/v1/seller/store");
  if (store.response.status === 401) return { kind: "signed-out" };
  if (store.data) return { kind: "seller", store: store.data, fullName: me.data.full_name ?? "" };
  // 403 seller_not_approved: no store, or one that is not approved.
  const application = await api.GET("/api/v1/seller/application");
  if (application.response.status === 401) return { kind: "signed-out" };
  return application.data ? { kind: "not-approved", store: application.data } : { kind: "no-store" };
});

export async function getSellerStore(): Promise<SellerStore | null> {
  const visitor = await getSellerVisitor();
  return visitor.kind === "seller" ? visitor.store : null;
}
