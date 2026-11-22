/** Helpers for the sign-in, registration and password pages. The browser only checks what is
 * typed; the backend applies the same rules again and owns every decision (AGENTS.md). */

/** Where to go after signing in: a path on this site only ("/cart", "/product/x?y=1"), never
 * another origin ("//evil.example", "https://…", "/\\evil"). Anything else → fallback. */
export function safeReturnTo(value: string | string[] | null | undefined, fallback = "/account"): string {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || raw.length > 512) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return fallback;
  // Control characters could hide a scheme or a second slash from the checks above.
  if ([...raw].some((c) => c.charCodeAt(0) < 0x20 || c.charCodeAt(0) === 0x7f)) return fallback;
  return raw;
}

/** /seller and its pages: the seller dashboard (ADR-014 phase 4), outside the locale routing. */
export function isSellerPath(path: string): boolean {
  return path === "/seller" || path.startsWith("/seller/") || path.startsWith("/seller?");
}

export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 256;

/** The backend's password rule (app/core/security.py): 8–256 characters with an upper-case
 * letter, a lower-case letter and a digit or symbol. */
export function passwordOk(password: string): boolean {
  return (
    password.length >= PASSWORD_MIN &&
    password.length <= PASSWORD_MAX &&
    /[A-Z]/.test(password) &&
    /[a-z]/.test(password) &&
    /[\d\W_]/.test(password)
  );
}

/** The register page's four-bar meter: one bar each for length, mixed case, a digit or symbol,
 * and 12 or more characters. 0 for an empty password. */
export function passwordStrength(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0;
  let score = 0;
  if (password.length >= PASSWORD_MIN) score++;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score++;
  if (/[\d\W_]/.test(password)) score++;
  if (password.length >= 12 && score === 3) score++;
  return Math.max(1, score) as 1 | 2 | 3 | 4;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function emailOk(value: string): boolean {
  return value.length <= 254 && EMAIL.test(value);
}

/** The code's destination on the reset page, partly hidden: "+250 788 ••• 111" or
 * "al•••@example.com". */
export function maskIdentifier(identifier: string): string {
  const value = identifier.trim();
  if (value.includes("@")) {
    const [name, domain] = value.split("@");
    return `${name.slice(0, 2)}•••@${domain}`;
  }
  const digits = value.replace(/\D/g, "");
  const local = digits.startsWith("250") ? digits.slice(3) : digits.replace(/^0/, "");
  if (local.length !== 9) return value;
  return `+250 ${local.slice(0, 3)} ••• ${local.slice(6)}`;
}

/** The identifier the reset page needs, carried from the forgot page in this tab only (never in
 * the URL, so it stays out of history and logs). */
const RESET_KEY = "sixty_reset";

export function rememberResetIdentifier(identifier: string): void {
  try {
    sessionStorage.setItem(RESET_KEY, identifier);
  } catch {
    // Storage may be unavailable: the reset page then asks for it.
  }
}

export function resetIdentifier(): string | null {
  try {
    return sessionStorage.getItem(RESET_KEY);
  } catch {
    return null;
  }
}

export function forgetResetIdentifier(): void {
  try {
    sessionStorage.removeItem(RESET_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** "Aline Mukamana" → "AM" for the account avatar. */
export function initials(fullName: string | null | undefined): string {
  const parts = (fullName ?? "").trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts;
  return letters.map((p) => p[0]!.toUpperCase()).join("") || "?";
}
