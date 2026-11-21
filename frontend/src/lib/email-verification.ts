/** Email verification links (backend ADR-006 amendment 2026-11-12): the email links to
 * /verify-email#token=<token>. The token is in the URL fragment, which browsers never send to a
 * server or in a Referer header. `?token=` is accepted too, for links copied from elsewhere. The
 * token is never stored or logged: the page reads it once, removes it from the address bar and
 * keeps it in memory only. */

/** The backend's tokens are secrets.token_urlsafe(32): 43 URL-safe characters. It accepts 32-128
 * characters; anything else cannot be a link it sent. */
const TOKEN = /^[A-Za-z0-9_-]{32,128}$/;

export type LinkToken = { kind: "ok"; token: string } | { kind: "missing" } | { kind: "malformed" };

function fromParams(raw: string): string | null {
  try {
    return new URLSearchParams(raw).get("token");
  } catch {
    return null;
  }
}

/** The token in a verification link, from its fragment ("#token=…") or query ("?token=…"). */
export function readLinkToken(hash: string, search: string): LinkToken {
  const value = fromParams(hash.replace(/^#/, "")) ?? fromParams(search.replace(/^\?/, ""));
  if (value === null || value === "") return { kind: "missing" };
  return TOKEN.test(value) ? { kind: "ok", token: value } : { kind: "malformed" };
}

/** The page URL without the token, for history.replaceState (other query parameters stay). */
export function withoutToken(pathname: string, search: string): string {
  const params = new URLSearchParams(search.replace(/^\?/, ""));
  params.delete("token");
  const rest = params.toString();
  return rest ? `${pathname}?${rest}` : pathname;
}

/** Seconds from a Retry-After header, or null when absent or unusable. */
export function retryAfterSeconds(value: string | null): number | null {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
}
