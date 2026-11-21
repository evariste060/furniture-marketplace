import "server-only";
import { cookies } from "next/headers";
import createClient from "openapi-fetch";
import { CART_COOKIE, SESSION_COOKIE } from "@/lib/session-cookies";
import type { paths } from "./schema";

/** The backend origin (without /api/v1), read on the server only. */
export function apiOrigin(): string {
  const value = process.env.API_URL;
  if (!value) throw new Error("API_URL is not configured");
  return value.replace(/\/+$/, "");
}

/** Public, anonymous calls (catalogue, banners). Wrap them in "use cache" helpers. */
export function publicApi() {
  return createClient<paths>({ baseUrl: apiOrigin() });
}

/** Calls as the signed-in customer or staff member (and their guest cart). Never cached. */
export async function sessionApi() {
  const store = await cookies();
  const headers: Record<string, string> = {};
  const session = store.get(SESSION_COOKIE)?.value;
  const cart = store.get(CART_COOKIE)?.value;
  if (session) headers.Authorization = `Bearer ${session}`;
  if (cart) headers["X-Cart-Token"] = cart;
  return createClient<paths>({ baseUrl: apiOrigin(), headers });
}

export async function hasSession(): Promise<boolean> {
  return Boolean((await cookies()).get(SESSION_COOKIE)?.value);
}
