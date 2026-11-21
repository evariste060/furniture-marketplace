/** The credentials the browser must never read (ADR-006): the customer or staff session token, the
 * guest cart token and, during Continue with Google, the flow token that binds the sign-in to this
 * browser. All live in httpOnly cookies set by this app's route handlers. */

export const SESSION_COOKIE = "sixty_session";
export const CART_COOKIE = "sixty_cart";
const CART_MAX_AGE = 30 * 24 * 60 * 60; // the backend expires guest carts after 30 days
/** Continue with Google: the flow between /api/auth/google/*start and the callback. Only those
 * route handlers receive it (its path), and it lives no longer than the backend's flow. */
export const GOOGLE_FLOW_COOKIE = "sixty_google_flow";
export const GOOGLE_FLOW_PATH = "/api/auth/google";
const GOOGLE_FLOW_MAX_AGE = 30 * 60; // the backend's longest flow (GOOGLE_OAUTH_FLOW_TTL_SECONDS)

type CookieOptions = {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: "/" | typeof GOOGLE_FLOW_PATH;
  maxAge: number;
};

function base(maxAge: number, path: CookieOptions["path"] = "/"): CookieOptions {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    // Lax, not Strict: Google's redirect back to the callback is a cross-site top-level GET, which
    // must carry the flow cookie; cross-site POSTs and subrequests never carry any of these.
    sameSite: "lax",
    path,
    maxAge,
  };
}

/** Session cookie options; it expires with the backend session. */
export function sessionCookieOptions(expiresAt: string, now: Date = new Date()): CookieOptions {
  const seconds = Math.floor((new Date(expiresAt).getTime() - now.getTime()) / 1000);
  return base(Math.max(0, seconds));
}

export function cartCookieOptions(): CookieOptions {
  return base(CART_MAX_AGE);
}

/** The Google flow cookie expires with the backend's flow (never later than 30 minutes). */
export function googleFlowCookieOptions(expiresAt: string, now: Date = new Date()): CookieOptions {
  const seconds = Math.floor((new Date(expiresAt).getTime() - now.getTime()) / 1000);
  return base(Math.min(GOOGLE_FLOW_MAX_AGE, Math.max(0, Number.isFinite(seconds) ? seconds : 0)), GOOGLE_FLOW_PATH);
}
