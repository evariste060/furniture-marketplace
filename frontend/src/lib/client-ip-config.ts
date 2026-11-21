/** Client-IP signing settings (ADR-006, 2026-11-13), checked when the app is built and started
 * (next.config.ts) so a misconfigured deployment never runs. Server-only values: never prefix them
 * with NEXT_PUBLIC_.
 *
 * - CLIENT_IP_SOURCE: unset (local development: nothing is sent, the API uses its transport peer)
 *   or "vercel" (the shopper's address comes from the headers Vercel's edge sets, and every call
 *   to the API carries it with an HMAC signature).
 * - CLIENT_IP_SIGNING_SECRET: the secret the signature is made with, at least 32 characters; the
 *   API's CLIENT_IP_SIGNING_SECRET or CLIENT_IP_SIGNING_SECRET_NEXT. Use a different secret for
 *   Preview and Production. */

export const SECRET_MIN_LENGTH = 32;

export type ClientIpConfig = { source: "none" } | { source: "vercel"; secret: string };

export function clientIpConfig(env: Record<string, string | undefined> = process.env): ClientIpConfig {
  const source = (env.CLIENT_IP_SOURCE ?? "").trim();
  if (source === "") return { source: "none" };
  if (source !== "vercel") throw new Error('CLIENT_IP_SOURCE must be unset or "vercel"');
  const secret = env.CLIENT_IP_SIGNING_SECRET ?? "";
  if (secret.length < SECRET_MIN_LENGTH || secret !== secret.trim()) {
    // Never the value itself.
    throw new Error(`CLIENT_IP_SOURCE=vercel requires CLIENT_IP_SIGNING_SECRET of at least ${SECRET_MIN_LENGTH} characters`);
  }
  return { source: "vercel", secret };
}
