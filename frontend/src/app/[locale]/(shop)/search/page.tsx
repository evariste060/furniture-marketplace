import { Check, Mail, Search as SearchIcon } from "lucide-react";
import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { ProductCard } from "@/components/store/product-card";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { buttonClasses } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { FilterSheet } from "@/features/listing/listing-filters";
import { activeChips, apiQuery, ChipLink } from "@/features/listing/listing-results";
import { SortSelect } from "@/features/listing/sort-select";
import { getPathname, Link } from "@/i18n/navigation";
import { getCategories, getFacets, getProducts } from "@/lib/api/catalogue";
import {
  activeFilterCount,
  categoryTrail,
  EMPTY_FILTERS,
  listingSearch,
  parseListingState,
  productQuery,
  searchText,
  topCategories,
  type ListingState,
} from "@/lib/catalogue";
import { cx } from "@/lib/cx";

type Props = PageProps<"/[locale]/search">;

const GRID = "m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3 sm:gap-5 lg:grid-cols-4";
const CHIP = "inline-flex items-center rounded-full border px-4 py-[7px] text-sm font-medium whitespace-nowrap";

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.search" });
  const query = await searchParams;
  const q = searchText(query.q);
  const state = q ? null : parseListingState(query, { search: true });
  const category = state?.category ? (categoryTrail(await getCategories().catch(() => []), state.category)?.at(-1) ?? null) : null;
  // Result pages are not for search engines.
  return { title: q ? t("metaTitle", { q }) : category ? t("metaTitle", { q: category.name }) : t("title"), robots: { index: false } };
}

/** /search?q=: Search.dc.html (results) and SearchEmpty.dc.html (no results). The text matches
 * product names, brands and models (GET /catalog/products?q=, best match first).
 * /search?category=: the same results page for one category without text (the header's category
 * menu links here, approved 2026-11-16); its chips are the main category and its subcategories. */
export default function SearchPage({ searchParams }: Props) {
  return (
    <main id="main" className="bg-page">
      <Suspense fallback={<SearchFallback />}>
        <SearchResults searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function SearchResults({ searchParams }: Pick<Props, "searchParams">) {
  const t = await getTranslations("store.search");
  const params = await searchParams;
  const state = parseListingState(params, { search: true });
  // Without text, a known category opens its results; anything else asks for a search.
  const trail = !state.q && state.category ? categoryTrail(await getCategories().catch(() => []), state.category) : null;
  if (!state.q && !trail) return <Prompt />;
  const base = state.q ? { q: state.q } : {};
  let products, facets;
  try {
    [products, facets] = await Promise.all([getProducts({ ...productQuery(state), ...apiQuery(base, state) }), getFacets(apiQuery(base, state))]);
  } catch {
    return (
      <div className="wrap py-8">
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("error")}
        </p>
      </div>
    );
  }
  if (state.q && products.total === 0 && activeFilterCount(state) === 0) return <NoResults q={state.q} />;

  const tl = await getTranslations("store.listing");
  const tu = await getTranslations("ui");
  const locale = await getLocale();
  const href = (next: Partial<ListingState>) => `/search${listingSearch({ ...state, ...next })}`;
  const all = facets.categories.reduce((sum, c) => sum + c.count, 0);
  // The category is chosen with the chips above, so it is not repeated as a removable chip.
  const chips = activeChips({ ...state, category: null }, facets, tl);
  const inStockOnly = state.stock.length === 1 && state.stock[0] === "in";
  // By category: the chosen one stays when the other filters are cleared.
  const main = trail?.[0] ?? null;
  const subs = main?.children ?? [];
  const cleared = { ...EMPTY_FILTERS, category: trail ? state.category : null, page: 1 };
  const canClear = activeFilterCount({ ...state, category: trail ? null : state.category }) > 0;

  return (
    <>
      <section className="border-b border-bd bg-white">
        <div className="wrap flex flex-col gap-2 pt-5 pb-5 sm:pt-7 sm:pb-6">
          <Breadcrumb
            label={tu("breadcrumb")}
            items={[{ label: (await getTranslations("store.tabs"))("home"), href: getPathname({ href: "/", locale }) }, { label: t("title") }]}
          />
          <h1 className="t-h1 break-words max-sm:text-2xl">{state.q ? t("results", { q: state.q }) : trail?.at(-1)?.name}</h1>
          <p className="text-tx2">{state.q ? t("matches", { count: facets.total }) : t("categoryMatches", { count: facets.total })}</p>
          {main ? (
            subs.length > 0 && (
              <nav aria-label={tl("subcategories")} className="-mx-4 overflow-x-auto px-4 pt-2 sm:mx-0 sm:px-0">
                <ul className="m-0 flex list-none gap-2 p-0 sm:flex-wrap">
                  {[{ slug: main.slug, name: tl("allOf", { name: main.name }) }, ...subs].map((c) => (
                    <li key={c.slug}>
                      <CategoryChip href={href({ category: c.slug, page: 1 })} on={state.category === c.slug} label={c.name} />
                    </li>
                  ))}
                </ul>
              </nav>
            )
          ) : facets.categories.length > 1 || state.category ? (
            <nav aria-label={t("categoriesLabel")} className="-mx-4 overflow-x-auto px-4 pt-2 sm:mx-0 sm:px-0">
              <ul className="m-0 flex list-none gap-2 p-0 sm:flex-wrap">
                <li>
                  <CategoryChip href={href({ category: null, page: 1 })} on={!state.category} label={t("all", { count: all })} />
                </li>
                {facets.categories.map((c) => (
                  <li key={c.slug}>
                    <CategoryChip href={href({ category: c.slug, page: 1 })} on={state.category === c.slug} label={tl("withCount", { label: c.name, count: c.count })} />
                  </li>
                ))}
              </ul>
            </nav>
          ) : null}
        </div>
      </section>
      <div className="wrap flex flex-col gap-5 pt-5 pb-14 sm:pt-6">
        {/* Sticks under the header while the results scroll; -my/py keep its resting position. */}
        <div className="sticky top-(--store-header-h) z-30 -my-3 flex flex-wrap items-center gap-3 bg-white py-3">
          <FilterSheet state={state} facets={facets} basePath="/search" base={base} side="right" className="flex-none" keepCategory={Boolean(trail)} />
          <Link
            href={href({ stock: inStockOnly ? [] : ["in"], page: 1 })}
            aria-current={inStockOnly ? "true" : undefined}
            className={cx(CHIP, inStockOnly ? "border-pri bg-light text-pri-h" : "border-bd bg-white text-tx")}
          >
            {inStockOnly && <Check size={14} aria-hidden="true" className="mr-1.5" />}
            {t("inStockOnly")}
          </Link>
          {chips
            .filter((chip) => chip.key !== "stock")
            .map((chip) => (
              <ChipLink key={chip.key} href={href(chip.without)} label={chip.label} removeLabel={tl("remove", { name: chip.label })} />
            ))}
          <span className="flex-1" />
          <SortSelect state={state} basePath="/search" />
        </div>
        {products.items.length === 0 ? (
          <div className="flex flex-col items-start gap-2 rounded-xl border border-bd bg-white p-8">
            <h2 className="t-h3">{tl("empty")}</h2>
            <p className="text-tx2">{tl("emptyHint")}</p>
            {canClear && (
              <Link href={href(cleared)} className={buttonClasses({ variant: "outline", size: "sm" })}>
                {tl("clearAll")}
              </Link>
            )}
          </div>
        ) : (
          <ul className={GRID}>
            {products.items.map((product, i) => (
              <li key={product.id}>
                <ProductCard product={product} preload={i < 2} />
              </li>
            ))}
          </ul>
        )}
        <Pagination
          total={products.total}
          page={products.page}
          size={products.size}
          hrefFor={(page) => getPathname({ href: href({ page }), locale })}
          labels={{ nav: tu("pagination"), previous: tu("previous"), next: tu("next"), page: (n) => tu("page", { n }) }}
        />
      </div>
    </>
  );
}

function CategoryChip({ href, on, label }: { href: string; on: boolean; label: string }) {
  return (
    <Link href={href} aria-current={on ? "true" : undefined} className={cx(CHIP, on ? "border-pri bg-light text-pri-h" : "border-bd bg-white text-tx hover:text-tx")}>
      {label}
    </Link>
  );
}

/** /search without text: a pointer to the search box. */
async function Prompt() {
  const t = await getTranslations("store.search");
  return (
    <div className="wrap flex flex-col items-center gap-4 py-16 text-center">
      <span className="flex size-24 items-center justify-center rounded-full bg-light text-pri" aria-hidden="true">
        <SearchIcon size={40} />
      </span>
      <h1 className="t-h2">{t("title")}</h1>
      <p className="max-w-[560px] text-tx2">{t("prompt")}</p>
    </div>
  );
}

/** SearchEmpty.dc.html. "Ask us on WhatsApp" opens the store's WhatsApp with the search
 * prefilled; without a WhatsApp number it is a link to the Contact page. */
async function NoResults({ q }: { q: string }) {
  const t = await getTranslations("store.search");
  const categories = topCategories(await getCategories().catch(() => []));
  return (
    <>
      <section className="bg-page">
        <div className="wrap flex flex-col items-center gap-4 pt-12 pb-12 text-center sm:pt-[72px] sm:pb-16">
          <span className="flex size-24 items-center justify-center rounded-full bg-light text-pri" aria-hidden="true">
            <SearchIcon size={40} />
          </span>
          <h1 className="t-h2 break-words">{t("emptyTitle", { q })}</h1>
          <p className="text-lg max-w-[560px] text-tx2">{t("emptyText")}</p>
          <WhatsAppLink
            label={t("whatsapp")}
            message={t("whatsappMessage", { q })}
            variant="whatsapp"
            fallback={
              <Link href="/contact" className={buttonClasses({ variant: "outline" })}>
                <Mail size={18} aria-hidden="true" />
                {t("contact")}
              </Link>
            }
          />
          <ul className="m-0 flex list-none flex-col gap-2 p-0 pt-3 text-left">
            {(["tipSpelling", "tipGeneral", "tipBrowse"] as const).map((key) => (
              <li key={key} className="flex items-center gap-2">
                <Check size={16} className="text-ok" aria-hidden="true" />
                <span className="text-tx2">{t(key)}</span>
              </li>
            ))}
          </ul>
          {categories.length > 0 && (
            <ul className="m-0 flex list-none flex-wrap justify-center gap-2.5 p-0 pt-2">
              {categories.map((c) => (
                <li key={c.id}>
                  <Link href={`/category/${c.slug}`} className={cx(CHIP, "border-bd bg-white text-tx hover:border-pri hover:text-tx")}>
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      <Suspense fallback={null}>
        <Popular />
      </Suspense>
    </>
  );
}

async function Popular() {
  const t = await getTranslations("store.search");
  const page = await getProducts({ sort_by: "bestselling", sort_direction: "desc", size: 5 }).catch(() => null);
  if (!page?.items.length) return null;
  return (
    <section aria-labelledby="popular-title" className="bg-white py-10 sm:py-14">
      <div className="wrap flex flex-col gap-6">
        <h2 id="popular-title" className="t-h2">
          {t("popular")}
        </h2>
        <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3 sm:gap-5 lg:grid-cols-5">
          {page.items.map((product, i) => (
            <li key={product.id} className={cx(i >= 4 && "hidden lg:block", i === 3 && "sm:hidden lg:block")}>
              <ProductCard product={product} showButton={false} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function SearchFallback() {
  return (
    <>
      <section className="border-b border-bd bg-white">
        <div className="wrap flex flex-col gap-2 py-7">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-5 w-96 max-w-full" />
        </div>
      </section>
      <div className={cx("wrap py-6", GRID)}>
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-[330px] rounded-xl" />
        ))}
      </div>
    </>
  );
}
