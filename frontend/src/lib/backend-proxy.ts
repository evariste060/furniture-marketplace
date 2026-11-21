import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import { apiOrigin } from "@/lib/api/server";
import { clientIpHeaders } from "@/lib/client-ip";
import { forbiddenOrigin, isSameSiteRequest } from "@/lib/origin";
import {
  CART_COOKIE,
  SESSION_COOKIE,
  cartCookieOptions,
} from "@/lib/session-cookies";

/** The one route the browser uses to reach the backend: /api/backend/api/v1/... It adds the
 * credentials from the httpOnly cookies and keeps both tokens out of browser JavaScript. */

const ALLOWED_PREFIX = /^api\/v1\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$/;
// Sign-in, registration and sign-out go through /api/auth/*, which set and clear the cookies.
const BLOCKED = new Set(["api/v1/auth/login", "api/v1/auth/register", "api/v1/auth/logout", "api/v1/auth/logout-all"]);
// Continue with Google goes only through /api/auth/google/*, which keep the flow token in an
// httpOnly cookie: the page must never start a flow (and read its flow_token) or finish one here.
// Checked on the decoded, lower-cased path, so "%67oogle" or "Google" cannot slip past.
const BLOCKED_PREFIX = /^api\/v1\/auth\/google(\/|$)/;

function decoded(path: string): string | null {
  try {
    return decodeURIComponent(path).toLowerCase();
  } catch {
    return null;
  }
}
const REQUEST_HEADERS = ["accept", "content-type", "idempotency-key", "x-order-phone"];
const RESPONSE_HEADERS = ["content-type", "content-disposition", "retry-after", "www-authenticate"];

function notFound(): NextResponse {
  return NextResponse.json(
    { error: { code: "not_found", message: "Not Found" } },
    { status: 404 },
  );
}

export function backendPath(segments: string[]): string | null {
  const path = segments.join("/");
  if (!ALLOWED_PREFIX.test(path)) return null;
  if (segments.some((s) => s === ".." || s === "." || s === "")) return null;
  if (BLOCKED.has(path.replace(/\/+$/, ""))) return null;
  const plain = decoded(path);
  if (plain === null || BLOCKED_PREFIX.test(plain)) return null;
  return path;
}

export async function proxyRequest(
  request: NextRequest,
  segments: string[],
  fetcher: typeof fetch = fetch,
): Promise<NextResponse> {
  const path = backendPath(segments);
  if (path === null) return notFound();
  if (!isSameSiteRequest(request)) return forbiddenOrigin();

  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // The backend limits some requests per client network: the shopper's address goes with a
  // signature for this exact method and path (ADR-006, 2026-11-13). The browser's own
  // X-Forwarded-For, and any X-Sixty-* header it sends, are never passed on (only the headers
  // listed above are copied).
  const method = request.method.toUpperCase();
  for (const [name, value] of Object.entries(clientIpHeaders(request, method, `/${path}`))) headers.set(name, value);
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  const cart = request.cookies.get(CART_COOKIE)?.value;
  if (session) headers.set("authorization", `Bearer ${session}`);
  if (cart) headers.set("x-cart-token", cart);

  const hasBody = !["GET", "HEAD"].includes(method);
  let upstream: Response;
  try {
    upstream = await fetcher(`${apiOrigin()}/${path}${request.nextUrl.search}`, {
      method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return NextResponse.json(
      { error: { code: "backend_unavailable", message: "The service is unavailable." } },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers({ "cache-control": "no-store" });
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  let body: BodyInit | null = upstream.status === 204 ? null : await upstream.arrayBuffer();
  let newCartToken: string | null = null;
  let cartGone = false;
  if (body && upstream.headers.get("content-type")?.includes("application/json")) {
    const json: unknown = JSON.parse(new TextDecoder().decode(body as ArrayBuffer));
    if (json && typeof json === "object" && !Array.isArray(json)) {
      const record = json as Record<string, unknown>;
      // The guest cart token is returned once, in the body of the request that created the
      // cart: keep it in the cookie and never hand it to the page.
      if (typeof record.cart_token === "string") newCartToken = record.cart_token;
      delete record.cart_token;
      delete record.session_token;
      delete record.flow_token; // never reaches the page, even from a route not blocked above
      const error = record.error as { code?: unknown } | undefined;
      cartGone = upstream.status === 404 && error?.code === "cart_not_found";
      body = JSON.stringify(record);
    }
  }

  const response = new NextResponse(body, { status: upstream.status, headers: responseHeaders });
  if (newCartToken) response.cookies.set(CART_COOKIE, newCartToken, cartCookieOptions());
  if (upstream.status === 401 && session) response.cookies.delete(SESSION_COOKIE);
  // The guest cart expired, or became an order at checkout: forget its token, so the next
  // request starts a new cart.
  if (cartGone && cart && !session) response.cookies.delete(CART_COOKIE);
  return response;
}
