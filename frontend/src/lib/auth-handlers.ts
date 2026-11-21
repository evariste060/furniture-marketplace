import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import { apiOrigin } from "@/lib/api/server";
import { clientIpHeaders } from "@/lib/client-ip";
import { forbiddenOrigin, isSameSiteRequest } from "@/lib/origin";
import { CART_COOKIE, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session-cookies";

/** Sign-in, registration and sign-out (ADR-006): the backend's session token goes into an
 * httpOnly cookie and never reaches browser JavaScript. On sign-in the guest cart is merged into
 * the customer's cart (POST /cart/merge) and its cookie is cleared. */

type AuthBody = { user?: unknown; session_token?: string | null; expires_at?: string | null; verification_required?: boolean };

export function unavailable(): NextResponse {
  return NextResponse.json(
    { error: { code: "backend_unavailable", message: "The service is unavailable." } },
    { status: 502 },
  );
}

/** Headers for one call to the API: JSON, any credentials in `extra`, and the shopper's signed
 * address for that exact method and path (ADR-006, 2026-11-13; ./client-ip.ts). The browser's own
 * X-Forwarded-For is never passed on. `path` is the API path without the query. */
export function forwardHeaders(request: NextRequest, method: string, path: string, extra: Record<string, string> = {}): Headers {
  return new Headers({ "content-type": "application/json", ...extra, ...clientIpHeaders(request, method, path) });
}

async function signIn(
  request: NextRequest,
  backendPath: "api/v1/auth/login" | "api/v1/auth/register",
  fetcher: typeof fetch,
): Promise<NextResponse> {
  if (!isSameSiteRequest(request)) return forbiddenOrigin();
  let upstream: Response;
  try {
    upstream = await fetcher(`${apiOrigin()}/${backendPath}`, {
      method: "POST",
      headers: forwardHeaders(request, "POST", `/${backendPath}`),
      body: await request.text(),
      cache: "no-store",
    });
  } catch {
    return unavailable();
  }
  const body = (await upstream.json().catch(() => null)) as AuthBody | null;
  if (upstream.ok && body?.verification_required === true && body.user) {
    // Registered with an email (backend 2026-11-12): no session until the address is verified.
    // Nothing to set, and no guest-cart merge yet: that happens at the first sign-in.
    return NextResponse.json({ user: body.user, verification_required: true }, { status: upstream.status });
  }
  if (!upstream.ok || !body?.session_token || !body.expires_at) {
    const headers = new Headers();
    const retry = upstream.headers.get("retry-after");
    if (retry) headers.set("retry-after", retry);
    return NextResponse.json(body ?? {}, { status: upstream.status, headers });
  }

  const response = NextResponse.json({ user: body.user }, { status: upstream.status });
  await establishSession(request, response, body.session_token, body.expires_at, fetcher);
  return response;
}

/** Every successful sign-in (password, registration, Continue with Google): the session token goes
 * into the httpOnly session cookie, and the guest cart, if any, is merged into the account's cart
 * and its cookie cleared. */
export async function establishSession(
  request: NextRequest,
  response: NextResponse,
  sessionToken: string,
  expiresAt: string,
  fetcher: typeof fetch,
): Promise<void> {
  response.cookies.set(SESSION_COOKIE, sessionToken, sessionCookieOptions(expiresAt));
  const cart = request.cookies.get(CART_COOKIE)?.value;
  if (cart) {
    // Best effort: a failed merge must not fail the sign-in. A merged (converted), expired or
    // unknown guest cart is no longer usable either way, so the cookie is cleared.
    await fetcher(`${apiOrigin()}/api/v1/cart/merge`, {
      method: "POST",
      headers: forwardHeaders(request, "POST", "/api/v1/cart/merge", {
        authorization: `Bearer ${sessionToken}`,
        "x-cart-token": cart,
      }),
      cache: "no-store",
    }).catch(() => undefined);
    response.cookies.delete(CART_COOKIE);
  }
}

export function login(request: NextRequest, fetcher: typeof fetch = fetch) {
  return signIn(request, "api/v1/auth/login", fetcher);
}

export function register(request: NextRequest, fetcher: typeof fetch = fetch) {
  return signIn(request, "api/v1/auth/register", fetcher);
}

export async function logout(
  request: NextRequest,
  fetcher: typeof fetch = fetch,
  everywhere = false,
): Promise<NextResponse> {
  if (!isSameSiteRequest(request)) return forbiddenOrigin();
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (session) {
    const path = everywhere ? "api/v1/auth/logout-all" : "api/v1/auth/logout";
    await fetcher(`${apiOrigin()}/${path}`, {
      method: "POST",
      headers: forwardHeaders(request, "POST", `/${path}`, { authorization: `Bearer ${session}` }),
      cache: "no-store",
    }).catch(() => undefined);
  }
  const response = new NextResponse(null, { status: 204 });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}

/** "Log out everywhere" (Profile): every session of the account ends, this one included. */
export function logoutEverywhere(request: NextRequest, fetcher: typeof fetch = fetch) {
  return logout(request, fetcher, true);
}

/** Who is signed in, for the storefront header (account label, wishlist, cart). A guest gets
 * {user: null} without a backend call, so the page never logs a 401. Only the fields the header
 * needs are returned. */
export type SessionUser = { full_name: string | null; is_staff: boolean; is_customer: boolean };

export async function session(request: NextRequest, fetcher: typeof fetch = fetch): Promise<NextResponse> {
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const noStore = { "cache-control": "no-store" };
  if (!token) return NextResponse.json({ user: null }, { headers: noStore });
  let upstream: Response;
  try {
    upstream = await fetcher(`${apiOrigin()}/api/v1/auth/me`, {
      headers: forwardHeaders(request, "GET", "/api/v1/auth/me", { authorization: `Bearer ${token}` }),
      cache: "no-store",
    });
  } catch {
    return unavailable();
  }
  if (upstream.status === 401) {
    const response = NextResponse.json({ user: null }, { headers: noStore });
    response.cookies.delete(SESSION_COOKIE);
    return response;
  }
  if (!upstream.ok) return unavailable();
  const me = (await upstream.json()) as { full_name?: string | null; is_staff?: boolean; roles?: string[] };
  const user: SessionUser = {
    full_name: me.full_name ?? null,
    is_staff: Boolean(me.is_staff),
    // The backend's customer-only rule (wishlist, cart): not staff and no role but customer.
    is_customer: !me.is_staff && (me.roles ?? []).length === 1 && me.roles?.[0] === "customer",
  };
  return NextResponse.json({ user }, { headers: noStore });
}
