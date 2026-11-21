import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Storefront pages only: not the API route handlers, the English-only admin, the development
  // component gallery, Next.js internals or files with an extension.
  matcher: "/((?!api/|admin|dev/|_next|_vercel|.*\\..*).*)",
};
