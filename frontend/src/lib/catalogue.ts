import type { components } from "@/lib/api/schema";
import { primaryImage, type ApiImage } from "@/lib/images";

/** Pure catalogue helpers shared by the cards and the listing pages. Prices are whole RWF from the
 * API; the browser only formats them (the backend prices the cart and the order). */

export type CatalogProduct = components["schemas"]["CatalogProduct"];
export type CatalogVariant = components["schemas"]["CatalogVariant"];
export type CatalogCategory = components["schemas"]["CatalogCategory"];
export type CatalogFacets = components["schemas"]["CatalogFacets"];

/** The variant a card shows: the cheapest one in stock, else the cheapest one. Null when the
 * product has no public variant. */
export function displayVariant(product: Pick<CatalogProduct, "variants">): CatalogVariant | null {
  const byPrice = [...product.variants].sort((a, b) => a.price - b.price);
  return byPrice.find((v) => v.in_stock) ?? byPrice[0] ?? null;
}

/** "−10%" style discount, rounded down, when compare_at_price is above the price. */
export function discountPercent(variant: Pick<CatalogVariant, "price" | "compare_at_price">): number | null {
  const was = variant.compare_at_price;
  if (!was || was <= variant.price) return null;
  const percent = Math.floor(((was - variant.price) / was) * 100);
  return percent > 0 ? percent : null;
}

export type StockLabel = "in_stock" | "low_stock" | "out_of_stock";

/** The product's stock badge: in stock if any variant is, low stock if the in-stock ones are all
 * low, otherwise out of stock. */
export function productStock(product: Pick<CatalogProduct, "variants">): StockLabel {
  const available = product.variants.filter((v) => v.in_stock);
  if (!available.length) return "out_of_stock";
  return available.every((v) => v.stock_status === "low_stock") ? "low_stock" : "in_stock";
}

/** How many of the 5 stars are filled for an average, to the nearest half star. */
export function starFill(average: number | null | undefined): number {
  if (!average) return 0;
  return Math.round(average * 2) / 2;
}

/** The category with this slug and its ancestors, main category first; null if there is none. */
export function categoryTrail(categories: readonly CatalogCategory[], slug: string): CatalogCategory[] | null {
  for (const category of categories) {
    if (category.slug === slug) return [category];
    const trail = categoryTrail(category.children ?? [], slug);
    if (trail) return [category, ...trail];
  }
  return null;
}

/** Top-level categories in merchandising order (the API returns them sorted). */
export function topCategories(categories: readonly CatalogCategory[]): CatalogCategory[] {
  return categories.filter((c) => c.parent_id === null);
}

// ---------------------------------------------------------------------------------------------
// The header's mega menu: a few best sellers per top-level category, cut down to what the menu
// draws, so the header (on every page) sends a few hundred bytes per product, not whole products.

export type CatalogBrand = components["schemas"]["CatalogBrand"];

/** Best sellers shown per category in the mega menu. */
export const MENU_PRODUCTS = 6;

export type MenuProduct = {
  id: string;
  name: string;
  slug: string;
  image: ApiImage | null;
  /** The display variant's price, or null when the product has no public variant. */
  price: number | null;
};

/** A brand with products in a category, and how many (the category's brand facet). */
export type MenuBrand = { name: string; slug: string; count: number };

export type MenuCategory = {
  id: string;
  name: string;
  slug: string;
  /** The brands the menu lists: staff's chosen list (any may have 0 products) or, for a category
   * with neither a list nor subcategories, those with public products in it, by name. Empty
   * when the menu lists the subcategories instead. */
  brands: MenuBrand[];
  /** Its subcategories, in merchandising order; listed when `brands` is empty. */
  subcategories: { id: string; name: string; slug: string }[];
  /** Null when the products could not be loaded (the menu shows an error and the category link). */
  products: { items: MenuProduct[]; total: number } | null;
};

export function menuProduct(product: Pick<CatalogProduct, "id" | "name" | "slug" | "images" | "variants">): MenuProduct {
  return {
    id: product.id,
    name: product.name,
    slug: product.slug,
    image: primaryImage(product.images),
    price: displayVariant(product)?.price ?? null,
  };
}

/** The home hero's showcase (hero-showcase.tsx): at most this many categories on its orbit, and
 * this many related products (or services) beside the spotlight, four together since 2026-11-18
 * (from the same request as the mega menu). */
export const ORBIT_MAX = 6;
export const RELATED_MAX = 4;
/** The home page's category spotlights (category-spotlight.tsx): the small cards beside the
 * showcased product, up to two rows of four. */
export const SPOTLIGHT_PRODUCTS = 8;

/** The API query for a category's best sellers, shared by the mega menu (the first
 * MENU_PRODUCTS), the home hero's showcase (the spotlight and RELATED_MAX more) and the home
 * page's category spotlights (the showcase and SPOTLIGHT_PRODUCTS more), so the catalogue cache holds one response per
 * category for all three. */
export function menuProductQuery(slug: string) {
  return { category: slug, page: 1, size: Math.max(MENU_PRODUCTS, 1 + RELATED_MAX, 1 + SPOTLIGHT_PRODUCTS), sort_by: "bestselling", sort_direction: "desc" } as const;
}

// ---------------------------------------------------------------------------------------------
// Listing state in the URL: /deals?brand=a&brand=b&category=c&min_price=…&max_price=…&stock=in
// &rating=4&sort=price_asc&view=list&page=2 (and q=… on /search)

/** "relevance" (best match) exists only with a search and is then the default. */
export const SORTS = ["relevance", "popular", "price_asc", "price_desc", "newest", "top_rated"] as const;
export type ListingSort = (typeof SORTS)[number];
export const VIEWS = ["grid", "list"] as const;
export type ListingView = (typeof VIEWS)[number];
export const STOCK = ["in", "out"] as const;
export type StockChoice = (typeof STOCK)[number];
export const LISTING_PAGE_SIZE = 12;
export const MAX_BRANDS = 20;
/** Reviews per page on the product page. */
export const REVIEW_PAGE_SIZE = 3;

export type ListingState = {
  /** The search text (only on /search); null elsewhere. */
  q: string | null;
  /** One category (the brand page's Category group, the search chips). */
  category: string | null;
  brands: string[];
  minPrice: number | null;
  maxPrice: number | null;
  /** Both or neither ticked means no availability filter. */
  stock: StockChoice[];
  minRating: number | null;
  sort: ListingSort;
  view: ListingView;
  page: number;
};

export type ListingFilters = Pick<ListingState, "category" | "brands" | "minPrice" | "maxPrice" | "stock" | "minRating">;

export const EMPTY_FILTERS: ListingFilters = {
  category: null,
  brands: [],
  minPrice: null,
  maxPrice: null,
  stock: [],
  minRating: null,
};

type Params = Record<string, string | string[] | undefined>;

const all = (value: string | string[] | undefined): string[] =>
  value === undefined ? [] : Array.isArray(value) ? value : [value];
const first = (value: string | string[] | undefined): string | undefined => all(value)[0];

function wholeNumber(value: string | undefined, max: number): number | null {
  if (!value || !/^\d{1,10}$/.test(value)) return null;
  const n = Number(value);
  return n <= max ? n : null;
}

export const SEARCH_MAX_LENGTH = 160; // the header search box's maxLength
const SLUG = /^[a-z0-9-]{1,180}$/;

/** The default sort: best match for a search, otherwise popularity. */
export function defaultSort(state: Pick<ListingState, "q">): ListingSort {
  return state.q ? "relevance" : "popular";
}

/** The search text from ?q=: trimmed, inner spaces collapsed, at most 160 characters; null when
 * empty. */
export function searchText(value: string | string[] | undefined): string | null {
  const text = (first(value) ?? "").replace(/\s+/g, " ").trim().slice(0, SEARCH_MAX_LENGTH);
  return text || null;
}

/** Reads the listing state from search params. Anything invalid is ignored rather than sent to
 * the API, so a hand-edited URL shows the unfiltered list instead of an error. `q` is read only
 * where searching is the page's purpose (`search: true`). */
export function parseListingState(params: Params, { search = false }: { search?: boolean } = {}): ListingState {
  const q = search ? searchText(params.q) : null;
  const categoryParam = first(params.category);
  const category = categoryParam && SLUG.test(categoryParam) ? categoryParam : null;
  const brands = [...new Set(all(params.brand).filter((b) => SLUG.test(b)))].slice(0, MAX_BRANDS);
  let minPrice = wholeNumber(first(params.min_price), 1_000_000_000);
  let maxPrice = wholeNumber(first(params.max_price), 1_000_000_000);
  if (minPrice !== null && maxPrice !== null && minPrice > maxPrice) minPrice = maxPrice = null;
  const stock = STOCK.filter((s) => all(params.stock).includes(s));
  const rating = wholeNumber(first(params.rating), 5);
  const asked = SORTS.find((s) => s === first(params.sort));
  const sort = asked && (asked !== "relevance" || q) ? asked : defaultSort({ q });
  const view = VIEWS.find((v) => v === first(params.view)) ?? "grid";
  const page = wholeNumber(first(params.page), 10_000) ?? 1;
  return {
    q,
    category,
    brands,
    minPrice,
    maxPrice,
    stock: stock.length === STOCK.length ? [] : stock,
    minRating: rating && rating >= 1 ? rating : null,
    sort,
    view,
    page: Math.max(1, page),
  };
}

/** The listing state as a query string ("" when everything is default). */
export function listingSearch(state: ListingState): string {
  const query = new URLSearchParams();
  if (state.q) query.set("q", state.q);
  if (state.category) query.set("category", state.category);
  for (const b of state.brands) query.append("brand", b);
  if (state.minPrice !== null) query.set("min_price", String(state.minPrice));
  if (state.maxPrice !== null) query.set("max_price", String(state.maxPrice));
  for (const s of state.stock.length === STOCK.length ? [] : state.stock) query.append("stock", s);
  if (state.minRating !== null) query.set("rating", String(state.minRating));
  if (state.sort !== defaultSort(state)) query.set("sort", state.sort);
  if (state.view !== "grid") query.set("view", state.view);
  if (state.page > 1) query.set("page", String(state.page));
  const text = query.toString();
  return text ? `?${text}` : "";
}

const SORT_QUERY: Record<
  ListingSort,
  { sort_by?: "bestselling" | "price" | "newest" | "top_rated"; sort_direction?: "asc" | "desc" }
> = {
  relevance: {}, // the API's default with q: best match
  popular: { sort_by: "bestselling", sort_direction: "desc" },
  price_asc: { sort_by: "price", sort_direction: "asc" },
  price_desc: { sort_by: "price", sort_direction: "desc" },
  newest: { sort_by: "newest", sort_direction: "desc" },
  top_rated: { sort_by: "top_rated", sort_direction: "desc" },
};

/** The API filters for the state (shared by /catalog/products and /catalog/facets). */
export function filterQuery(state: ListingFilters & { q?: string | null }) {
  return {
    ...(state.q ? { q: state.q } : {}),
    ...(state.category ? { category: state.category } : {}),
    ...(state.brands.length ? { brand: state.brands } : {}),
    ...(state.minPrice !== null ? { min_price: state.minPrice } : {}),
    ...(state.maxPrice !== null ? { max_price: state.maxPrice } : {}),
    ...(state.stock.length === 1 ? { in_stock: state.stock[0] === "in" } : {}),
    ...(state.minRating !== null ? { min_rating: state.minRating } : {}),
  };
}

export function productQuery(state: ListingState) {
  return { ...filterQuery(state), ...SORT_QUERY[state.sort], page: state.page, size: LISTING_PAGE_SIZE };
}

/** How many filters are applied (the mobile "Filters (2)" button). */
export function activeFilterCount(state: ListingFilters): number {
  return (
    (state.category ? 1 : 0) +
    state.brands.length +
    (state.minPrice !== null || state.maxPrice !== null ? 1 : 0) +
    (state.stock.length === 1 ? 1 : 0) +
    (state.minRating !== null ? 1 : 0)
  );
}
