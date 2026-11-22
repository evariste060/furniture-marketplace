import * as rootParams from "next/root-params";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";
import { withMarketplace } from "@/lib/marketplace";
import { ADMIN_LOCALE_COOKIE, adminLocale } from "./admin-locale";
import { routing } from "./routing";

export default getRequestConfig(async ({ locale }) => {
  let admin = false;
  if (!locale) {
    // Storefront pages have a [locale] root parameter. The admin and /dev have none: the admin's
    // language comes from its own cookie (English unless Kinyarwanda was chosen in the top bar),
    // with the admin's messages (messages/admin.json or admin.rw.json) on top.
    const value = await rootParams.locale().catch(() => undefined);
    if (value === undefined) {
      admin = true;
      locale = adminLocale((await cookies()).get(ADMIN_LOCALE_COOKIE)?.value);
    } else if (hasLocale(routing.locales, value)) locale = value;
    else notFound();
  }
  // The marketplace name is filled in here, once (lib/marketplace.ts).
  const messages = withMarketplace((await import(`../../messages/${locale}.json`)).default);
  if (!admin) return { locale, timeZone: "Africa/Kigali", messages };
  // Two literal imports: the bundler can't follow a path chosen at run time.
  const adminMessages = locale === "rw" ? (await import("../../messages/admin.rw.json")).default : (await import("../../messages/admin.json")).default;
  return { locale, timeZone: "Africa/Kigali", messages: { ...messages, admin: withMarketplace(adminMessages) } };
});
