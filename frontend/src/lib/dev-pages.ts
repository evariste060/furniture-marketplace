/** Development-only pages (the component gallery at /dev/ui). In a production build they exist
 * only when ENABLE_DEV_UI=true was set at build time (the end-to-end tests do that). */
export function devPagesEnabled(): boolean {
  return process.env.NODE_ENV !== "production" || process.env.ENABLE_DEV_UI === "true";
}
