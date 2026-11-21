import "server-only";
import { NextResponse, type NextRequest } from "next/server";
import { routing, type Locale } from "@/i18n/routing";
import { apiOrigin } from "@/lib/api/server";
import { establishSession, forwardHeaders, unavailable } from "@/lib/auth-handlers";
import { safeReturnTo } from "@/lib/auth";
import { forbiddenOrigin, isSameSiteRequest, siteOrigin } from "@/lib/origin";
import {
  GOOGLE_FLOW_COOKIE,
  GOOGLE_FLOW_PATH,
  SESSION_COOKIE,
  googleFlowCookieOptions,
} from "@/lib/session-cookies";

/** Continue with Google (ADR-006 amendment 2026-11-11) through this app, the backend-for-frontend.
 *
 * 1. The page POSTs to /api/auth/google/start (or /link/start when signed in). The backend creates
 *    a single-use flow (state, nonce, PKCE verifier) and returns Google's authorization URL and a
 *    `flow_token` binding the flow to this browser. The token goes into an httpOnly cookie, never
 *    to the page; the page gets only the authorization URL, checked to be Google's.
 * 2. Google redirects the browser to GET /api/auth/google/callback?state=…&code=… (or error=…).
 *    The callback reads and always clears the cookie, forwards state, code or error and the flow
 *    token to the backend, and on success sets the usual session cookie (merging the guest cart)
 *    exactly as password sign-in does. It answers with a 303 to a clean page URL, so the code and
 *    state never stay in the address bar, history or a Referer.
 *
 * Errors reach the page only as a code from a fixed list, never the backend's message. Nothing
 * here logs codes, states or tokens. */

export const GOOGLE_AUTHORIZE_PREFIX = "https://accounts.google.com/";

type Purpose = "login" | "link";
type Page = "login" | "register";

/** What the flow cookie holds between start and callback: no Google credential, no session. */
export type GoogleFlow = {
  token: string;
  purpose: Purpose;
  page: Page;
  returnTo: string;
  locale: Locale;
  wishlist?: string;
};

/** The codes the login and register pages can explain (backend codes, plus three of this app's). */
export const LOGIN_ERRORS = [
  "google_state_invalid",
  "google_auth_cancelled",
  "google_auth_failed",
  "google_code_invalid",
  "google_token_invalid",
  "google_email_unverified",
  "google_email_invalid",
  "google_staff_not_allowed",
  "account_inactive",
  "google_account_exists",
  "rate_limited",
  "google_unavailable",
  "google_auth_unavailable",
  "login_unavailable",
] as const;
/** The profile page's codes: the same, plus the two linking conflicts. */
export const LINK_ERRORS = [...LOGIN_ERRORS, "google_account_in_use", "google_already_linked"] as const;
export type GoogleErrorCode = (typeof LINK_ERRORS)[number];

const FLOW_TOKEN = /^[A-Za-z0-9_-]{16,512}$/; // the backend's secrets.token_urlsafe
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATE_MAX = 512; // the backend's OAUTH_VALUE_MAX_LENGTH
const CODE_MAX = 2048; // OAUTH_CODE_MAX_LENGTH
const START_BODY_MAX = 2048;
const NO_STORE = { "cache-control": "no-store" };

function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (routing.locales as readonly string[]).includes(value);
}

/** A page path in the visitor's language: "/account" stays "/account" in English and becomes
 * "/rw/account" in Kinyarwanda (localePrefix "as-needed"). */
export function localized(path: string, locale: Locale): string {
  if (locale === routing.defaultLocale) return path;
  return path === "/" ? `/${locale}` : `/${locale}${path}`;
}

// ---- the flow cookie ---------------------------------------------------------------------------

export function encodeFlow(flow: GoogleFlow): string {
  return Buffer.from(JSON.stringify(flow), "utf8").toString("base64url");
}

/** The stored flow, or null when the cookie is missing, malformed or holds anything unexpected.
 * Each value is checked again, so a tampered cookie cannot redirect elsewhere or change purpose. */
export function decodeFlow(value: string | undefined): GoogleFlow | null {
  if (!value || value.length > 4096) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
  } catch {
    return null;
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.token !== "string" || !FLOW_TOKEN.test(r.token)) return null;
  if (r.purpose !== "login" && r.purpose !== "link") return null;
  if (r.page !== "login" && r.page !== "register") return null;
  // A non-empty path on this site, unchanged by safeReturnTo (which would turn "" into the fallback).
  if (typeof r.returnTo !== "string" || !r.returnTo || safeReturnTo(r.returnTo, "") !== r.returnTo) return null;
  if (!isLocale(r.locale)) return null;
  if (r.wishlist !== undefined && (typeof r.wishlist !== "string" || !UUID.test(r.wishlist))) return null;
  return {
    token: r.token,
    purpose: r.purpose,
    page: r.page,
    returnTo: r.returnTo,
    locale: r.locale,
    ...(r.wishlist ? { wishlist: r.wishlist } : {}),
  };
}

function clearFlow(response: NextResponse): void {
  response.cookies.delete({ name: GOOGLE_FLOW_COOKIE, path: GOOGLE_FLOW_PATH });
}

// ---- start -------------------------------------------------------------------------------------

type StartInput = { page: Page; returnTo: string; locale: Locale; wishlist?: string };

/** What the page may ask for: where to go afterwards, its language, and a product to save. */
async function startInput(request: NextRequest, fallback: string): Promise<StartInput> {
  const text = (await request.text().catch(() => "")).slice(0, START_BODY_MAX);
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = text ? JSON.parse(text) : {};
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) body = parsed as Record<string, unknown>;
  } catch {
    // An unreadable body starts a flow with the defaults.
  }
  const wishlist = typeof body.wishlist === "string" && UUID.test(body.wishlist) ? body.wishlist : undefined;
  return {
    page: body.page === "register" ? "register" : "login",
    returnTo: safeReturnTo(typeof body.returnTo === "string" ? body.returnTo : null, fallback),
    locale: isLocale(body.locale) ? body.locale : routing.defaultLocale,
    ...(wishlist ? { wishlist } : {}),
  };
}

/** Google's authorization endpoint and nothing else: the page navigates to whatever this returns. */
export function isGoogleAuthorizationUrl(value: unknown): value is string {
  if (typeof value !== "string" || !value.startsWith(GOOGLE_AUTHORIZE_PREFIX)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.host === "accounts.google.com" && !url.username && !url.password;
  } catch {
    return false;
  }
}

function errorJson(status: number, code: string, retryAfter?: string | null): NextResponse {
  const headers = new Headers(NO_STORE);
  if (retryAfter) headers.set("retry-after", retryAfter);
  return NextResponse.json({ error: { code } }, { status, headers });
}

async function startFlow(
  request: NextRequest,
  purpose: Purpose,
  fetcher: typeof fetch,
): Promise<NextResponse> {
  if (!isSameSiteRequest(request)) return forbiddenOrigin();
  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (purpose === "link" && !session) return errorJson(401, "token_missing");
  const input = await startInput(request, purpose === "link" ? "/account/profile" : "/account");

  const extra: Record<string, string> = session && purpose === "link" ? { authorization: `Bearer ${session}` } : {};
  let upstream: Response;
  try {
    const path = `/api/v1/auth/google/${purpose === "link" ? "link/start" : "start"}`;
    upstream = await fetcher(`${apiOrigin()}${path}`, {
      method: "POST",
      headers: forwardHeaders(request, "POST", path, extra),
      cache: "no-store",
    });
  } catch {
    return unavailable();
  }
  const body = (await upstream.json().catch(() => null)) as
    | { authorization_url?: unknown; flow_token?: unknown; expires_at?: unknown; error?: { code?: unknown } }
    | null;
  if (!upstream.ok) {
    const code = typeof body?.error?.code === "string" ? body.error.code : "google_auth_failed";
    const allowed = (LINK_ERRORS as readonly string[]).includes(code) || code === "token_missing" || code === "session_invalid";
    const response = errorJson(upstream.status, allowed ? code : "google_auth_failed", upstream.headers.get("retry-after"));
    if (upstream.status === 401 && session) response.cookies.delete(SESSION_COOKIE);
    return response;
  }
  if (
    !isGoogleAuthorizationUrl(body?.authorization_url) ||
    typeof body?.flow_token !== "string" ||
    !FLOW_TOKEN.test(body.flow_token) ||
    typeof body.expires_at !== "string" ||
    Number.isNaN(Date.parse(body.expires_at))
  ) {
    return errorJson(502, "google_unavailable");
  }

  const response = NextResponse.json({ authorization_url: body.authorization_url }, { headers: NO_STORE });
  const flow: GoogleFlow = { token: body.flow_token, purpose, ...input };
  response.cookies.set(GOOGLE_FLOW_COOKIE, encodeFlow(flow), googleFlowCookieOptions(body.expires_at));
  return response;
}

/** POST /api/auth/google/start: Continue with Google from the login or register page. */
export function googleStart(request: NextRequest, fetcher: typeof fetch = fetch) {
  return startFlow(request, "login", fetcher);
}

/** POST /api/auth/google/link/start: connect Google to the signed-in customer (Profile). */
export function googleLinkStart(request: NextRequest, fetcher: typeof fetch = fetch) {
  return startFlow(request, "link", fetcher);
}

// ---- callback ----------------------------------------------------------------------------------

function redirectTo(request: NextRequest, path: string): NextResponse {
  const response = NextResponse.redirect(new URL(path, siteOrigin(request)), 303);
  response.headers.set("cache-control", "no-store");
  response.headers.set("referrer-policy", "no-referrer");
  clearFlow(response);
  return response;
}

function withQuery(path: string, query: Record<string, string | undefined>): string {
  const url = new URL(path, "http://x");
  for (const [key, value] of Object.entries(query)) if (value) url.searchParams.set(key, value);
  return `${url.pathname}${url.search}`;
}

/** Where a failed attempt lands: the page it started from, with a code from the list and what is
 * needed to try again (returnTo and the product to save). */
function failurePath(flow: GoogleFlow | null, code: string): string {
  const purpose = flow?.purpose ?? "login";
  const allowed: readonly string[] = purpose === "link" ? LINK_ERRORS : LOGIN_ERRORS;
  const safe = allowed.includes(code) ? code : "google_auth_failed";
  const locale = flow?.locale ?? routing.defaultLocale;
  if (purpose === "link") return localized(withQuery("/account/profile", { google_error: safe }), locale);
  const page = flow?.page === "register" ? "/register" : "/login";
  return localized(
    withQuery(page, {
      google_error: safe,
      returnTo: flow && flow.returnTo !== "/account" ? flow.returnTo : undefined,
      wishlist: flow?.wishlist,
    }),
    locale,
  );
}

type CallbackBody = {
  session_token?: unknown;
  expires_at?: unknown;
  account_created?: unknown;
  error?: { code?: unknown };
};

/** GET /api/auth/google/callback: where Google sends the browser back. */
export async function googleCallback(request: NextRequest, fetcher: typeof fetch = fetch): Promise<NextResponse> {
  const flow = decodeFlow(request.cookies.get(GOOGLE_FLOW_COOKIE)?.value);
  const query = request.nextUrl.searchParams;
  const state = query.get("state");
  const code = query.get("code");
  const error = query.get("error");

  // Nothing to finish: no flow in this browser, no state, or not exactly one of code and error.
  // The backend would refuse it the same way; it is not called.
  if (!flow || !state || state.length > STATE_MAX) return redirectTo(request, failurePath(flow, "google_state_invalid"));
  if ((code === null) === (error === null) || (code !== null && (!code || code.length > CODE_MAX)) || (error !== null && (!error || error.length > STATE_MAX))) {
    return redirectTo(request, failurePath(flow, "google_auth_failed"));
  }

  const session = request.cookies.get(SESSION_COOKIE)?.value;
  if (flow.purpose === "link" && !session) {
    return redirectTo(request, localized(withQuery("/login", { returnTo: "/account/profile" }), flow.locale));
  }
  const payload = { state, flow_token: flow.token, ...(code !== null ? { code } : { error: error as string }) };
  const extra: Record<string, string> = flow.purpose === "link" ? { authorization: `Bearer ${session}` } : {};
  let upstream: Response;
  try {
    const path = `/api/v1/auth/google/${flow.purpose === "link" ? "link/callback" : "callback"}`;
    upstream = await fetcher(`${apiOrigin()}${path}`, {
      method: "POST",
      headers: forwardHeaders(request, "POST", path, extra),
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    return redirectTo(request, failurePath(flow, "google_unavailable"));
  }
  const body = (await upstream.json().catch(() => null)) as CallbackBody | null;

  if (!upstream.ok) {
    const failure = typeof body?.error?.code === "string" ? body.error.code : "google_auth_failed";
    if (flow.purpose === "link" && (failure === "session_invalid" || failure === "token_missing")) {
      // The session ended while the visitor was at Google: sign in again, then connect.
      const response = redirectTo(request, localized(withQuery("/login", { returnTo: "/account/profile" }), flow.locale));
      response.cookies.delete(SESSION_COOKIE);
      return response;
    }
    return redirectTo(request, failurePath(flow, failure));
  }

  if (flow.purpose === "link") {
    return redirectTo(request, localized(withQuery("/account/profile", { google: "linked" }), flow.locale));
  }

  if (typeof body?.session_token !== "string" || typeof body.expires_at !== "string") {
    return redirectTo(request, failurePath(flow, "google_auth_failed"));
  }
  // A new account sees a welcome note when it lands in the account area.
  const created = body.account_created === true && flow.returnTo.startsWith("/account");
  const target = localized(withQuery(flow.returnTo, { google: created ? "created" : undefined }), flow.locale);
  const response = redirectTo(request, target);
  await establishSession(request, response, body.session_token, body.expires_at, fetcher);
  if (flow.wishlist) {
    // The product the visitor hearted before signing in (as the login page does). Best effort.
    const wishlistPath = `/api/v1/customers/me/wishlist/${flow.wishlist}`;
    await fetcher(`${apiOrigin()}${wishlistPath}`, {
      method: "PUT",
      headers: forwardHeaders(request, "PUT", wishlistPath, { authorization: `Bearer ${body.session_token}` }),
      cache: "no-store",
    }).catch(() => undefined);
  }
  return response;
}
