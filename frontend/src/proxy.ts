import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Storefront pages only: not the API route handlers, the English-only admin, the development
  // component gallery, Next.js internals or files with an extension.
  // The seller dashboard (/seller, ADR-014 phase 4) is outside the locale routing too.
  matcher: "/((?!api/|admin|seller|dev/|_next|_vercel|.*\\..*).*)",
};
