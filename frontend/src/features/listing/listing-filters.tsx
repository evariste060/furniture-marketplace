"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { SlidersHorizontal, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Checkbox, Radio } from "@/components/ui/form";
import { Link, useRouter } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import {
  activeFilterCount,
  EMPTY_FILTERS,
  filterQuery,
  listingSearch,
  type CatalogFacets,
  type ListingFilters,
  type ListingState,
  type StockChoice,
} from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { CHOICES, type FilterKey } from "@/lib/furniture";
import { bandKey, bandLabel, type PriceBand } from "./price-bands";

type Filters = ListingFilters;
/** The page's own fixed filter (Deals: on_sale=true; a category page: its category; a brand
 * page: its brand; search: the text). */
/** `store` (ADR-014 phase 5): one approved store's products (/store/[slug]). */
export type BaseQuery = { on_sale?: boolean; category?: string; brand?: string[]; q?: string; store?: string };
/** Which choice group comes first: Brand (default) or, on a brand page, Category. */
export type FirstGroup = "brand" | "category";
/** On a category page: its main category's subcategories, offered as the first filter group
 * (owner, 2026-11-17; they used to be links above the listing). `current` is the page's slug. */
export type SubcategoryFilter = { main: { name: string; slug: string }; items: { name: string; slug: string }[]; current: string };

const RATING = 4; // the design's one rating option: "4 stars & up"

function samePrice(f: Filters, band: PriceBand) {
  return f.minPrice === (band.min_price ?? null) && f.maxPrice === (band.max_price ?? null);
}

/** Live counts for the filters being chosen (each group ignores its own filter, so every count is
 * what the list would show with that option). The server's counts for the applied filters are
 * the starting point. */
function usePendingFacets(base: BaseQuery, applied: Filters, pending: Filters, initial: CatalogFacets) {
  const changed = JSON.stringify(pending) !== JSON.stringify(applied);
  const query = useQuery({
    queryKey: ["facets", base, pending],
    enabled: changed,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET("/api/v1/catalog/facets", {
        params: { query: { ...base, ...filterQuery(pending), brand: [...(base.brand ?? []), ...pending.brands] } },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
  return changed ? (query.data ?? initial) : initial;
}

/** `keepCategory`: the page's category is not one of these filters (the search page opened from the
 * category menu), so "Clear all" keeps it. */
function useFilterState(state: ListingState, basePath: string, keepCategory = false) {
  const router = useRouter();
  const applied: Filters = useMemo(
    () => ({
      category: state.category,
      brands: state.brands,
      minPrice: state.minPrice,
      maxPrice: state.maxPrice,
      stock: state.stock,
      minRating: state.minRating,
      attributes: state.attributes,
    }),
    [state],
  );
  const [pending, setPending] = useState<Filters>(applied);
  const go = (filters: Filters) => router.push(`${basePath}${listingSearch({ ...state, ...filters, page: 1 })}`);
  return {
    applied,
    pending,
    setPending,
    apply: () => go(pending),
    clearAll: () => {
      const cleared = keepCategory ? { ...EMPTY_FILTERS, category: state.category } : EMPTY_FILTERS;
      setPending(cleared);
      go(cleared);
    },
    reset: () => setPending(applied),
    setCategory: (slug: string | null) => setPending((f) => ({ ...f, category: slug })),
    toggleBrand: (slug: string) =>
      setPending((f) => ({ ...f, brands: f.brands.includes(slug) ? f.brands.filter((b) => b !== slug) : [...f.brands, slug] })),
    setBand: (band: PriceBand | null) =>
      setPending((f) => ({ ...f, minPrice: band?.min_price ?? null, maxPrice: band?.max_price ?? null })),
    toggleStock: (choice: StockChoice) =>
      setPending((f) => ({ ...f, stock: f.stock.includes(choice) ? f.stock.filter((s) => s !== choice) : [...f.stock, choice] })),
    toggleRating: () => setPending((f) => ({ ...f, minRating: f.minRating === RATING ? null : RATING })),
    toggleAttribute: (key: FilterKey, code: string) =>
      setPending((f) => {
        const on = f.attributes[key].includes(code);
        const codes = on ? f.attributes[key].filter((c) => c !== code) : [...f.attributes[key], code];
        const order: readonly string[] = CHOICES[key];
        return { ...f, attributes: { ...f.attributes, [key]: codes.sort((a, b) => order.indexOf(a) - order.indexOf(b)) } };
      }),
  };
}

type Props = { state: ListingState; facets: CatalogFacets; basePath: string; base: BaseQuery; first?: FirstGroup; subcategories?: SubcategoryFilter };

/** The subcategory choices: each opens that (sub)category's page at once, keeping the other
 * filters and the sort; "All …" is the main category. */
function subcategoryChoices(sub: SubcategoryFilter, state: ListingState, allLabel: string) {
  const search = listingSearch({ ...state, page: 1 });
  return [{ slug: sub.main.slug, name: allLabel }, ...sub.items].map((c) => ({
    ...c,
    href: `/category/${c.slug}${search}`,
    on: c.slug === sub.current,
  }));
}

/** Subcategory choices in the panel: links drawn as radio options. */
function SubcategoryGroup({ sub, state }: { sub: SubcategoryFilter; state: ListingState }) {
  const t = useTranslations("store.listing");
  return (
    <nav aria-label={t("subcategory")} className="border-t border-bd py-4">
      <h3 className="m-0 mb-2.5 text-base font-semibold">{t("subcategory")}</h3>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {subcategoryChoices(sub, state, t("allIn", { name: sub.main.name })).map((c) => (
          <li key={c.slug}>
            <Link
              href={c.href}
              aria-current={c.on ? "page" : undefined}
              className={cx("flex items-center gap-2 rounded-md py-1 text-sm no-underline", c.on ? "font-semibold text-pri-h" : "text-tx hover:text-pri")}
            >
              <span
                aria-hidden="true"
                className={cx("flex size-4 flex-none items-center justify-center rounded-full border", c.on ? "border-pri" : "border-bd2 bg-white")}
              >
                {c.on && <span className="size-2 rounded-full bg-pri" />}
              </span>
              {c.name}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** The furniture attribute groups (ADR-014 phase 6): Material, Colour, Style, each listing the
 * codes found with the other filters applied, plus any chosen one (so it can be unticked). */
function attributeGroups(facets: CatalogFacets, pending: Filters) {
  return (facets.attributes ?? [])
    .map((group) => ({ key: group.key, values: group.values.filter((v) => v.count > 0 || pending.attributes[group.key].includes(v.value)) }))
    .filter((group) => group.values.length > 0);
}

function Group({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="m-0 flex flex-col gap-2.5 border-0 border-t border-bd px-0 py-4">
      <legend className="float-left mb-2.5 w-full p-0 font-semibold">{legend}</legend>
      {children}
    </fieldset>
  );
}

function FourStars() {
  return (
    <span className="inline-flex gap-px text-star" aria-hidden="true">
      {[1, 2, 3, 4].map((n) => (
        <Star key={n} size={14} fill="currentColor" strokeWidth={0} />
      ))}
    </span>
  );
}

/** Category.dc.html filter panel (desktop): Brand (Category on a brand page), Price range,
 * Availability, Customer rating. Storage, Screen size and Delivery are left out: the catalogue
 * has no such filters (owner decision 2026-10-27). Choices apply with "Apply Filters". */
export function FilterPanel({ state, facets: initial, basePath, base, first = "brand", subcategories }: Props) {
  const t = useTranslations("store.listing");
  const f = useFilterState(state, basePath);
  const facets = usePendingFacets(base, f.applied, f.pending, initial);
  const tf = useTranslations("furniture");
  const n = (label: string, count: number) => t("withCount", { label, count });
  return (
    <aside
      aria-label={t("filters")}
      className="sticky top-[calc(var(--store-header-h)+1rem)] hidden max-h-[calc(100dvh-var(--store-header-h)-2rem)] max-w-[300px] flex-[1_1_260px] overflow-y-auto overscroll-contain rounded-xl border border-bd bg-white p-5 lg:block"
    >
      <div className="flex items-center justify-between pb-4">
        <h2 className="t-h3">{t("filters")}</h2>
        <Button variant="ghost" size="sm" className="h-auto px-0" onClick={f.clearAll}>
          {t("clearAll")}
        </Button>
      </div>
      {subcategories && <SubcategoryGroup sub={subcategories} state={state} />}
      {first === "category" && facets.categories.length > 0 && (
        <Group legend={t("category")}>
          <Radio name="category" label={t("allCategories")} checked={f.pending.category === null} onChange={() => f.setCategory(null)} />
          {facets.categories.map((c) => (
            <Radio
              key={c.slug}
              name="category"
              label={n(c.name, c.count)}
              checked={f.pending.category === c.slug}
              onChange={() => f.setCategory(c.slug)}
            />
          ))}
        </Group>
      )}
      {first === "brand" && facets.brands.length > 0 && (
        <Group legend={t("brand")}>
          {facets.brands.map((b) => (
            <Checkbox key={b.slug} label={n(b.name, b.count)} checked={f.pending.brands.includes(b.slug)} onChange={() => f.toggleBrand(b.slug)} />
          ))}
        </Group>
      )}
      {attributeGroups(facets, f.pending).map((group) => (
        <Group key={group.key} legend={tf(`names.${group.key}`)}>
          {group.values.map((v) => (
            <Checkbox
              key={v.value}
              label={n(tf(`${group.key}.${v.value}`), v.count)}
              checked={f.pending.attributes[group.key].includes(v.value)}
              onChange={() => f.toggleAttribute(group.key, v.value)}
            />
          ))}
        </Group>
      ))}
      <Group legend={t("price")}>
        {facets.price_bands.map((band) => (
          <Radio
            key={bandKey(band)}
            name="price"
            label={n(bandLabel(band, t, "long"), band.count)}
            checked={samePrice(f.pending, band)}
            onChange={() => f.setBand(band)}
          />
        ))}
      </Group>
      <Group legend={t("availability")}>
        <Checkbox label={n(t("inStock"), facets.availability.in_stock)} checked={f.pending.stock.includes("in")} onChange={() => f.toggleStock("in")} />
        <Checkbox label={n(t("outOfStock"), facets.availability.out_of_stock)} checked={f.pending.stock.includes("out")} onChange={() => f.toggleStock("out")} />
      </Group>
      <Group legend={t("rating")}>
        <Checkbox
          label={
            <>
              <FourStars />
              {n(t("ratingUp", { stars: RATING }), facets.ratings.find((r) => r.min_rating === RATING)?.count ?? 0)}
            </>
          }
          checked={f.pending.minRating === RATING}
          onChange={f.toggleRating}
        />
      </Group>
      <div className="flex gap-2.5 border-t border-bd pt-4">
        <Button size="sm" className="flex-1" onClick={f.apply}>
          {t("apply")}
        </Button>
        <Button variant="outline" size="sm" className="flex-1" onClick={f.reset}>
          {t("reset")}
        </Button>
      </div>
    </aside>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cx(
        "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-4 py-[7px] text-sm font-medium",
        on ? "border-pri bg-light text-pri-h" : "border-bd bg-white text-tx",
      )}
    >
      {children}
    </button>
  );
}

/** MobileCategory.dc.html: "Filters (n)" opens a bottom sheet with chips; "Show N products"
 * applies them. */
export function FilterSheet({
  state,
  facets: initial,
  basePath,
  base,
  first = "brand",
  side = "bottom",
  className = "flex-1",
  keepCategory = false,
  subcategories,
}: Props & { side?: "bottom" | "right"; className?: string; keepCategory?: boolean }) {
  const t = useTranslations("store.listing");
  const tu = useTranslations("ui");
  const tf = useTranslations("furniture");
  const [open, setOpen] = useState(false);
  const f = useFilterState(state, basePath, keepCategory);
  const facets = usePendingFacets(base, f.applied, f.pending, initial);
  const applied = activeFilterCount(keepCategory ? { ...f.applied, category: null } : f.applied);
  return (
    <>
      <Button
        variant="neutral"
        size="sm"
        className={className}
        aria-haspopup="dialog"
        onClick={() => {
          f.reset();
          setOpen(true);
        }}
      >
        <SlidersHorizontal size={16} aria-hidden="true" />
        {applied ? t("filtersCount", { count: applied }) : t("filters")}
      </Button>
      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        side={side}
        title={t("filters")}
        closeLabel={tu("close")}
        footer={
          <Button
            block
            onClick={() => {
              setOpen(false);
              f.apply();
            }}
          >
            {t("show", { count: facets.total })}
          </Button>
        }
      >
        <div className="flex flex-col gap-[18px] p-4">
          <Button variant="ghost" size="sm" className="self-end px-0" onClick={f.clearAll}>
            {t("clearAll")}
          </Button>
          {subcategories && (
            <SheetGroup title={t("subcategory")}>
              {subcategoryChoices(subcategories, state, t("allIn", { name: subcategories.main.name })).map((c) => (
                <Link
                  key={c.slug}
                  href={c.href}
                  aria-current={c.on ? "page" : undefined}
                  onClick={() => setOpen(false)}
                  className={cx(
                    "inline-flex items-center rounded-full border px-4 py-[7px] text-sm font-medium no-underline",
                    c.on ? "border-pri bg-light text-pri-h" : "border-bd bg-white text-tx",
                  )}
                >
                  {c.name}
                </Link>
              ))}
            </SheetGroup>
          )}
          {first === "category" && facets.categories.length > 0 && (
            <SheetGroup title={t("category")}>
              {facets.categories.map((c) => {
                const on = f.pending.category === c.slug;
                return (
                  <Chip key={c.slug} on={on} onClick={() => f.setCategory(on ? null : c.slug)}>
                    {c.name}
                  </Chip>
                );
              })}
            </SheetGroup>
          )}
          {first === "brand" && facets.brands.length > 0 && (
            <SheetGroup title={t("brand")}>
              {facets.brands.map((b) => (
                <Chip key={b.slug} on={f.pending.brands.includes(b.slug)} onClick={() => f.toggleBrand(b.slug)}>
                  {b.name}
                </Chip>
              ))}
            </SheetGroup>
          )}
          {attributeGroups(facets, f.pending).map((group) => (
            <SheetGroup key={group.key} title={tf(`names.${group.key}`)}>
              {group.values.map((v) => (
                <Chip key={v.value} on={f.pending.attributes[group.key].includes(v.value)} onClick={() => f.toggleAttribute(group.key, v.value)}>
                  {tf(`${group.key}.${v.value}`)}
                </Chip>
              ))}
            </SheetGroup>
          ))}
          <SheetGroup title={t("priceShort")}>
            {facets.price_bands.map((band) => {
              const on = samePrice(f.pending, band);
              return (
                <Chip key={bandKey(band)} on={on} onClick={() => f.setBand(on ? null : band)}>
                  {bandLabel(band, t, "short")}
                </Chip>
              );
            })}
          </SheetGroup>
          <SheetGroup title={t("availability")}>
            <Checkbox label={t("inStock")} checked={f.pending.stock.includes("in")} onChange={() => f.toggleStock("in")} />
            <Checkbox label={t("outOfStock")} checked={f.pending.stock.includes("out")} onChange={() => f.toggleStock("out")} />
          </SheetGroup>
          <SheetGroup title={t("rating")}>
            <Chip on={f.pending.minRating === RATING} onClick={f.toggleRating}>
              <FourStars />
              {t("ratingUp", { stars: RATING })}
            </Chip>
          </SheetGroup>
        </div>
      </Drawer>
    </>
  );
}

function SheetGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={title} className="flex flex-col gap-2.5">
      <b className="font-semibold" aria-hidden="true">
        {title}
      </b>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}
