import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { login, logout, logoutEverywhere, session } from "./auth-handlers";
import { backendPath, proxyRequest } from "./backend-proxy";
import { CART_COOKIE, SESSION_COOKIE } from "./session-cookies";

const SITE = "http://localhost:3000";

function request(path: string, init: { method?: string; origin?: string | null; cookies?: string; body?: string } = {}) {
  const headers = new Headers({ "content-type": "application/json" });
  if (init.origin !== null) headers.set("origin", init.origin ?? SITE);
  if (init.cookies) headers.set("cookie", init.cookies);
  return new NextRequest(`${SITE}${path}`, { method: init.method ?? "GET", headers, body: init.body });
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

beforeEach(() => {
  vi.stubEnv("API_URL", "http://api.test");
  vi.stubEnv("SITE_URL", SITE);
});
afterEach(() => vi.unstubAllEnvs());

describe("backendPath", () => {
  it("allows only /api/v1 paths", () => {
    expect(backendPath(["api", "v1", "cart"])).toBe("api/v1/cart");
    expect(backendPath(["admin"])).toBeNull();
    expect(backendPath(["api", "v1", "..", "health"])).toBeNull();
    expect(backendPath(["api", "v2", "cart"])).toBeNull();
  });
  it("keeps sign-in, registration and sign-out on the cookie-setting handlers", () => {
    expect(backendPath(["api", "v1", "auth", "login"])).toBeNull();
    expect(backendPath(["api", "v1", "auth", "register"])).toBeNull();
    expect(backendPath(["api", "v1", "auth", "logout"])).toBeNull();
    expect(backendPath(["api", "v1", "auth", "logout-all"])).toBeNull();
    expect(backendPath(["api", "v1", "auth", "me"])).toBe("api/v1/auth/me");
  });
  it("keeps every Continue with Google endpoint on /api/auth/google/*, however it is spelt", () => {
    for (const path of [
      "api/v1/auth/google/start",
      "api/v1/auth/google/callback",
      "api/v1/auth/google/link/start",
      "api/v1/auth/google/link/callback",
      "api/v1/auth/google",
      "api/v1/auth/google/start/",
      "api/v1/auth/Google/start",
      "api/v1/auth/%67oogle/start",
      "api/v1/auth/google%2Fstart",
      "api/v1/auth/google/%E0%A4%A", // not decodable: refused rather than guessed
    ]) {
      expect(backendPath(path.split("/")), path).toBeNull();
    }
    expect(backendPath(["api", "v1", "auth", "googlers"])).toBe("api/v1/auth/googlers");
  });
});

describe("the shopper's address (ADR-006 client IP, 2026-11-13)", () => {
  const SECRET = "test-only-client-ip-signing-secret-0123456789";

  async function proxied(headers: Record<string, string>) {
    const fetcher = vi.fn(async () => json({ ok: true }));
    const req = request("/api/backend/api/v1/cart/apply-code", { method: "POST", body: "{}" });
    for (const [name, value] of Object.entries(headers)) req.headers.set(name, value);
    await proxyRequest(req, ["api", "v1", "cart", "apply-code"], fetcher as unknown as typeof fetch);
    return new Headers((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].headers);
  }

  it("never passes on the browser's X-Forwarded-For or X-Sixty-* headers", async () => {
    const sent = await proxied({
      "x-forwarded-for": "198.18.0.1",
      "x-sixty-client-ip": "198.18.0.2",
      "x-sixty-client-ip-signature": "a".repeat(64),
      "x-sixty-client-ip-timestamp": "1700000000",
    });
    for (const name of ["x-forwarded-for", "x-sixty-client-ip", "x-sixty-client-ip-signature", "x-sixty-client-ip-timestamp"]) {
      expect(sent.get(name), name).toBeNull(); // not configured: nothing at all (local development)
    }
  });

  it("on Vercel, signs Vercel's address for this method and path, replacing anything the browser sent", async () => {
    vi.stubEnv("CLIENT_IP_SOURCE", "vercel");
    vi.stubEnv("CLIENT_IP_SIGNING_SECRET", SECRET);
    const sent = await proxied({
      "x-vercel-forwarded-for": "203.0.113.25",
      "x-forwarded-for": "198.18.0.1",
      "x-sixty-client-ip": "198.18.0.2",
    });
    expect(sent.get("x-forwarded-for")).toBeNull();
    expect(sent.get("x-sixty-client-ip")).toBe("203.0.113.25");
    const timestamp = sent.get("x-sixty-client-ip-timestamp")!;
    const { createHmac } = await import("node:crypto");
    const expected = createHmac("sha256", SECRET)
      .update(["sixty-client-ip-v1", timestamp, "203.0.113.25", "POST", "/api/v1/cart/apply-code"].join(String.fromCharCode(10)))
      .digest("hex");
    expect(sent.get("x-sixty-client-ip-signature")).toBe(expected);
  });
});

describe("Continue with Google through the proxy", () => {
  it("never reaches the backend for a Google endpoint", async () => {
    const fetcher = vi.fn();
    for (const path of ["start", "callback", "link/start", "link/callback"]) {
      const segments = ["api", "v1", "auth", "google", ...path.split("/")];
      const res = await proxyRequest(
        request(`/api/backend/${segments.join("/")}`, { method: "POST", cookies: `${SESSION_COOKIE}=sess` }),
        segments,
        fetcher as unknown as typeof fetch,
      );
      expect(res.status).toBe(404);
      expect(await res.text()).not.toContain("flow_token");
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("strips a flow token from any response, so it can never reach page scripts", async () => {
    const fetcher = vi.fn(async () => json({ authorization_url: "https://accounts.google.com/x", flow_token: "secret-flow", session_token: "s" }));
    const res = await proxyRequest(request("/api/backend/api/v1/cart"), ["api", "v1", "cart"], fetcher as unknown as typeof fetch);
    const text = await res.text();
    expect(text).not.toContain("secret-flow");
    expect(JSON.parse(text)).toEqual({ authorization_url: "https://accounts.google.com/x" });
  });
});

describe("proxyRequest", () => {
  it("adds the credentials from the cookies and ignores any sent by the page", async () => {
    const fetcher = vi.fn(async () => json({ ok: true }));
    const req = request("/api/backend/api/v1/cart?zone=gasabo", {
      cookies: `${SESSION_COOKIE}=sess; ${CART_COOKIE}=cart`,
    });
    req.headers.set("authorization", "Bearer forged");
    await proxyRequest(req, ["api", "v1", "cart"], fetcher as unknown as typeof fetch);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/api/v1/cart?zone=gasabo");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer sess");
    expect(headers.get("x-cart-token")).toBe("cart");
  });

  it("refuses a mutating request from another site, before calling the backend", async () => {
    const fetcher = vi.fn();
    for (const origin of ["https://evil.example", null]) {
      const res = await proxyRequest(
        request("/api/backend/api/v1/cart/items", { method: "POST", origin, body: "{}" }),
        ["api", "v1", "cart", "items"],
        fetcher as unknown as typeof fetch,
      );
      expect(res.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("moves a new guest cart token into an httpOnly cookie and out of the body", async () => {
    const fetcher = vi.fn(async () => json({ id: "c1", cart_token: "secret-token", lines: [] }));
    const res = await proxyRequest(
      request("/api/backend/api/v1/cart/items", { method: "POST", body: "{}" }),
      ["api", "v1", "cart", "items"],
      fetcher as unknown as typeof fetch,
    );
    expect(await res.json()).toEqual({ id: "c1", lines: [] });
    const cookie = res.cookies.get(CART_COOKIE);
    expect(cookie?.value).toBe("secret-token");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe("lax");
  });

  it("answers 404 for paths outside /api/v1 and clears a session the backend rejects", async () => {
    expect((await proxyRequest(request("/api/backend/x"), ["x"])).status).toBe(404);
    const fetcher = vi.fn(async () => json({ error: { code: "unauthorized" } }, 401));
    const res = await proxyRequest(
      request("/api/backend/api/v1/auth/me", { cookies: `${SESSION_COOKIE}=old` }),
      ["api", "v1", "auth", "me"],
      fetcher as unknown as typeof fetch,
    );
    expect(res.status).toBe(401);
    expect(res.cookies.get(SESSION_COOKIE)?.value).toBe("");
  });

  it("forgets a guest cart the backend no longer knows (expired, or ordered)", async () => {
    const gone = () => json({ error: { code: "cart_not_found" } }, 404);
    const guest = await proxyRequest(
      request("/api/backend/api/v1/cart", { cookies: `${CART_COOKIE}=old` }),
      ["api", "v1", "cart"],
      vi.fn(async () => gone()) as unknown as typeof fetch,
    );
    expect(guest.status).toBe(404);
    expect(guest.cookies.get(CART_COOKIE)?.value).toBe("");
    // A signed-in customer's request ignores the guest token, so the cookie is kept for merge.
    const customer = await proxyRequest(
      request("/api/backend/api/v1/cart", { cookies: `${SESSION_COOKIE}=s; ${CART_COOKIE}=old` }),
      ["api", "v1", "cart"],
      vi.fn(async () => gone()) as unknown as typeof fetch,
    );
    expect(customer.cookies.get(CART_COOKIE)).toBeUndefined();
    const otherNotFound = await proxyRequest(
      request("/api/backend/api/v1/cart/items/x", { method: "DELETE", cookies: `${CART_COOKIE}=old` }),
      ["api", "v1", "cart", "items", "x"],
      vi.fn(async () => json({ error: { code: "cart_item_not_found" } }, 404)) as unknown as typeof fetch,
    );
    expect(otherNotFound.cookies.get(CART_COOKIE)).toBeUndefined();
  });

  it("answers 502 when the backend cannot be reached", async () => {
    const fetcher = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const res = await proxyRequest(request("/api/backend/api/v1/cart"), ["api", "v1", "cart"], fetcher as unknown as typeof fetch);
    expect(res.status).toBe(502);
  });
});

describe("login and logout", () => {
  it("keeps the session token in a cookie, merges the guest cart and clears its cookie", async () => {
    const fetcher = vi.fn(async (url: string) =>
      url.endsWith("/auth/login")
        ? json({ user: { id: "u1" }, session_token: "tok", token_type: "bearer", expires_at: "2099-01-01T00:00:00Z" })
        : json({ cart: {}, merged_lines: 1 }),
    );
    const res = await login(
      request("/api/auth/login", { method: "POST", cookies: `${CART_COOKIE}=guest`, body: '{"identifier":"a","password":"b"}' }),
      fetcher as unknown as typeof fetch,
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ user: { id: "u1" } });
    expect(res.cookies.get(SESSION_COOKIE)?.value).toBe("tok");
    expect(res.cookies.get(SESSION_COOKIE)?.httpOnly).toBe(true);
    expect(res.cookies.get(CART_COOKIE)?.value).toBe("");
    const merge = fetcher.mock.calls[1] as unknown as [string, RequestInit];
    expect(merge[0]).toBe("http://api.test/api/v1/cart/merge");
    expect(new Headers(merge[1].headers).get("x-cart-token")).toBe("guest");
    expect(new Headers(merge[1].headers).get("authorization")).toBe("Bearer tok");
  });

  it("passes a refusal through without setting a cookie", async () => {
    const fetcher = vi.fn(async () => json({ error: { code: "invalid_credentials" } }, 401));
    const res = await login(request("/api/auth/login", { method: "POST", body: "{}" }), fetcher as unknown as typeof fetch);
    expect(res.status).toBe(401);
    expect(res.cookies.get(SESSION_COOKIE)).toBeUndefined();
  });

  it("refuses sign-in from another site", async () => {
    const fetcher = vi.fn();
    const res = await login(
      request("/api/auth/login", { method: "POST", origin: "https://evil.example", body: "{}" }),
      fetcher as unknown as typeof fetch,
    );
    expect(res.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("logs out at the backend and clears the session cookie", async () => {
    const fetcher = vi.fn(async () => json({ message: "ok" }));
    const res = await logout(
      request("/api/auth/logout", { method: "POST", cookies: `${SESSION_COOKIE}=tok` }),
      fetcher as unknown as typeof fetch,
    );
    expect(res.status).toBe(204);
    expect(res.cookies.get(SESSION_COOKIE)?.value).toBe("");
    expect(new Headers((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].headers).get("authorization")).toBe("Bearer tok");
  });

  it("logs out everywhere and clears the session cookie", async () => {
    const fetcher = vi.fn(async () => json({ message: "ok" }));
    const res = await logoutEverywhere(
      request("/api/auth/logout-all", { method: "POST", cookies: `${SESSION_COOKIE}=tok` }),
      fetcher as unknown as typeof fetch,
    );
    expect(res.status).toBe(204);
    expect(res.cookies.get(SESSION_COOKIE)?.value).toBe("");
    expect((fetcher.mock.calls[0] as unknown as [string])[0]).toBe("http://api.test/api/v1/auth/logout-all");
  });
});

describe("session", () => {
  it("answers a guest without calling the backend", async () => {
    const fetcher = vi.fn();
    const res = await session(request("/api/auth/session"), fetcher);
    expect(await res.json()).toEqual({ user: null });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("returns only the header's fields and marks customers", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      json({ id: "u", email: "a@b.rw", phone: "+250788000000", full_name: "Aline Uwase", is_staff: false, roles: ["customer"] }),
    );
    const res = await session(request("/api/auth/session", { cookies: `${SESSION_COOKIE}=tok` }), fetcher);
    expect(await res.json()).toEqual({ user: { full_name: "Aline Uwase", is_staff: false, is_customer: true } });
    expect(fetcher.mock.calls[0][1].headers.get("authorization")).toBe("Bearer tok");
  });

  it("does not treat staff as customers", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ full_name: "Sales", is_staff: true, roles: ["sales"] }));
    const res = await session(request("/api/auth/session", { cookies: `${SESSION_COOKIE}=tok` }), fetcher);
    expect((await res.json()).user).toMatchObject({ is_staff: true, is_customer: false });
  });

  it("clears an expired session cookie", async () => {
    const fetcher = vi.fn().mockResolvedValue(json({ error: { code: "unauthorized" } }, 401));
    const res = await session(request("/api/auth/session", { cookies: `${SESSION_COOKIE}=old` }), fetcher);
    expect(await res.json()).toEqual({ user: null });
    expect(res.headers.get("set-cookie")).toContain(`${SESSION_COOKIE}=;`);
  });
});
