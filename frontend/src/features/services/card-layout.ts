import type { components } from "@/lib/api/schema";

/** What the service grids and cards read: a service from GET /services, with its items. Kept out
 * of the "use client" card so server pages can import these values (a client module's exports
 * reach the server as client references, not as strings). */
export type ServiceSummary = components["schemas"]["PublicServiceWithItems"];

export const SERVICE_IMAGE_SIZES = {
  card: "(max-width: 520px) 100vw, (max-width: 1024px) 50vw, 300px",
  hero: "(max-width: 700px) 100vw, 50vw",
} as const;

/** The service grids (home page and /services): one column on small phones, two from 520px
 * (large phones, tablets), four on desktop. */
export const SERVICE_GRID = "grid gap-4 min-[520px]:grid-cols-2 lg:grid-cols-4 sm:gap-6";

/** How many included items a card's back shows before "+ n more on the details page". */
export const BACK_ITEMS = 6;
