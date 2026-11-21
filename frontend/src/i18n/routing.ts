import { defineRouting } from "next-intl/routing";

/** Storefront locales: English at "/", Kinyarwanda under "/rw". The admin lives outside this
 * routing (/admin) and keeps its language in a cookie (./admin-locale.ts). */
export const routing = defineRouting({
  locales: ["en", "rw"],
  defaultLocale: "en",
  localePrefix: "as-needed",
  // The language is chosen from the URL only, never from the browser's Accept-Language.
  localeDetection: false,
});

export type Locale = (typeof routing.locales)[number];
