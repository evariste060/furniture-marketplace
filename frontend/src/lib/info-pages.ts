/** Info pages (module 19): the six policy pages the API serves, in menu order (Policy.dc.html's
 * "Help & policies"). The keys name their messages; the slugs match the backend's PAGE_SLUGS. */
export const INFO_PAGES = {
  about: "/pages/about-us",
  delivery: "/pages/delivery-information",
  returns: "/pages/returns-and-refunds",
  warranty: "/pages/warranty",
  privacy: "/pages/privacy-policy",
  terms: "/pages/terms-and-conditions",
} as const;

export type InfoPageKey = keyof typeof INFO_PAGES;

/** The page key of a slug, or null when the slug is not one of the six pages. */
export function infoPageKey(slug: string): InfoPageKey | null {
  const entry = Object.entries(INFO_PAGES).find(([, href]) => href === `/pages/${slug}`);
  return entry ? (entry[0] as InfoPageKey) : null;
}
