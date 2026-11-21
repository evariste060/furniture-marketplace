import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { login, register } from "./auth-handlers";
import {
  decodeFlow,
  encodeFlow,
  googleCallback,
  googleLinkStart,
  googleStart,
  isGoogleAuthorizationUrl,
  localized,
  type GoogleFlow,
} from "./google-auth-handlers";
import { CART_COOKIE, GOOGLE_FLOW_COOKIE, SESSION_COOKIE } from "./session-cookies";

/** Continue with Google through this app's route handlers, with the backend replaced by a fake
 * fetcher: the flow token stays in its httpOnly cookie, the page gets only Google's URL, and the
 * callback always clears the flow and lands on a clean page with a code from the list. */

const SITE = "http://localhost:3000";
const API = "http://api.test";
const AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=s";
const FLOW_TOKEN = "f".repeat(43);
const WISH = "0b7c6f1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b";

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

function post(path: string, body?: unknown, init: { origin?: string | null; cookies?: string } = {}) {
  const headers = new Headers({ "content-type": "application/json", "x-forwarded-for": "203.0.113.7" });
  if (init.origin !== null) headers.set("origin", init.origin ?? SITE);
  if (init.cookies) headers.set("cookie", init.cookies);
  return new NextRequest(`${SITE}${path}`, { method: "POST", headers, body: body === undefined ? undefined : JSON.stringify(body) });
}

function callback(query: Record<string, string>, cookies?: string) {
  const headers = new Headers({ "x-forwarded-for": "203.0.113.7" });
  if (cookies) headers.set("cookie", cookies);
  return new NextRequest(`${SITE}/api/auth/google/callback?${new URLSearchParams(query)}`, { headers });
}

function flow(overrides: Partial<GoogleFlow> = {}): GoogleFlow {
  return { token: FLOW_TOKEN, purpose: "login", page: "login", returnTo: "/account", locale: "en", ...overrides };
}

function flowCookie(value: GoogleFlow | string = flow()) {
  return `${GOOGLE_FLOW_COOKIE}=${typeof value === "string" ? value : encodeFlow(value)}`;
}

function inSeconds(seconds: number) {
  return new Date(Date.now() + seconds * 1000).toISOString();
}

function started(overrides: Record<string, unknown> = {}) {
  return json({ authorization_url: AUTH_URL, flow_token: FLOW_TOKEN, expires_at: inSeconds(600), ...overrides });
}

type Call = [string, RequestInit];
const calls = (fetcher: ReturnType<typeof vi.fn>) => fetcher.mock.calls as unknown as Call[];

/** The redirect's target, relative to the site. */
function location(res: Response): string {
  const value = res.headers.get("location");
  expect(value).toBeTruthy();
  const url = new URL(value!);
  expect(url.origin).toBe(SITE);
  return `${url.pathname}${url.search}`;
}

/** Every callback answer: a 303 that cannot be cached or leak the URL, and the flow cleared. */
function expectCleanRedirect(res: Response) {
  expect(res.status).toBe(303);
  expect(res.headers.get("cache-control")).toBe("no-store");
  expect(res.headers.get("referrer-policy")).toBe("no-referrer");
  const cleared = res.headers.getSetCookie().find((c) => c.startsWith(`${GOOGLE_FLOW_COOKIE}=`));
  expect(cleared).toBeDefined();
  expect(cleared).toMatch(/Path=\/api\/auth\/google/);
  expect(cleared).toMatch(/Expires=Thu, 01 Jan 1970|Max-Age=0/);
}

beforeEach(() => {
  vi.stubEnv("API_URL", API);
  vi.stubEnv("SITE_URL", SITE);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ---- start -------------------------------------------------------------------------------------

describe("googleStart", () => {
  it("starts a flow, keeps the flow token in the cookie and returns only Google's URL", async () => {
    const fetcher = vi.fn(async () => started());
    const res = await googleStart(
      post("/api/auth/google/start", { page: "register", returnTo: "/cart", locale: "rw", wishlist: WISH }),
      fetcher as unknown as typeof fetch,
    );
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(JSON.parse(text)).toEqual({ authorization_url: AUTH_URL });
    expect(text).not.toContain(FLOW_TOKEN);
    expect(res.headers.get("cache-control")).toBe("no-store");

    const [url, init] = calls(fetcher)[0];
    expect(url).toBe(`${API}/api/v1/auth/google/start`);
    expect(init.method).toBe("POST");
    const headers = new Headers(init.headers);
    // The browser's X-Forwarded-For is never passed on (ADR-006 client IP, 2026-11-13).
    expect(headers.get("x-forwarded-for")).toBeNull();
    expect(headers.get("authorization")).toBeNull();

    const cookie = res.cookies.get(GOOGLE_FLOW_COOKIE)!;
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: "lax", path: "/api/auth/google", secure: false });
    expect(cookie.maxAge).toBeGreaterThanOrEqual(598);
    expect(cookie.maxAge).toBeLessThanOrEqual(600);
    expect(decodeFlow(cookie.value)).toEqual({ token: FLOW_TOKEN, purpose: "login", page: "register", returnTo: "/cart", locale: "rw", wishlist: WISH });
    expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });

  it("stores only safe values: another site, an unknown language or a bad product id fall back", async () => {
    const fetcher = vi.fn(async () => started());
    const res = await googleStart(
      post("/api/auth/google/start", { returnTo: "//evil.example/x", locale: "fr", wishlist: "../../admin", page: "admin" }),
      fetcher as unknown as typeof fetch,
    );
    expect(decodeFlow(res.cookies.get(GOOGLE_FLOW_COOKIE)!.value)).toEqual({
      token: FLOW_TOKEN,
      purpose: "login",
      page: "login",
      returnTo: "/account",
      locale: "en",
    });
  });

  it("starts with the defaults when the page sends no or an unreadable body", async () => {
    const fetcher = vi.fn(async () => started());
    const req = new NextRequest(`${SITE}/api/auth/google/start`, { method: "POST", headers: { origin: SITE }, body: "{not json" });
    const res = await googleStart(req, fetcher as unknown as typeof fetch);
    expect(res.status).toBe(200);
    expect(decodeFlow(res.cookies.get(GOOGLE_FLOW_COOKIE)!.value)?.returnTo).toBe("/account");
  });

  it("refuses a start from another site before calling the backend", async () => {
    const fetcher = vi.fn();
    for (const origin of ["https://evil.example", null]) {
      const res = await googleStart(post("/api/auth/google/start", {}, { origin }), fetcher as unknown as typeof fetch);
      expect(res.status).toBe(403);
      expect(res.cookies.get(GOOGLE_FLOW_COOKIE)).toBeUndefined();
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    "https://accounts.google.com.evil.example/o/oauth2/v2/auth",
    "http://accounts.google.com/o/oauth2/v2/auth",
    "https://evil.example/?next=https://accounts.google.com/",
    "https://user:pass@accounts.google.com/o/oauth2/v2/auth",
    "javascript:alert(1)",
    "",
  ])("refuses an authorization URL that is not Google's (%s) and sets no cookie", async (authorizationUrl) => {
    const fetcher = vi.fn(async () => started({ authorization_url: authorizationUrl }));
    const res = await googleStart(post("/api/auth/google/start", {}), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: { code: "google_unavailable" } });
    expect(res.cookies.get(GOOGLE_FLOW_COOKIE)).toBeUndefined();
  });

  it("refuses a start answer without a usable flow token or expiry", async () => {
    for (const overrides of [{ flow_token: undefined }, { flow_token: "short" }, { flow_token: "x;y".repeat(10) }, { expires_at: "soon" }]) {
      const fetcher = vi.fn(async () => started(overrides));
      const res = await googleStart(post("/api/auth/google/start", {}), fetcher as unknown as typeof fetch);
      expect(res.status).toBe(502);
      expect(res.cookies.get(GOOGLE_FLOW_COOKIE)).toBeUndefined();
    }
  });

  it("passes on the backend's code and Retry-After, never its message", async () => {
    const fetcher = vi.fn(async () => json({ error: { code: "rate_limited", message: "internal detail" } }, 429, { "retry-after": "120" }));
    const res = await googleStart(post("/api/auth/google/start", {}), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(429);
    expect(res.headers.get("retry-after")).toBe("120");
    expect(await res.json()).toEqual({ error: { code: "rate_limited" } });
  });

  it("reports an unknown backend code as a failed attempt, and an unreachable backend as 502", async () => {
    const odd = vi.fn(async () => json({ error: { code: "sqlalchemy_exploded", message: "trace" } }, 500));
    const res = await googleStart(post("/api/auth/google/start", {}), odd as unknown as typeof fetch);
    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ error: { code: "google_auth_failed" } });

    const down = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const res2 = await googleStart(post("/api/auth/google/start", {}), down as unknown as typeof fetch);
    expect(res2.status).toBe(502);
    expect((await res2.json()).error.code).toBe("backend_unavailable");
  });

  it("marks the flow cookie Secure in production and never lets it outlive 30 minutes", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const fetcher = vi.fn(async () => started({ expires_at: inSeconds(7200) }));
    const res = await googleStart(post("/api/auth/google/start", {}), fetcher as unknown as typeof fetch);
    const cookie = res.cookies.get(GOOGLE_FLOW_COOKIE)!;
    expect(cookie.secure).toBe(true);
    expect(cookie.maxAge).toBe(1800);
  });
});

describe("googleLinkStart", () => {
  it("needs the session cookie and does not call the backend without one", async () => {
    const fetcher = vi.fn();
    const res = await googleLinkStart(post("/api/auth/google/link/start", {}), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(401);
    expect((await res.json()).error.code).toBe("token_missing");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("starts a link flow with the session's bearer token and returns only Google's URL", async () => {
    const fetcher = vi.fn(async () => started());
    const res = await googleLinkStart(
      post("/api/auth/google/link/start", { locale: "rw", returnTo: "/account/profile" }, { cookies: `${SESSION_COOKIE}=sess` }),
      fetcher as unknown as typeof fetch,
    );
    expect(await res.json()).toEqual({ authorization_url: AUTH_URL });
    const [url, init] = calls(fetcher)[0];
    expect(url).toBe(`${API}/api/v1/auth/google/link/start`);
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer sess");
    expect(decodeFlow(res.cookies.get(GOOGLE_FLOW_COOKIE)!.value)).toMatchObject({ purpose: "link", returnTo: "/account/profile", locale: "rw" });
  });

  it("refuses another site, passes on already-linked, and forgets an expired session", async () => {
    const never = vi.fn();
    const forged = await googleLinkStart(
      post("/api/auth/google/link/start", {}, { origin: "https://evil.example", cookies: `${SESSION_COOKIE}=sess` }),
      never as unknown as typeof fetch,
    );
    expect(forged.status).toBe(403);
    expect(never).not.toHaveBeenCalled();

    const linked = vi.fn(async () => json({ error: { code: "google_already_linked", message: "x" } }, 409));
    const res = await googleLinkStart(post("/api/auth/google/link/start", {}, { cookies: `${SESSION_COOKIE}=sess` }), linked as unknown as typeof fetch);
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: { code: "google_already_linked" } });

    const expired = vi.fn(async () => json({ error: { code: "session_invalid", message: "x" } }, 401));
    const res2 = await googleLinkStart(post("/api/auth/google/link/start", {}, { cookies: `${SESSION_COOKIE}=sess` }), expired as unknown as typeof fetch);
    expect(res2.status).toBe(401);
    expect(res2.headers.getSetCookie().some((c) => c.startsWith(`${SESSION_COOKIE}=;`))).toBe(true);
  });
});

// ---- callback ----------------------------------------------------------------------------------

function signedIn(overrides: Record<string, unknown> = {}) {
  return json({
    user: { id: "u1", is_staff: false, roles: ["customer"] },
    session_token: "new-session",
    token_type: "bearer",
    expires_at: inSeconds(7 * 24 * 3600),
    account_created: false,
    ...overrides,
  });
}

describe("googleCallback", () => {
  it("without a flow cookie in this browser: refused without calling the backend", async () => {
    const fetcher = vi.fn();
    const res = await googleCallback(callback({ state: "s", code: "c" }), fetcher as unknown as typeof fetch);
    expectCleanRedirect(res);
    expect(location(res)).toBe("/login?google_error=google_state_invalid");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    ["not base64 json", "%%%"],
    ["another site to return to", encodeFlow({ ...flow(), returnTo: "//evil.example" })],
    ["an empty return path", encodeFlow({ ...flow(), returnTo: "" })],
    ["an unknown purpose", encodeFlow({ ...flow(), purpose: "admin" as never })],
    ["an unknown language", encodeFlow({ ...flow(), locale: "fr" as never })],
    ["a malformed flow token", encodeFlow({ ...flow(), token: "a b" })],
    ["a bad product id", encodeFlow({ ...flow(), wishlist: "x" })],
  ])("a tampered flow cookie (%s) is refused without calling the backend", async (_, value) => {
    const fetcher = vi.fn();
    const res = await googleCallback(callback({ state: "s", code: "c" }, flowCookie(value)), fetcher as unknown as typeof fetch);
    expectCleanRedirect(res);
    expect(location(res)).toBe("/login?google_error=google_state_invalid");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("refuses a missing state, or not exactly one of code and error, without calling the backend", async () => {
    const fetcher = vi.fn();
    const cases: [Record<string, string>, string][] = [
      [{ code: "c" }, "google_state_invalid"],
      [{ state: "s" }, "google_auth_failed"],
      [{ state: "s", code: "c", error: "access_denied" }, "google_auth_failed"],
      [{ state: "s".repeat(513), code: "c" }, "google_state_invalid"],
      [{ state: "s", code: "c".repeat(2049) }, "google_auth_failed"],
    ];
    for (const [query, code] of cases) {
      const res = await googleCallback(callback(query, flowCookie()), fetcher as unknown as typeof fetch);
      expectCleanRedirect(res);
      expect(location(res)).toBe(`/login?google_error=${code}`);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("signs in: sends exactly state, code and the flow token, sets the session cookie and merges the cart", async () => {
    const fetcher = vi.fn(async (url: string) => (url.endsWith("/auth/google/callback") ? signedIn() : json({}, 200)));
    const cookies = `${flowCookie(flow({ returnTo: "/cart?step=2", locale: "rw" }))}; ${CART_COOKIE}=guest-cart`;
    const res = await googleCallback(callback({ state: "the-state", code: "the-code", scope: "openid" }, cookies), fetcher as unknown as typeof fetch);

    expectCleanRedirect(res);
    expect(location(res)).toBe("/rw/cart?step=2");
    const [url, init] = calls(fetcher)[0];
    expect(url).toBe(`${API}/api/v1/auth/google/callback`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ state: "the-state", flow_token: FLOW_TOKEN, code: "the-code" });
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBeNull();
    // The browser's X-Forwarded-For is never passed on (ADR-006 client IP, 2026-11-13).
    expect(headers.get("x-forwarded-for")).toBeNull();

    expect(res.cookies.get(SESSION_COOKIE)).toMatchObject({ value: "new-session", httpOnly: true, sameSite: "lax", path: "/" });
    const [mergeUrl, mergeInit] = calls(fetcher)[1];
    expect(mergeUrl).toBe(`${API}/api/v1/cart/merge`);
    expect(new Headers(mergeInit.headers).get("authorization")).toBe("Bearer new-session");
    expect(new Headers(mergeInit.headers).get("x-cart-token")).toBe("guest-cart");
    expect(res.headers.getSetCookie().some((c) => c.startsWith(`${CART_COOKIE}=;`))).toBe(true);
    // Nothing secret in the redirect.
    expect(res.headers.get("location")).not.toMatch(/the-code|the-state|new-session|f{43}/);
  });

  it("saves the hearted product after signing in, and still signs in when that fails", async () => {
    const fetcher = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/google/callback")) return signedIn();
      throw new Error("wishlist down");
    });
    const res = await googleCallback(callback({ state: "s", code: "c" }, flowCookie(flow({ wishlist: WISH }))), fetcher as unknown as typeof fetch);
    expect(location(res)).toBe("/account");
    expect(res.cookies.get(SESSION_COOKIE)?.value).toBe("new-session");
    const [url, init] = calls(fetcher)[1];
    expect(url).toBe(`${API}/api/v1/customers/me/wishlist/${WISH}`);
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer new-session");
  });

  it("welcomes a new account in the account area only", async () => {
    const fetcher = vi.fn(async () => signedIn({ account_created: true }));
    const res = await googleCallback(callback({ state: "s", code: "c" }, flowCookie()), fetcher as unknown as typeof fetch);
    expect(location(res)).toBe("/account?google=created");
    const res2 = await googleCallback(callback({ state: "s", code: "c" }, flowCookie(flow({ returnTo: "/checkout" }))), fetcher as unknown as typeof fetch);
    expect(location(res2)).toBe("/checkout");
  });

  it("forwards a cancellation at Google and explains it on the page the visitor came from", async () => {
    const fetcher = vi.fn(async () => json({ error: { code: "google_auth_cancelled", message: "cancelled" } }, 422));
    const res = await googleCallback(
      callback({ state: "s", error: "access_denied" }, flowCookie(flow({ page: "register", returnTo: "/cart", wishlist: WISH }))),
      fetcher as unknown as typeof fetch,
    );
    expect(JSON.parse(calls(fetcher)[0][1].body as string)).toEqual({ state: "s", flow_token: FLOW_TOKEN, error: "access_denied" });
    expectCleanRedirect(res);
    expect(location(res)).toBe(`/register?google_error=google_auth_cancelled&returnTo=%2Fcart&wishlist=${WISH}`);
    expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });

  it.each([
    "google_state_invalid",
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
  ])("passes on the sign-in code %s, without the backend's message or a session", async (code) => {
    const fetcher = vi.fn(async () => json({ error: { code, message: "Secret internal detail" } }, 409));
    const res = await googleCallback(callback({ state: "s", code: "c" }, flowCookie(flow({ locale: "rw" }))), fetcher as unknown as typeof fetch);
    expectCleanRedirect(res);
    expect(location(res)).toBe(`/rw/login?google_error=${code}`);
    expect(res.headers.get("location")).not.toMatch(/Secret/);
    expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });

  it("reports unknown codes, linking codes on a sign-in, bodies without a code and outages safely", async () => {
    const cases: [() => Promise<Response>, string][] = [
      [async () => json({ error: { code: "psycopg_operational_error" } }, 500), "google_auth_failed"],
      [async () => json({ error: { code: "google_account_in_use" } }, 409), "google_auth_failed"],
      [async () => new Response("<html>bad gateway</html>", { status: 502 }), "google_auth_failed"],
      [async () => json({ user: {} }), "google_auth_failed"], // 200 without a session
      [
        async () => {
          throw new Error("ECONNREFUSED");
        },
        "google_unavailable",
      ],
    ];
    for (const [answer, code] of cases) {
      const fetcher = vi.fn(answer);
      const res = await googleCallback(callback({ state: "s", code: "c" }, flowCookie()), fetcher as unknown as typeof fetch);
      expectCleanRedirect(res);
      expect(location(res)).toBe(`/login?google_error=${code}`);
      expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
    }
  });

  it("links Google for the signed-in customer without creating a session", async () => {
    const fetcher = vi.fn(async () => json({ provider: "google", email: "shopper@gmail.com", linked_at: "2026-11-12T08:00:00Z" }));
    const cookies = `${flowCookie(flow({ purpose: "link", returnTo: "/account/profile", locale: "rw" }))}; ${SESSION_COOKIE}=sess; ${CART_COOKIE}=cart`;
    const res = await googleCallback(callback({ state: "s", code: "c" }, cookies), fetcher as unknown as typeof fetch);
    expectCleanRedirect(res);
    expect(location(res)).toBe("/rw/account/profile?google=linked");
    expect(fetcher).toHaveBeenCalledTimes(1); // no cart merge, no wishlist
    const [url, init] = calls(fetcher)[0];
    expect(url).toBe(`${API}/api/v1/auth/google/link/callback`);
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer sess");
    expect(JSON.parse(init.body as string)).toEqual({ state: "s", flow_token: FLOW_TOKEN, code: "c" });
    expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
    expect(res.cookies.get(CART_COOKIE)).toBeUndefined();
  });

  it("explains linking conflicts on the profile page", async () => {
    for (const code of ["google_account_in_use", "google_already_linked", "google_auth_cancelled", "google_state_invalid"]) {
      const fetcher = vi.fn(async () => json({ error: { code, message: "x" } }, 409));
      const res = await googleCallback(
        callback({ state: "s", code: "c" }, `${flowCookie(flow({ purpose: "link" }))}; ${SESSION_COOKIE}=sess`),
        fetcher as unknown as typeof fetch,
      );
      expectCleanRedirect(res);
      expect(location(res)).toBe(`/account/profile?google_error=${code}`);
    }
  });

  it("sends a link callback without a session, or whose session ended, to sign in again", async () => {
    const never = vi.fn();
    const res = await googleCallback(callback({ state: "s", code: "c" }, flowCookie(flow({ purpose: "link" }))), never as unknown as typeof fetch);
    expectCleanRedirect(res);
    expect(location(res)).toBe("/login?returnTo=%2Faccount%2Fprofile");
    expect(never).not.toHaveBeenCalled();

    const ended = vi.fn(async () => json({ error: { code: "session_invalid", message: "x" } }, 401));
    const res2 = await googleCallback(
      callback({ state: "s", code: "c" }, `${flowCookie(flow({ purpose: "link" }))}; ${SESSION_COOKIE}=old`),
      ended as unknown as typeof fetch,
    );
    expectCleanRedirect(res2);
    expect(location(res2)).toBe("/login?returnTo=%2Faccount%2Fprofile");
    expect(res2.headers.getSetCookie().some((c) => c.startsWith(`${SESSION_COOKIE}=;`))).toBe(true);
  });

  it("a Google code error on a link (401) keeps the session", async () => {
    const fetcher = vi.fn(async () => json({ error: { code: "google_code_invalid", message: "x" } }, 401));
    const res = await googleCallback(
      callback({ state: "s", code: "c" }, `${flowCookie(flow({ purpose: "link" }))}; ${SESSION_COOKIE}=sess`),
      fetcher as unknown as typeof fetch,
    );
    expect(location(res)).toBe("/account/profile?google_error=google_code_invalid");
    expect(res.headers.getSetCookie().some((c) => c.startsWith(`${SESSION_COOKIE}=`))).toBe(false);
  });

  it("logs nothing: no code, state, flow token or session reaches the console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => undefined));
    const fetcher = vi.fn(async () => signedIn());
    await googleCallback(callback({ state: "s", code: "c" }, flowCookie()), fetcher as unknown as typeof fetch);
    await googleStart(post("/api/auth/google/start", {}), vi.fn(async () => started()) as unknown as typeof fetch);
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});

describe("helpers", () => {
  it("accepts only Google's authorization endpoint", () => {
    expect(isGoogleAuthorizationUrl(AUTH_URL)).toBe(true);
    expect(isGoogleAuthorizationUrl("https://accounts.google.com.evil.example/")).toBe(false);
    expect(isGoogleAuthorizationUrl(42)).toBe(false);
  });

  it("puts the language prefix on page paths as next-intl does", () => {
    expect(localized("/account", "en")).toBe("/account");
    expect(localized("/account", "rw")).toBe("/rw/account");
    expect(localized("/", "rw")).toBe("/rw");
  });

  it("round-trips a flow and rejects an oversized cookie", () => {
    expect(decodeFlow(encodeFlow(flow({ wishlist: WISH })))).toEqual(flow({ wishlist: WISH }));
    expect(decodeFlow("a".repeat(5000))).toBeNull();
    expect(decodeFlow(encodeFlow(flow({ returnTo: "" })))).toBeNull();
    expect(decodeFlow(encodeFlow(flow({ returnTo: "/cart?step=2" })))?.returnTo).toBe("/cart?step=2");
    expect(decodeFlow(undefined)).toBeNull();
  });
});

describe("registration waiting for email verification (2026-11-12)", () => {
  it("returns the user and the flag only, sets no session and keeps the guest cart for sign-in", async () => {
    const fetcher = vi.fn(async () =>
      json(
        { user: { id: "u1", email: "a@b.rw" }, session_token: null, token_type: null, expires_at: null, verification_required: true },
        201,
      ),
    );
    const res = await register(post("/api/auth/register", { email: "a@b.rw", full_name: "A B", password: "x" }, { cookies: `${CART_COOKIE}=cart` }), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ user: { id: "u1", email: "a@b.rw" }, verification_required: true });
    expect(res.headers.getSetCookie()).toEqual([]); // no session cookie, cart cookie untouched
    expect(fetcher).toHaveBeenCalledTimes(1); // no cart merge without a session
  });

  it("still signs in a phone-only registration", async () => {
    const fetcher = vi.fn(async (url: string) =>
      url.endsWith("/auth/register") ? json({ user: { id: "u2" }, session_token: "tok", expires_at: inSeconds(3600), verification_required: false }, 201) : json({}),
    );
    const res = await register(post("/api/auth/register", { phone: "0788000111", full_name: "A B", password: "x" }), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(201);
    expect(res.cookies.get(SESSION_COOKIE)?.value).toBe("tok");
  });

  it("passes on email_verification_unavailable", async () => {
    const fetcher = vi.fn(async () => json({ error: { code: "email_verification_unavailable", message: "x" } }, 503));
    const res = await register(post("/api/auth/register", { email: "a@b.rw" }), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(503);
    expect((await res.json()).error.code).toBe("email_verification_unavailable");
    expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });
});

describe("password sign-in after the refactor", () => {
  it("still sets the session cookie, merges the guest cart and clears its cookie", async () => {
    const fetcher = vi.fn(async (url: string) =>
      url.endsWith("/auth/login") ? json({ user: { id: "u1" }, session_token: "tok", expires_at: inSeconds(3600) }) : json({}),
    );
    const res = await login(post("/api/auth/login", { identifier: "a@b.rw", password: "x" }, { cookies: `${CART_COOKIE}=cart` }), fetcher as unknown as typeof fetch);
    expect(await res.json()).toEqual({ user: { id: "u1" } });
    expect(res.cookies.get(SESSION_COOKIE)).toMatchObject({ value: "tok", httpOnly: true, path: "/" });
    expect(calls(fetcher)[1][0]).toBe(`${API}/api/v1/cart/merge`);
    expect(res.headers.getSetCookie().some((c) => c.startsWith(`${CART_COOKIE}=;`))).toBe(true);
  });
});
