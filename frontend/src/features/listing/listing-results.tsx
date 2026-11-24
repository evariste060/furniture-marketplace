import { LayoutGrid, List, X } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import { ListingCard } from "@/components/store/listing-card";
import { buttonClasses } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { getPathname, Link } from "@/i18n/navigation";
import { getFacets, getProducts } from "@/lib/api/catalogue";
import {
  EMPTY_FILTERS,
  filterQuery,
  listingSearch,
  parseListingState,
  productQuery,
  type CatalogFacets,
  type ListingState,
} from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { InfiniteListing } from "./infinite-listing";
import { FilterPanel, FilterSheet, type BaseQuery, type FirstGroup, type SubcategoryFilter } from "./listing-filters";
import { bandLabel } from "./price-bands";
import { SortSelect } from "./sort-select";

type SearchParams = Record<string, string | string[] | undefined>;

/** The API query: the visitor's filters, then the page's own filter (which wins). */
export function apiQuery(base: BaseQuery, state: ListingState) {
  return { ...filterQuery(state), ...base };
}

/** The listing state for a page: a brand page (Category first) offers the category choice; the
 * other pages have their own category. Brands are not a storefront filter (SC-09). */
function pageState(params: SearchParams, first: FirstGroup): ListingState {
  const state = parseListingState(params);
  return first === "category" ? state : { ...state, category: null };
}

/** "Showing N products" in the listing hero. */
export async function ShowingCount({
  searchParams,
  base,
  first = "brand",
}: {
  searchParams: Promise<SearchParams>;
  base: BaseQuery;
  first?: FirstGroup;
}) {
  const t = await getTranslations("store.listing");
  const state = pageState(await searchParams, first);
  const data = await getProducts({ ...productQuery(state), ...apiQuery(base, state) }).catch(() => null);
  if (!data) return null;
  return <span className="text-sm font-medium">{t("showing", { count: data.total })}</span>;
}

/** Category.dc.html's body (filters, toolbar, cards, pagination) and the MobileCategory.dc.html
 * list. All state is in the URL, so every view can be linked and the back button works. */
export async function ListingResults({
  searchParams,
  base,
  path,
  first = "brand",
  infinite = false,
  subcategories,
}: {
  searchParams: Promise<SearchParams>;
  /** On a category page: the subcategory filter group. */
  subcategories?: SubcategoryFilter;
  base: BaseQuery;
  /** The page path without locale, e.g. "/deals". */
  path: string;
  /** The first filter group: Brand, or Category on a brand page. */
  first?: FirstGroup;
  /** Load further pages while scrolling (InfiniteListing) instead of numbered pagination. */
  infinite?: boolean;
}) {
  const t = await getTranslations("store.listing");
  const tu = await getTranslations("ui");
  const locale = await getLocale();
  const parsed = pageState(await searchParams, first);
  // An infinite list always starts at the first page.
  const state = infinite ? { ...parsed, page: 1 } : parsed;
  const query = { ...productQuery(state), ...apiQuery(base, state) };
  let products, facets: CatalogFacets;
  try {
    [products, facets] = await Promise.all([
      getProducts(query),
      getFacets(apiQuery(base, state)),
    ]);
  } catch {
    return (
      <div className="wrap py-8">
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("error")}
        </p>
      </div>
    );
  }
  const href = (next: Partial<ListingState>) => `${path}${listingSearch({ ...state, ...next })}`;
  const chips = activeChips(state, facets, t);
  const props = { state, facets, basePath: path, base, first, subcategories };

  return (
    <div className="bg-page">
      {/* Mobile toolbar: sticks under the header while the listing scrolls. */}
      <div className="sticky top-(--store-header-h) z-30 flex flex-col gap-3 border-b border-bd bg-card px-4 py-3 lg:hidden">
        <div className="flex gap-2.5">
          <FilterSheet {...props} />
          <SortSelect state={state} basePath={path} compact />
        </div>
        <div className="flex items-center gap-2 overflow-x-auto">
          {chips.map((chip) => (
            <ChipLink key={chip.key} href={href(chip.without)} label={chip.label} removeLabel={t("remove", { name: chip.label })} />
          ))}
          <span className="text-sm whitespace-nowrap text-mut">{t("count", { count: products.total })}</span>
        </div>
      </div>
      <div className="wrap flex items-start gap-6 pt-0 pb-14">
        <FilterPanel {...props} />
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <div className="hidden flex-wrap items-center gap-3 lg:flex">
            <span className="font-semibold">{t("found", { count: products.total })}</span>
            {chips.map((chip) => (
              <ChipLink key={chip.key} href={href(chip.without)} label={chip.label} removeLabel={t("remove", { name: chip.label })} />
            ))}
            {chips.length > 0 && (
              <Link href={href({ ...EMPTY_FILTERS, page: 1 })} className={buttonClasses({ variant: "ghost", size: "sm", className: "px-1" })}>
                {t("clearAll")}
              </Link>
            )}
            <span className="flex-1" />
            <SortSelect state={state} basePath={path} />
            <div className="flex overflow-hidden rounded-lg border border-bd">
              {(["grid", "list"] as const).map((view) => (
                <Link
                  key={view}
                  href={href({ view, page: state.page })}
                  aria-label={t(view)}
                  aria-current={state.view === view ? "true" : undefined}
                  className={cx(
                    "flex size-[42px] items-center justify-center",
                    state.view === view ? "bg-pri text-white hover:text-white" : "bg-card text-tx2",
                  )}
                >
                  {view === "grid" ? <LayoutGrid size={18} aria-hidden="true" /> : <List size={18} aria-hidden="true" />}
                </Link>
              ))}
            </div>
          </div>
          {products.items.length === 0 ? (
            <div className="flex flex-col items-start gap-2 rounded-xl border border-bd bg-card p-8">
              <h2 className="t-h3">{t("empty")}</h2>
              <p className="text-tx2">{t("emptyHint")}</p>
              {chips.length > 0 && (
                <Link href={href({ ...EMPTY_FILTERS, page: 1 })} className={buttonClasses({ variant: "outline", size: "sm" })}>
                  {t("clearAll")}
                </Link>
              )}
            </div>
          ) : infinite ? (
            <InfiniteListing key={JSON.stringify(query)} query={query} initial={products} view={state.view} />
          ) : (
            <ul
              className={cx(
                "m-0 grid list-none grid-cols-1 gap-3 p-0 sm:gap-4",
                state.view === "grid" ? "sm:grid-cols-2 xl:grid-cols-3" : "",
              )}
            >
              {products.items.map((product, i) => (
                <li key={product.id}>
                  <ListingCard product={product} preload={i < 2} />
                </li>
              ))}
            </ul>
          )}
          {!infinite && (
            <Pagination
              total={products.total}
              page={products.page}
              size={products.size}
              hrefFor={(page) => getPathname({ href: href({ page }), locale })}
              labels={{ nav: tu("pagination"), previous: tu("previous"), next: tu("next"), page: (n) => tu("page", { n }) }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

type Chip = { key: string; label: string; without: Partial<ListingState> };
type ListingT = Awaited<ReturnType<typeof getTranslations<"store.listing">>>;

export function activeChips(state: ListingState, facets: CatalogFacets, t: ListingT): Chip[] {
  const chips: Chip[] = [];
  if (state.category) {
    chips.push({
      key: "category",
      label: facets.categories.find((c) => c.slug === state.category)?.name ?? state.category,
      without: { category: null, page: 1 },
    });
  }
  if (state.minPrice !== null || state.maxPrice !== null) {
    chips.push({
      key: "price",
      label: bandLabel({ min_price: state.minPrice, max_price: state.maxPrice }, (k, v) => t(k, v), "long"),
      without: { minPrice: null, maxPrice: null, page: 1 },
    });
  }
  if (state.stock.length === 1) {
    chips.push({ key: "stock", label: t(state.stock[0] === "in" ? "inStock" : "outOfStock"), without: { stock: [], page: 1 } });
  }
  if (state.minRating !== null) {
    chips.push({ key: "rating", label: t("ratingUp", { stars: state.minRating }), without: { minRating: null, page: 1 } });
  }
  return chips;
}

export function ChipLink({ href, label, removeLabel }: { href: string; label: string; removeLabel: string }) {
  return (
    <span className="inline-flex flex-none items-center gap-1.5 rounded-md bg-light px-2.5 py-1.5 text-sm font-medium whitespace-nowrap text-pri-h">
      {label}
      <Link href={href} aria-label={removeLabel} className="flex text-current hover:text-pri-fg">
        <X size={14} aria-hidden="true" />
      </Link>
    </span>
  );
}

export function ListingFallback() {
  return (
    <div className="bg-page">
      <div className="wrap flex gap-6 pt-0 pb-8">
        <Skeleton className="hidden h-[640px] max-w-[300px] flex-[1_1_260px] rounded-xl lg:block" />
        <div className="grid flex-[999_1_560px] grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[270px] rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  );
}
