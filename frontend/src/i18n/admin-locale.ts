import type { Locale } from "./routing";

/** The admin's language, chosen in its top bar and kept in this cookie (path /admin, one year).
 * The seller dashboard keeps its own copy of the cookie under /seller (ADR-014 phase 4), so a
 * browser sends each panel only its own. The storefront's language comes from its URL instead. */
export const ADMIN_LOCALE_COOKIE = "admin_locale";
export const ADMIN_LOCALES = ["en", "rw"] as const satisfies readonly Locale[];

/** The admin language a cookie value asks for; English for anything else. */
export function adminLocale(value: string | undefined): Locale {
  return value === "rw" ? "rw" : "en";
}

/** The panels that keep their language in this cookie. */
export type PanelPath = "/admin" | "/seller";

/** The cookie that keeps a panel (the admin unless told otherwise) in a language. */
export function adminLocaleCookie(locale: Locale, path: PanelPath = "/admin"): string {
  return `${ADMIN_LOCALE_COOKIE}=${locale}; Path=${path}; Max-Age=31536000; SameSite=Lax`;
}

/** Keeps a panel in a language (in the browser; the next server render reads it). */
export function saveAdminLocale(locale: Locale, path: PanelPath = "/admin"): void {
  document.cookie = adminLocaleCookie(locale, path);
}
