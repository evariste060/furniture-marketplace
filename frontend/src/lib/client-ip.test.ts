import { createHmac } from "node:crypto";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clientIpConfig } from "./client-ip-config";
import { clientIpHeaders, clientIpMessage, vercelClientIp } from "./client-ip";

/** Signed client IPs (ADR-006, 2026-11-13): only Vercel's own headers are read, only when
 * configured, and the signature is the one the API verifies. */

const SECRET = "test-only-client-ip-signing-secret-0123456789";

function req(headers: Record<string, string>) {
  return new NextRequest("https://shop.test/api/backend/api/v1/cart", { headers });
}

afterEach(() => vi.unstubAllEnvs());

describe("clientIpConfig", () => {
  it("is off unless CLIENT_IP_SOURCE is set", () => {
    expect(clientIpConfig({})).toEqual({ source: "none" });
    expect(clientIpConfig({ CLIENT_IP_SOURCE: "" })).toEqual({ source: "none" });
  });

  it("needs a secret of at least 32 characters for Vercel, without echoing it", () => {
    expect(clientIpConfig({ CLIENT_IP_SOURCE: "vercel", CLIENT_IP_SIGNING_SECRET: SECRET })).toEqual({ source: "vercel", secret: SECRET });
    for (const secret of [undefined, "", "short-secret", ` ${SECRET}`]) {
      expect(() => clientIpConfig({ CLIENT_IP_SOURCE: "vercel", CLIENT_IP_SIGNING_SECRET: secret })).toThrow(/at least 32 characters/);
    }
    try {
      clientIpConfig({ CLIENT_IP_SOURCE: "vercel", CLIENT_IP_SIGNING_SECRET: "visible-but-too-short" });
    } catch (error) {
      expect(String(error)).not.toContain("visible-but-too-short");
    }
  });

  it("refuses any other source", () => {
    expect(() => clientIpConfig({ CLIENT_IP_SOURCE: "x-forwarded-for", CLIENT_IP_SIGNING_SECRET: SECRET })).toThrow(/unset or "vercel"/);
  });
});

describe("vercelClientIp", () => {
  it("reads Vercel's headers: x-vercel-forwarded-for first, then x-real-ip", () => {
    expect(vercelClientIp(req({ "x-vercel-forwarded-for": "203.0.113.25", "x-real-ip": "203.0.113.99" }))).toBe("203.0.113.25");
    expect(vercelClientIp(req({ "x-real-ip": "2001:db8::1" }))).toBe("2001:db8::1");
    expect(vercelClientIp(req({ "x-vercel-forwarded-for": "203.0.113.25, 10.0.0.1" }))).toBe("203.0.113.25");
  });

  it("never reads X-Forwarded-For or a browser's X-Sixty-Client-IP", () => {
    expect(vercelClientIp(req({ "x-forwarded-for": "203.0.113.25" }))).toBeNull();
    expect(vercelClientIp(req({ "x-sixty-client-ip": "203.0.113.25" }))).toBeNull();
  });

  it("gives null for anything that is not one address", () => {
    for (const value of ["not-an-ip", "203.0.113.256", "1".repeat(46)]) {
      expect(vercelClientIp(req({ "x-vercel-forwarded-for": value }))).toBeNull();
    }
  });
});

describe("clientIpHeaders", () => {
  it("adds nothing without CLIENT_IP_SOURCE (local development)", () => {
    vi.stubEnv("CLIENT_IP_SOURCE", "");
    expect(clientIpHeaders(req({ "x-vercel-forwarded-for": "203.0.113.25" }), "POST", "/api/v1/auth/login")).toEqual({});
  });

  it("signs the address, time, method and path the way the API checks them", () => {
    vi.stubEnv("CLIENT_IP_SOURCE", "vercel");
    vi.stubEnv("CLIENT_IP_SIGNING_SECRET", SECRET);
    const headers = clientIpHeaders(req({ "x-vercel-forwarded-for": "203.0.113.25" }), "post", "/api/v1/auth/login", 1_700_000_000_999);
    // The vector in backend/tests/unit/test_client_ip.py: both sides sign the same bytes.
    expect(clientIpMessage("1700000000", "203.0.113.25", "post", "/api/v1/auth/login")).toBe("sixty-client-ip-v1\n1700000000\n203.0.113.25\nPOST\n/api/v1/auth/login");
    expect(headers).toEqual({
      "x-sixty-client-ip": "203.0.113.25",
      "x-sixty-client-ip-timestamp": "1700000000",
      "x-sixty-client-ip-signature": "c7e7cc427d810262e6e6c05349b37d6d0320c23df2e918824f7528581b701280",
    });
    expect(headers["x-sixty-client-ip-signature"]).toBe(
      createHmac("sha256", SECRET).update("sixty-client-ip-v1\n1700000000\n203.0.113.25\nPOST\n/api/v1/auth/login").digest("hex"),
    );
  });

  it("adds nothing when Vercel gave no usable address", () => {
    vi.stubEnv("CLIENT_IP_SOURCE", "vercel");
    vi.stubEnv("CLIENT_IP_SIGNING_SECRET", SECRET);
    expect(clientIpHeaders(req({ "x-forwarded-for": "203.0.113.25" }), "POST", "/api/v1/auth/login")).toEqual({});
  });
});
