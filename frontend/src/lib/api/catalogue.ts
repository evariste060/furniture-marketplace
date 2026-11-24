import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { connection } from "next/server";
import type { paths } from "./schema";
import { ApiError } from "./errors";
import { publicApi } from "./server";

/** Public catalogue reads for Server Components, cached briefly with the `catalogue` profile
 * (next.config.ts: about a minute). Errors are thrown, not cached, so the page's error state
 * shows and the next request retries.
 *
 * Each exported read first awaits connection(): during `next build` it never resolves, so the
 * read is left to request time and the build never calls the API. Without it, Next runs the
 * cached function while prerendering and a failed call stops the build, even when the caller
 * catches it (the store header and footer do, and the not-found page draws them on every
 * route). */

export type ProductQuery = NonNullable<paths["/api/v1/catalog/products"]["get"]["parameters"]["query"]>;

async function cachedCategories() {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/catalog/categories");
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

async function cachedBrands() {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/catalog/brands");
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

async function cachedProducts(query: ProductQuery) {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/catalog/products", { params: { query } });
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

async function cachedBanners() {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/banners");
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

export type FacetQuery = NonNullable<paths["/api/v1/catalog/facets"]["get"]["parameters"]["query"]>;

async function cachedFacets(query: FacetQuery) {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/catalog/facets", { params: { query } });
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

/** Delivery zones and the free-delivery threshold (the announcement bar and trust strip). */
async function cachedDeliveryInfo() {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/delivery/zones");
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

/** One public product with its rating distribution; null when the slug is unknown or hidden. */
async function cachedProduct(slug: string) {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/catalog/products/{slug}", {
    params: { path: { slug } },
  });
  if (response.status === 404) return null;
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

/** Approved reviews of a product, newest first (module 20). */
async function cachedProductReviews(slug: string, page = 1, size = 3) {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/catalog/products/{slug}/reviews", {
    params: { path: { slug }, query: { page, size } },
  });
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

/** The store's public contact details and announcement (GET /settings, module 19). */
async function cachedStoreContact() {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/settings");
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

/** One published language version of a policy page (module 19); null when that version does
 * not exist or is unpublished (the API never answers with another language). */
async function cachedPage(slug: string, lang: "en" | "rw") {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/pages/{slug}", {
    params: { path: { slug }, query: { lang } },
  });
  if (response.status === 404) return null;
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

/** One approved store's public profile (ADR-014 phase 5); null when there is none: unknown,
 * pending, rejected and suspended stores all answer 404. Never contact details or the owner. */
async function cachedStore(slug: string) {
  "use cache";
  cacheLife("catalogue");
  cacheTag("catalogue");
  const { data, error, response } = await publicApi().GET("/api/v1/stores/{slug}", { params: { path: { slug } } });
  if (response.status === 404) return null;
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

async function atRequestTime<T>(read: () => Promise<T>): Promise<T> {
  await connection();
  return read();
}

export function getCategories() {
  return atRequestTime(() => cachedCategories());
}

export function getBrands() {
  return atRequestTime(() => cachedBrands());
}

export function getProducts(query: ProductQuery) {
  return atRequestTime(() => cachedProducts(query));
}

export function getBanners() {
  return atRequestTime(() => cachedBanners());
}

export function getFacets(query: FacetQuery) {
  return atRequestTime(() => cachedFacets(query));
}

export function getDeliveryInfo() {
  return atRequestTime(() => cachedDeliveryInfo());
}

export function getProduct(slug: string) {
  return atRequestTime(() => cachedProduct(slug));
}

export function getProductReviews(slug: string, page = 1, size = 3) {
  return atRequestTime(() => cachedProductReviews(slug, page, size));
}

export function getStoreContact() {
  return atRequestTime(() => cachedStoreContact());
}

export function getStore(slug: string) {
  return atRequestTime(() => cachedStore(slug));
}

export function getPage(slug: string, lang: "en" | "rw") {
  return atRequestTime(() => cachedPage(slug, lang));
}
