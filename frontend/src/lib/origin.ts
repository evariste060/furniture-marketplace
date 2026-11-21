import { NextResponse } from "next/server";

/** Mutating requests to this app's API route handlers must come from this site (CSRF defence,
 * together with SameSite=Lax cookies). */

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function siteOrigin(request: Request): string {
  const configured = process.env.SITE_URL;
  return configured ? new URL(configured).origin : new URL(request.url).origin;
}

export function isSameSiteRequest(request: Request): boolean {
  if (SAFE_METHODS.has(request.method.toUpperCase())) return true;
  const origin = request.headers.get("origin");
  return origin !== null && origin === siteOrigin(request);
}

export function forbiddenOrigin(): NextResponse {
  return NextResponse.json(
    { error: { code: "forbidden_origin", message: "This request must come from the site itself." } },
    { status: 403 },
  );
}
