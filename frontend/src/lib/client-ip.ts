import "server-only";
import { createHmac } from "node:crypto";
import { isIP } from "node:net";
import type { NextRequest } from "next/server";
import { clientIpConfig } from "@/lib/client-ip-config";

/** The shopper's address for the API's rate limits and audit records (ADR-006, 2026-11-13).
 *
 * Every call this app makes to the API comes from this server, so the API's transport peer is
 * this server (or its host's load balancer), never the shopper. With CLIENT_IP_SOURCE=vercel this
 * module reads the shopper's address from the headers Vercel's edge sets (it overwrites any value a
 * browser sends, to prevent spoofing) and signs it, with a timestamp and the exact method and path
 * of the API call, with HMAC-SHA256. The API accepts the address only with a valid, fresh
 * signature (backend/app/core/request_context.py builds the same message).
 *
 * The X-Forwarded-For a browser could send is never passed on, and any X-Sixty-* header in the
 * browser's request is ignored: only these generated headers reach the API. Without
 * CLIENT_IP_SOURCE (local development) nothing is added. */

export const CLIENT_IP_HEADER = "x-sixty-client-ip";
export const CLIENT_IP_SIGNATURE_HEADER = "x-sixty-client-ip-signature";
export const CLIENT_IP_TIMESTAMP_HEADER = "x-sixty-client-ip-timestamp";
const VERSION = "sixty-client-ip-v1";

/** The shopper's address from Vercel's own headers: x-vercel-forwarded-for first (Vercel notes
 * that x-forwarded-for can be replaced by a proxy in front of it), then x-real-ip. One address
 * only; anything else gives null. */
export function vercelClientIp(request: Pick<NextRequest, "headers">): string | null {
  for (const name of ["x-vercel-forwarded-for", "x-real-ip"]) {
    const value = request.headers.get(name);
    if (!value) continue;
    const first = value.split(",")[0]!.trim();
    return first.length <= 45 && isIP(first) ? first : null;
  }
  return null;
}

export function clientIpMessage(timestamp: string, ip: string, method: string, path: string): string {
  return [VERSION, timestamp, ip, method.toUpperCase(), path].join("\n");
}

/** The signed headers for one API call (`path` as the API sees it: "/api/v1/auth/login", no
 * query), or none when not configured or no usable address is known. */
export function clientIpHeaders(
  request: Pick<NextRequest, "headers">,
  method: string,
  path: string,
  now: number = Date.now(),
): Record<string, string> {
  const config = clientIpConfig();
  if (config.source !== "vercel") return {};
  const ip = vercelClientIp(request);
  if (!ip) return {};
  const timestamp = String(Math.floor(now / 1000));
  const signature = createHmac("sha256", config.secret).update(clientIpMessage(timestamp, ip, method, path)).digest("hex");
  return { [CLIENT_IP_HEADER]: ip, [CLIENT_IP_SIGNATURE_HEADER]: signature, [CLIENT_IP_TIMESTAMP_HEADER]: timestamp };
}
