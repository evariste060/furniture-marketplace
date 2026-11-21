import type { Locale } from "./routing";

/** The admin's language, chosen in its top bar and kept in this cookie (path /admin, one year).
 * The storefront's language comes from its URL instead. */
export const ADMIN_LOCALE_COOKIE = "admin_locale";
export const ADMIN_LOCALES = ["en", "rw"] as const satisfies readonly Locale[];

/** The admin language a cookie value asks for; English for anything else. */
export function adminLocale(value: string | undefined): Locale {
  return value === "rw" ? "rw" : "en";
}

/** The cookie that keeps the admin in a language. */
export function adminLocaleCookie(locale: Locale): string {
  return `${ADMIN_LOCALE_COOKIE}=${locale}; Path=/admin; Max-Age=31536000; SameSite=Lax`;
}

/** Keeps the admin in a language (in the browser; the next server render reads it). */
export function saveAdminLocale(locale: Locale): void {
  document.cookie = adminLocaleCookie(locale);
}
