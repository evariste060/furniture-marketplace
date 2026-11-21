"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronUp, CornerDownRight, ExternalLink, EyeOff, Folder, FolderPlus, FolderTree, LayoutList, Pencil, Plus, Search, Tag, X, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { Toggle } from "@/components/ui/toggle";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { bodyFieldErrors, FilterBar, LoadError, must, PageHeader, postFiles, Thumb, useListParams } from "./ui";

type Category = components["schemas"]["StaffCategoryItem"];
type Brand = components["schemas"]["StaffBrandItem"];

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const IMAGE_TYPES = "image/jpeg,image/png,image/webp";

/** Categories in tree order (parents before their children, each level by sort order, then name)
 * with their depth. */
export function categoryTree<T extends Pick<Category, "id" | "parent_id" | "sort_order" | "name">>(items: readonly T[]): { item: T; level: number; hasChildren: boolean }[] {
  const byParent = new Map<string | null, T[]>();
  const ids = new Set(items.map((i) => i.id));
  for (const item of items) {
    const parent = item.parent_id && ids.has(item.parent_id) ? item.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) ?? []), item]);
  }
  const out: { item: T; level: number; hasChildren: boolean }[] = [];
  const walk = (parent: string | null, level: number) => {
    const children = [...(byParent.get(parent) ?? [])].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
    for (const child of children) {
      out.push({ item: child, level, hasChildren: byParent.has(child.id) });
      walk(child.id, level + 1);
    }
  };
  walk(null, 0);
  return out;
}

/** The categories under one (to keep a category from being moved under itself). */
function descendants(items: readonly Pick<Category, "id" | "parent_id">[], id: string): Set<string> {
  const found = new Set<string>([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const item of items)
      if (item.parent_id && found.has(item.parent_id) && !found.has(item.id)) {
        found.add(item.id);
        grew = true;
      }
  }
  return found;
}

/** Products in a category and every subcategory below it (product_count is direct only). */
export function subtreeCount(items: readonly Pick<Category, "id" | "parent_id" | "product_count">[], id: string): number {
  const ids = descendants(items, id);
  return items.reduce((sum, item) => sum + (ids.has(item.id) ? item.product_count : 0), 0);
}

export type CategoryStatus = "all" | "shown" | "hidden";

/** The rows a search and status filter keep: the matches, plus their parents so each match stays
 * in its place in the tree. An empty search with "all" keeps everything. */
export function visibleRows(items: readonly Pick<Category, "id" | "parent_id" | "name" | "slug" | "is_active">[], search: string, status: CategoryStatus): Set<string> {
  const needle = search.trim().toLowerCase();
  const byId = new Map(items.map((i) => [i.id, i]));
  const keep = new Set<string>();
  for (const item of items) {
    const text = !needle || item.name.toLowerCase().includes(needle) || item.slug.includes(needle);
    const state = status === "all" || (status === "shown") === item.is_active;
    if (!text || !state) continue;
    for (let node: typeof item | undefined = item; node && !keep.has(node.id); node = node.parent_id ? byId.get(node.parent_id) : undefined) keep.add(node.id);
  }
  return keep;
}

/** The ids under one parent in their order, with one of them moved up (-1) or down (+1); null
 * when it is already first or last. */
export function siblingOrder(items: readonly Pick<Category, "id" | "parent_id" | "sort_order" | "name">[], id: string, step: -1 | 1): string[] | null {
  const item = items.find((i) => i.id === id);
  if (!item) return null;
  const siblings = items.filter((i) => i.parent_id === item.parent_id).sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
  const from = siblings.findIndex((i) => i.id === id);
  const to = from + step;
  if (to < 0 || to >= siblings.length) return null;
  const ids = siblings.map((i) => i.id);
  [ids[from], ids[to]] = [ids[to], ids[from]];
  return ids;
}

/** The position after the last category under a parent: new and moved categories go last. */
export function nextSortOrder(items: readonly Pick<Category, "id" | "parent_id" | "sort_order">[], parentId: string | null, exceptId?: string): number {
  const siblings = items.filter((i) => i.parent_id === parentId && i.id !== exceptId);
  return siblings.length ? Math.max(...siblings.map((i) => i.sort_order)) + 1 : 1;
}

/** The list with the item at `index` moved one place up (-1) or down (1); unchanged at either end. */
export function moveItem<T>(list: readonly T[], index: number, step: -1 | 1): T[] {
  const to = index + step;
  if (index < 0 || to < 0 || to >= list.length) return [...list];
  const next = [...list];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}

/** Brands that can be added to a menu list: active ones not listed yet, by name. */
export function addableBrands<T extends Pick<Brand, "id" | "name" | "is_active">>(brands: readonly T[], listed: readonly string[]): T[] {
  return brands.filter((b) => b.is_active && !listed.includes(b.id)).sort((a, b) => a.name.localeCompare(b.name));
}

/** Brands filtered by a search (name or slug) and status, by name. */
export function filterBrands<T extends Pick<Brand, "name" | "slug" | "is_active"> & { category_ids?: string[] }>(brands: readonly T[], search: string, status: CategoryStatus, category = ""): T[] {
  const needle = search.trim().toLowerCase();
  const inCategory = (b: T) => !category || (category === NO_CATEGORY ? !b.category_ids?.length : (b.category_ids ?? []).includes(category));
  return brands
    .filter((b) => (!needle || b.name.toLowerCase().includes(needle) || b.slug.includes(needle)) && (status === "all" || (status === "shown") === b.is_active) && inCategory(b))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** The brands filter's value for brands without a category yet. */
export const NO_CATEGORY = "none";

/** The brands that belong to a main category (ADR-012 decision 9), by name. */
export function brandsOfCategory<T extends Pick<Brand, "name"> & { category_ids?: string[] }>(brands: readonly T[], categoryId: string): T[] {
  return brands.filter((b) => (b.category_ids ?? []).includes(categoryId)).sort((a, b) => a.name.localeCompare(b.name));
}

/** For each brand, the main categories whose store menu lists it, in tree order. */
export function menusByBrand<T extends Pick<Category, "id" | "parent_id" | "sort_order" | "name" | "menu_brand_ids">>(categories: readonly T[]): Map<string, T[]> {
  const found = new Map<string, T[]>();
  for (const { item, level } of categoryTree(categories)) {
    if (level !== 0) continue;
    for (const brandId of item.menu_brand_ids ?? []) found.set(brandId, [...(found.get(brandId) ?? []), item]);
  }
  return found;
}

/** Names typed or pasted for new subcategories: one per line, trimmed, inner spaces collapsed,
 * blank lines dropped. A name already under the main category (any case), or repeated, is
 * skipped. */
export function newSubcategoryNames(text: string, existing: readonly string[]): { names: string[]; skipped: string[] } {
  const seen = new Set(existing.map((n) => n.trim().toLowerCase()));
  const names: string[] = [];
  const skipped: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const name = line.trim().replace(/\s+/g, " ");
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) skipped.push(name);
    else {
      seen.add(key);
      names.push(name);
    }
  }
  return { names, skipped };
}

/** Creates subcategories one after another, in order, after the existing ones; one refused
 * name does not stop the others. Slugs come from the names (backend). */
async function createSubcategories(parentId: string, names: readonly string[], firstSortOrder: number) {
  const added: string[] = [];
  const failed: { name: string; code: string | null; detail: string | null }[] = [];
  for (const [index, name] of names.entries()) {
    try {
      await must(browserApi.POST("/api/v1/staff/categories", { body: { name, parent_id: parentId, slug: null, is_active: true, description: null, sort_order: firstSortOrder + index } }));
      added.push(name);
    } catch (error) {
      failed.push({ name, code: error instanceof ApiError ? (error.code ?? null) : null, detail: bodyFieldErrors(error).name ?? null });
    }
  }
  return { added, failed };
}

const DETAIL_TABS = ["subcategories", "brands", "menu", "details"] as const;
type DetailTab = (typeof DETAIL_TABS)[number];
type DialogTab = "basics" | "media" | "menu";
type Editing = { category: Category | null; parentId: string | null; tab?: DialogTab; name?: string };

function useStaffCategories() {
  return useQuery({ queryKey: ["admin", "categories"], queryFn: () => must(browserApi.GET("/api/v1/staff/categories")) });
}

function useStaffBrands() {
  return useQuery({ queryKey: ["admin", "brands"], queryFn: () => must(browserApi.GET("/api/v1/staff/brands")) });
}

/** The page's header: title, the four totals and the Categories / Brands tabs (Categories.dc.html,
 * redesigned 2026-11-16). */
function CatalogueHeader({ categories, brands, action }: { categories?: Category[]; brands?: Brand[]; action: ReactNode }) {
  const t = useTranslations("admin.catalogue");
  const pathname = usePathname();
  const hidden = categories && brands ? categories.filter((c) => !c.is_active).length + brands.filter((b) => !b.is_active).length : undefined;
  const tabs = [
    { href: "/admin/categories", label: t("stats.categories"), count: categories?.length },
    { href: "/admin/brands", label: t("stats.brands"), count: brands?.length },
  ];
  return (
    <>
      <PageHeader title={t("title")} description={t("pageDescription")} actions={action} />
      <dl className="m-0 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat Icon={FolderTree} tone="bg-light text-pri-h" label={t("stats.topLevel")} value={categories?.filter((c) => !c.parent_id).length} />
        <Stat Icon={Folder} tone="bg-subtle text-tx2" label={t("stats.subcategories")} value={categories?.filter((c) => c.parent_id).length} />
        <Stat Icon={Tag} tone="bg-pur-bg text-pur" label={t("stats.brands")} value={brands?.length} />
        <Stat Icon={EyeOff} tone="bg-warn-bg text-warn-tx" label={t("stats.hidden")} value={hidden} />
      </dl>
      <nav aria-label={t("sections")} className="flex gap-7 overflow-x-auto overflow-y-hidden border-b border-bd">
        {tabs.map((item) => {
          const on = pathname === item.href;
          return (
            <NextLink
              key={item.href}
              href={item.href}
              aria-current={on ? "page" : undefined}
              className={cx(
                "-mb-px flex items-center gap-2 border-b-2 px-0.5 py-3 text-base font-semibold whitespace-nowrap no-underline transition-colors duration-150 motion-reduce:transition-none",
                on ? "border-pri text-pri-h hover:text-pri-h" : "border-transparent text-tx2 hover:border-bd2 hover:text-tx",
              )}
            >
              {item.label}
              {item.count !== undefined && (
                <span className={cx("rounded-full px-2 py-px text-cap font-semibold tabular-nums", on ? "bg-light text-pri-h" : "bg-subtle text-tx2")}>{item.count}</span>
              )}
            </NextLink>
          );
        })}
      </nav>
    </>
  );
}

function Stat({ Icon, tone, label, value }: { Icon: LucideIcon; tone: string; label: string; value: number | undefined }) {
  return (
    <div className="flex items-center gap-3.5 rounded-xl border border-bd bg-white p-4 shadow-sh">
      <span aria-hidden="true" className={cx("flex size-10 flex-none items-center justify-center rounded-xl", tone)}>
        <Icon size={19} />
      </span>
      <div className="flex min-w-0 flex-col">
        <dt className="truncate text-sm text-tx2">{label}</dt>
        <dd className="m-0">{value === undefined ? <Skeleton className="mt-1 h-6 w-10" /> : <b className="t-h2 tabular-nums">{value}</b>}</dd>
      </div>
    </div>
  );
}

/** /admin/categories: the main categories down the left; the one chosen (kept in the URL as
 * ?category=&tab=) opens on the right with its subcategories, store menu and details. */
export function CategoriesView() {
  const t = useTranslations("admin.catalogue");
  const categories = useStaffCategories();
  const brands = useStaffBrands();
  const { get, set } = useListParams();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [brandEditing, setBrandEditing] = useState<{ brand: Brand | null; categoryIds?: string[] } | null>(null);
  const items = categories.data?.items ?? [];
  const mains = categoryTree(items)
    .filter(({ level }) => level === 0)
    .map(({ item }) => item);
  const selected = mains.find((c) => c.id === get("category")) ?? mains[0] ?? null;
  const tab: DetailTab = DETAIL_TABS.find((x) => x === get("tab")) ?? "subcategories";
  const tabParam = (next: DetailTab) => (next === "subcategories" ? null : next);

  return (
    <>
      <CatalogueHeader
        categories={categories.data?.items}
        brands={brands.data?.items}
        action={
          <Button onClick={() => setEditing({ category: null, parentId: null })} className="gap-1.5">
            <Plus size={16} aria-hidden="true" />
            {t("addMainCategory")}
          </Button>
        }
      />
      {categories.isError ? (
        <LoadError onRetry={() => categories.refetch()} />
      ) : !categories.data ? (
        <div className="grid items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]" aria-busy="true">
          <Skeleton className="h-96 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      ) : mains.length === 0 ? (
        <div className="rounded-xl border border-bd bg-white shadow-sh">
          <Empty Icon={FolderTree}>{t("noCategories")}</Empty>
        </div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <MainList items={items} mains={mains} selectedId={selected?.id ?? null} onSelect={(id, next) => set({ category: id, tab: tabParam(next ?? tab) })} />
          {selected && (
            <CategoryDetail
              category={selected}
              items={items}
              brands={brands.data?.items}
              tab={tab}
              onTab={(next) => set({ category: selected.id, tab: tabParam(next) })}
              onEdit={(category, dialogTab) => setEditing({ category, parentId: category.parent_id, tab: dialogTab })}
              onAddWithOptions={(name) => setEditing({ category: null, parentId: selected.id, name })}
              onEditBrand={(brand) => setBrandEditing({ brand })}
              onNewBrand={() => setBrandEditing({ brand: null, categoryIds: [selected.id] })}
            />
          )}
        </div>
      )}
      {editing && (
        <CategoryDialog
          category={editing.category}
          initialParentId={editing.parentId}
          initialTab={editing.tab}
          initialName={editing.name}
          all={items}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            if (!saved.parent_id) set({ category: saved.id, tab: null });
          }}
          onDeleted={(deleted) => {
            if (deleted.id === selected?.id) set({ category: null, tab: null });
          }}
        />
      )}
      {brandEditing && <BrandDialog brand={brandEditing.brand} initialCategoryIds={brandEditing.categoryIds} onClose={() => setBrandEditing(null)} />}
    </>
  );
}

/** The main categories with their totals; the search also finds subcategories, shown under
 * their main category. */
function MainList({ items, mains, selectedId, onSelect }: { items: Category[]; mains: Category[]; selectedId: string | null; onSelect: (id: string, tab?: DetailTab) => void }) {
  const t = useTranslations("admin.catalogue");
  const headingId = useId();
  const [search, setSearch] = useState("");
  const searching = search.trim() !== "";
  const keep = visibleRows(items, search, "all");
  const tree = categoryTree(items);
  const rows = mains
    .filter((main) => keep.has(main.id))
    .map((main) => ({
      main,
      subs: items.filter((c) => c.parent_id === main.id).length,
      found: searching ? tree.filter(({ item }) => item.parent_id === main.id && keep.has(item.id)).map(({ item }) => item) : [],
    }));
  return (
    <section aria-labelledby={headingId} className="min-w-0 overflow-hidden rounded-xl border border-bd bg-white shadow-sh lg:sticky lg:top-24">
      <div className="flex flex-col gap-3 border-b border-bd px-4 pt-4 pb-3">
        <h2 id={headingId} className="t-h3 flex items-center gap-2">
          {t("mainCategories")}
          <span className="rounded-full bg-subtle px-2 py-px text-cap font-semibold text-tx2 tabular-nums">{mains.length}</span>
        </h2>
        <label className="relative block">
          <span className="sr-only">{t("search")}</span>
          <Search size={15} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-tx2" />
          <Input type="search" value={search} placeholder={t("searchAll")} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        </label>
      </div>
      {rows.length === 0 ? (
        <Empty Icon={Search}>{t("noMatches")}</Empty>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-0.5 overflow-y-auto p-2 lg:max-h-[calc(100dvh-320px)]">
          {rows.map(({ main, subs, found }) => {
            const on = main.id === selectedId;
            const total = subtreeCount(items, main.id);
            return (
              <li key={main.id}>
                <button
                  type="button"
                  aria-current={on ? "true" : undefined}
                  onClick={() => onSelect(main.id)}
                  className={cx(
                    "group relative flex w-full cursor-pointer items-center gap-3 rounded-lg border-0 px-2.5 py-2.5 text-left transition-colors duration-150 motion-reduce:transition-none",
                    on ? "bg-light" : "bg-transparent hover:bg-page",
                  )}
                >
                  {on && <span aria-hidden="true" className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-pri" />}
                  <CategoryImage category={main} size={40} main />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className={cx("truncate text-sm font-semibold", on ? "text-pri-h" : main.is_active ? "text-tx" : "text-tx2")}>{main.name}</span>
                      {!main.is_active && (
                        <>
                          <EyeOff size={13} aria-hidden="true" className="flex-none text-tx2" />
                          <span className="sr-only">{t("hiddenBadge")}</span>
                        </>
                      )}
                    </span>
                    <span className="text-cap text-tx2">{t("subcategoryCount", { count: subs })}</span>
                  </span>
                  <span
                    title={t("productCountTotal", { count: total })}
                    className={cx("flex-none rounded-full px-2 py-0.5 text-cap font-semibold tabular-nums", on ? "bg-white text-pri-h" : "bg-subtle text-tx2")}
                  >
                    {total}
                    <span className="sr-only">{t("productsWord", { count: total })}</span>
                  </span>
                </button>
                {found.length > 0 && (
                  <ul className="m-0 list-none p-0 pb-1" aria-label={t("matchesIn", { name: main.name })}>
                    {found.map((sub) => (
                      <li key={sub.id}>
                        <button
                          type="button"
                          onClick={() => onSelect(main.id, "subcategories")}
                          className="flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent py-1.5 pr-3 pl-[62px] text-left text-sm text-tx2 hover:bg-page hover:text-pri-h"
                        >
                          <CornerDownRight size={14} aria-hidden="true" className="flex-none" />
                          <span className="truncate">{sub.name}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** A category's image, or a folder icon when it has none. */
function CategoryImage({ category, size, main = false }: { category: Category; size: number; main?: boolean }) {
  if (category.image) return <Thumb image={{ url: category.image.url, width: category.image.width, height: category.image.height, alt: "", position: 0 }} size={size} />;
  const Icon = main ? FolderTree : Folder;
  return (
    <span aria-hidden="true" className={cx("flex flex-none items-center justify-center rounded-lg", main ? "bg-light text-pri-h" : "bg-subtle text-tx2")} style={{ width: size, height: size }}>
      <Icon size={Math.round(size / 2.3)} />
    </span>
  );
}

/** A brand's logo, or its first letters when it has none. */
function BrandMark({ brand, size }: { brand: Brand; size: number }) {
  if (brand.logo) return <Thumb image={{ url: brand.logo.url, width: brand.logo.width, height: brand.logo.height, alt: "", position: 0 }} size={size} />;
  return (
    <span aria-hidden="true" className="inline-flex flex-none items-center justify-center rounded-lg bg-light text-cap font-bold text-pri-h" style={{ width: size, height: size }}>
      {brand.name.slice(0, 2).toUpperCase()}
    </span>
  );
}

/** "Shown" (green) or "Hidden" (grey). */
function StatusBadge({ active }: { active: boolean }) {
  const t = useTranslations("admin.catalogue");
  return (
    <Badge tone={active ? "soft-ok" : "soft-neutral"} className="gap-1">
      <span aria-hidden="true" className={cx("size-1.5 rounded-full", active ? "bg-ok-tx" : "bg-tx2")} />
      {active ? t("stateShown") : t("stateHidden")}
    </Badge>
  );
}

function useCategoryReorder(items: Category[]) {
  const t = useTranslations("admin.catalogue");
  const tc = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async ({ item, step }: { item: Category; step: -1 | 1 }) => {
      const ids = siblingOrder(items, item.id, step);
      if (ids) await must(browserApi.PUT("/api/v1/staff/categories/order", { body: { parent_id: item.parent_id, category_ids: ids } }));
    },
    onError: (error) => toast.show(error instanceof ApiError && error.code === "category_order_mismatch" ? t("errors.orderChanged") : tc("common.saveError"), "error"),
    onSettled: () => void client.invalidateQueries({ queryKey: ["admin", "categories"] }),
  });
}

/** Move up / move down for a category among its siblings. */
function MoveButtons({ item, items, reorder }: { item: Category; items: Category[]; reorder: ReturnType<typeof useCategoryReorder> }) {
  const t = useTranslations("admin.catalogue");
  const canUp = siblingOrder(items, item.id, -1) !== null;
  const canDown = siblingOrder(items, item.id, 1) !== null;
  return (
    <span className="flex gap-1">
      <button type="button" aria-label={t("moveUp", { name: item.name })} title={t("moveUp", { name: item.name })} disabled={!canUp || reorder.isPending} onClick={() => reorder.mutate({ item, step: -1 })} className={cx(ICON_BUTTON, MOVE_DISABLED)}>
        <ChevronUp size={14} aria-hidden="true" />
      </button>
      <button type="button" aria-label={t("moveDown", { name: item.name })} title={t("moveDown", { name: item.name })} disabled={!canDown || reorder.isPending} onClick={() => reorder.mutate({ item, step: 1 })} className={cx(ICON_BUTTON, MOVE_DISABLED)}>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
    </span>
  );
}

/** One figure in the category's summary row. */
function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg border border-bd bg-page px-3.5 py-3">
      <dt className="text-cap font-medium text-tx2">{label}</dt>
      <dd className="m-0 flex min-h-6 items-center text-base font-semibold text-tx tabular-nums">{children}</dd>
    </div>
  );
}

function CategoryDetail({
  category,
  items,
  brands,
  tab,
  onTab,
  onEdit,
  onAddWithOptions,
  onEditBrand,
  onNewBrand,
}: {
  category: Category;
  items: Category[];
  brands: Brand[] | undefined;
  tab: DetailTab;
  onTab: (tab: DetailTab) => void;
  onEdit: (category: Category, tab?: DialogTab) => void;
  onAddWithOptions: (name: string) => void;
  onEditBrand: (brand: Brand) => void;
  onNewBrand: () => void;
}) {
  const t = useTranslations("admin.catalogue");
  const headingId = useId();
  const reorder = useCategoryReorder(items);
  const subs = categoryTree(items)
    .filter(({ item }) => item.parent_id === category.id)
    .map(({ item }) => item);
  const hiddenSubs = subs.filter((s) => !s.is_active).length;
  const listed = (category.menu_brand_ids ?? []).length;
  const ownBrands = brands ? brandsOfCategory(brands, category.id).length : undefined;
  return (
    <section aria-labelledby={headingId} className="min-w-0 overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
      <div className="flex flex-col gap-4 border-b border-bd p-5">
        <div className="flex flex-wrap items-start gap-4">
          <CategoryImage category={category} size={56} main />
          <div className="flex min-w-0 flex-[1_1_220px] flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id={headingId} className="t-h2">
                {category.name}
              </h2>
              <StatusBadge active={category.is_active} />
            </div>
            <p className="m-0 font-mono text-sm text-tx2">/{category.slug}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={`/category/${encodeURIComponent(category.slug)}`}
              target="_blank"
              rel="noopener"
              aria-label={t("viewOnStoreOf", { name: category.name })}
              className={buttonClasses({ variant: "ghost", size: "sm", className: "gap-1.5" })}
            >
              <ExternalLink size={14} aria-hidden="true" />
              {t("viewOnStore")}
            </a>
            <MoveButtons item={category} items={items} reorder={reorder} />
            <Button variant="neutral" size="sm" onClick={() => onEdit(category)} className="gap-1.5">
              <Pencil size={14} aria-hidden="true" />
              {t("edit")}
            </Button>
          </div>
        </div>
        <dl className="m-0 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
          <Metric label={t("metrics.products")}>{subtreeCount(items, category.id)}</Metric>
          <Metric label={t("metrics.subcategories")}>
            {subs.length}
            {hiddenSubs > 0 && <span className="ml-2 text-cap font-medium text-tx2">{t("hiddenCount", { count: hiddenSubs })}</span>}
          </Metric>
          <Metric label={t("metrics.brands")}>{ownBrands === undefined ? <Skeleton className="h-5 w-8" /> : ownBrands}</Metric>
          <Metric label={t("metrics.menu")}>{listed ? t("menuShort.brands", { count: listed }) : subs.length ? t("menuShort.subcategories") : t("menuShort.productBrands")}</Metric>
          <Metric label={t("metrics.visibility")}>
            <ActiveToggle kind="category" id={category.id} name={category.name} active={category.is_active} showState />
          </Metric>
        </dl>
      </div>
      <Tabs
        label={t("tabsLabel", { name: category.name })}
        value={tab}
        onChange={(id) => onTab(id as DetailTab)}
        className="px-5 pb-5"
        items={[
          {
            id: "subcategories",
            label: (
              <span className="flex items-center gap-2">
                {t("tabs.subcategories")}
                <span className="rounded-full bg-subtle px-2 py-px text-cap font-semibold text-tx2 tabular-nums">{subs.length}</span>
              </span>
            ),
            content: <SubcategoryTable main={category} subs={subs} items={items} reorder={reorder} onEdit={(sub) => onEdit(sub)} onAddWithOptions={onAddWithOptions} />,
          },
          {
            id: "brands",
            label: (
              <span className="flex items-center gap-2">
                {t("tabs.brands")}
                {ownBrands !== undefined && <span className="rounded-full bg-subtle px-2 py-px text-cap font-semibold text-tx2 tabular-nums">{ownBrands}</span>}
              </span>
            ),
            content: <CategoryBrands category={category} brands={brands} onEdit={onEditBrand} onNew={onNewBrand} />,
          },
          { id: "menu", label: t("tabs.menu"), content: <StoreMenuSummary category={category} subs={subs} brands={brands} onEdit={() => onEdit(category, "menu")} /> },
          { id: "details", label: t("tabs.details"), content: <CategoryDetails category={category} onEdit={() => onEdit(category)} /> },
        ]}
      />
    </section>
  );
}

/** Adding subcategories without a dialog: type a name and press Enter (the box stays ready for
 * the next), or paste a list, one per line. "More options" opens the full dialog. */
function QuickAddSubcategories({ main, siblings, items, onAddWithOptions, first = false }: { main: Category; siblings: Category[]; items: Category[]; onAddWithOptions: (name: string) => void; first?: boolean }) {
  const t = useTranslations("admin.catalogue");
  const client = useQueryClient();
  const inputId = useId();
  const hintId = useId();
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ added: string[]; skipped: string[]; failed: { name: string; code: string | null; detail: string | null }[] } | null>(null);
  const add = useMutation({
    mutationFn: (names: string[]) => createSubcategories(main.id, names, nextSortOrder(items, main.id)),
    onSettled: () => void client.invalidateQueries({ queryKey: ["admin", "categories"] }),
  });
  const submit = async (value: string) => {
    const { names, skipped } = newSubcategoryNames(value, siblings.map((s) => s.name));
    if (names.length === 0) {
      setResult({ added: [], skipped, failed: [] });
      if (skipped.length) setText("");
      return;
    }
    const done = await add.mutateAsync(names);
    setResult({ ...done, skipped });
    // A refused name stays in the box to be corrected.
    setText(done.failed[0]?.name ?? "");
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim() && !add.isPending) void submit(text);
      }}
      className="flex flex-col gap-2"
    >
      <label htmlFor={inputId} className="text-sm font-semibold text-tx">
        {first ? t("quickAdd.firstTitle", { name: main.name }) : t("quickAdd.title")}
      </label>
      <div className="flex flex-wrap gap-2">
        <span className="relative min-w-0 flex-[1_1_260px]">
          <Plus size={16} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-tx2" />
          <Input
            id={inputId}
            value={text}
            maxLength={160}
            aria-describedby={hintId}
            placeholder={t("quickAdd.placeholder")}
            disabled={add.isPending}
            onChange={(e) => setText(e.target.value)}
            onPaste={(e) => {
              const pasted = e.clipboardData.getData("text");
              if (!/\r?\n/.test(pasted.trim())) return;
              // A pasted list adds every line at once (a one-line box would join them).
              e.preventDefault();
              void submit(`${text}\n${pasted}`);
            }}
            className="pl-9"
          />
        </span>
        <Button type="submit" disabled={!text.trim() || add.isPending}>
          {add.isPending ? t("quickAdd.adding") : t("quickAdd.add")}
        </Button>
        <Button type="button" variant="ghost" onClick={() => onAddWithOptions(text.trim())}>
          {t("quickAdd.moreOptions")}
        </Button>
      </div>
      <p id={hintId} className="m-0 text-cap text-tx2">
        {t("quickAdd.hint")}
      </p>
      <div role="status" aria-live="polite" className="flex flex-col gap-1 empty:hidden">
        {result && result.added.length > 0 && (
          <p className="m-0 flex items-start gap-1.5 text-sm text-ok-tx">
            <Check size={15} aria-hidden="true" className="mt-0.5 flex-none" />
            {t("quickAdd.added", { count: result.added.length, names: result.added.join(", ") })}
          </p>
        )}
        {result && result.skipped.length > 0 && <p className="m-0 text-sm text-tx2">{t("quickAdd.skipped", { names: result.skipped.join(", ") })}</p>}
        {result?.failed.map((f) => (
          <p key={f.name} className="m-0 text-sm text-err-tx">
            {t("quickAdd.failed", { name: f.name, reason: f.code === "slug_taken" ? t("quickAdd.slugTaken") : (f.detail ?? t("quickAdd.otherError")) })}
          </p>
        ))}
      </div>
    </form>
  );
}

function SubcategoryTable({
  main,
  subs,
  items,
  reorder,
  onEdit,
  onAddWithOptions,
}: {
  main: Category;
  subs: Category[];
  items: Category[];
  reorder: ReturnType<typeof useCategoryReorder>;
  onEdit: (sub: Category) => void;
  onAddWithOptions: (name: string) => void;
}) {
  const t = useTranslations("admin.catalogue");
  if (subs.length === 0) {
    return (
      <div className="flex flex-col gap-5">
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-bd2 px-6 py-8 text-center">
          <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-light text-pri-h">
            <FolderPlus size={22} />
          </span>
          <p className="m-0 font-semibold">{t("noSubcategoriesYet", { name: main.name })}</p>
          <p className="m-0 max-w-md text-sm text-tx2">{t("noSubcategoriesHelp")}</p>
        </div>
        <QuickAddSubcategories main={main} siblings={subs} items={items} onAddWithOptions={onAddWithOptions} first />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="m-0 text-sm text-tx2">{main.product_count > 0 ? t("directProducts", { count: main.product_count, name: main.name }) : t("subcategoriesHelp", { name: main.name })}</p>
      <div className="overflow-hidden rounded-lg border border-bd">
        <Table>
          <thead>
            <tr>
              <Th className="w-12 text-center">{t("columns.position")}</Th>
              <Th>{t("columns.subcategory")}</Th>
              <Th className="text-right">{t("columns.products")}</Th>
              <Th>{t("columns.status")}</Th>
              <Th className="text-right">{t("columns.actions")}</Th>
            </tr>
          </thead>
          <tbody>
            {subs.map((sub, index) => (
              <tr key={sub.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                <Td className="text-center text-cap text-tx2 tabular-nums">{index + 1}</Td>
                <Td>
                  <span className="flex min-w-0 items-center gap-3">
                    <CategoryImage category={sub} size={36} />
                    <span className="flex min-w-0 flex-col">
                      <span className={cx("font-medium", !sub.is_active && "text-tx2")}>{sub.name}</span>
                      <span className="font-mono text-cap text-tx2">/{sub.slug}</span>
                    </span>
                  </span>
                </Td>
                <Td className="text-right tabular-nums">
                  {sub.product_count > 0 ? (
                    <NextLink href={`/admin/products?category=${sub.id}`} aria-label={t("viewProductsOf", { count: sub.product_count, name: sub.name })} className="font-semibold text-pri-h hover:underline">
                      {sub.product_count}
                    </NextLink>
                  ) : (
                    <span className="text-tx2">0</span>
                  )}
                </Td>
                <Td>
                  <ActiveToggle kind="category" id={sub.id} name={sub.name} active={sub.is_active} showState />
                </Td>
                <Td>
                  <span className="flex items-center justify-end gap-1">
                    <MoveButtons item={sub} items={items} reorder={reorder} />
                    <button type="button" aria-label={t("editOf", { name: sub.name })} title={t("editOf", { name: sub.name })} onClick={() => onEdit(sub)} className={ICON_BUTTON}>
                      <Pencil size={14} aria-hidden="true" />
                    </button>
                  </span>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <div className="border-t border-bd bg-page px-4 py-4">
          <QuickAddSubcategories main={main} siblings={subs} items={items} onAddWithOptions={onAddWithOptions} />
        </div>
      </div>
    </div>
  );
}

/** The brands of a main category (ADR-012 decision 9): who they are, whether its store menu
 * lists them, and adding or removing one here (a brand keeps at least one category). */
function CategoryBrands({ category, brands, onEdit, onNew }: { category: Category; brands: Brand[] | undefined; onEdit: (brand: Brand) => void; onNew: () => void }) {
  const t = useTranslations("admin.catalogue");
  const tc = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const selectId = useId();
  const link = useMutation({
    mutationFn: ({ brand, on }: { brand: Brand; on: boolean }) =>
      must(
        browserApi.PATCH("/api/v1/staff/brands/{brand_id}", {
          params: { path: { brand_id: brand.id } },
          body: { category_ids: on ? [...(brand.category_ids ?? []), category.id] : (brand.category_ids ?? []).filter((id) => id !== category.id) },
        }),
      ),
    onSuccess: (_d, { brand, on }) => toast.show(t(on ? "brandAdded" : "brandRemoved", { brand: brand.name, category: category.name })),
    onError: () => toast.show(tc("common.saveError"), "error"),
    onSettled: () => void client.invalidateQueries({ queryKey: ["admin", "brands"] }),
  });
  if (!brands) return <Skeleton className="h-40 w-full" />;
  const own = brandsOfCategory(brands, category.id);
  const others = brands.filter((b) => b.is_active && !(b.category_ids ?? []).includes(category.id)).sort((a, b) => a.name.localeCompare(b.name));
  const menu = new Set(category.menu_brand_ids ?? []);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="m-0 min-w-0 flex-[1_1_260px] text-sm text-tx2">{t("categoryBrandsHelp", { name: category.name })}</p>
        <Button size="sm" variant="secondary" onClick={onNew} className="gap-1.5">
          <Plus size={15} aria-hidden="true" />
          {t("newBrandIn")}
        </Button>
      </div>
      <div className="overflow-hidden rounded-lg border border-bd">
        {own.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-6 py-8 text-center">
            <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-light text-pri-h">
              <Tag size={22} />
            </span>
            <p className="m-0 font-semibold">{t("noCategoryBrands", { name: category.name })}</p>
          </div>
        ) : (
          <Table aria-busy={link.isPending}>
            <thead>
              <tr>
                <Th>{t("columns.brand")}</Th>
                <Th className="text-right">{t("columns.allProducts")}</Th>
                <Th>{t("columns.storeMenu")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th className="text-right">{t("columns.actions")}</Th>
              </tr>
            </thead>
            <tbody>
              {own.map((brand) => {
                const only = (brand.category_ids ?? []).length <= 1;
                const listed = menu.has(brand.id);
                return (
                  <tr key={brand.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                    <Td>
                      <span className="flex min-w-0 items-center gap-3">
                        <BrandMark brand={brand} size={36} />
                        <span className="flex min-w-0 flex-col">
                          <span className={cx("font-medium", !brand.is_active && "text-tx2")}>{brand.name}</span>
                          <span className="font-mono text-cap text-tx2">/{brand.slug}</span>
                        </span>
                      </span>
                    </Td>
                    <Td className="text-right tabular-nums">
                      {brand.product_count > 0 ? (
                        <NextLink href={`/admin/products?brand=${brand.id}`} aria-label={t("viewProductsOf", { count: brand.product_count, name: brand.name })} className="font-semibold text-pri-h hover:underline">
                          {brand.product_count}
                        </NextLink>
                      ) : (
                        <span className="text-tx2">0</span>
                      )}
                    </Td>
                    <Td>{menu.has(brand.id) ? <Badge tone="soft-info">{t("inMenu")}</Badge> : <span className="text-cap text-tx2">{t("notInMenu")}</span>}</Td>
                    <Td>
                      <ActiveToggle kind="brand" id={brand.id} name={brand.name} active={brand.is_active} showState />
                    </Td>
                    <Td>
                      <span className="flex items-center justify-end gap-1">
                        <button type="button" aria-label={t("editOf", { name: brand.name })} title={t("editOf", { name: brand.name })} onClick={() => onEdit(brand)} className={ICON_BUTTON}>
                          <Pencil size={14} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          aria-label={t("removeBrandFrom", { brand: brand.name, category: category.name })}
                          title={
                            listed
                              ? t("inMenuCannotRemove", { brand: brand.name, category: category.name })
                              : only
                                ? t("onlyCategory", { brand: brand.name, category: category.name })
                                : t("removeBrandFrom", { brand: brand.name, category: category.name })
                          }
                          disabled={listed || only || link.isPending}
                          onClick={() => link.mutate({ brand, on: false })}
                          className={cx(ICON_BUTTON, MOVE_DISABLED)}
                        >
                          <X size={14} aria-hidden="true" />
                        </button>
                      </span>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        <div className="flex flex-wrap items-center gap-3 border-t border-bd bg-page px-4 py-4">
          <label htmlFor={selectId} className="text-sm font-semibold text-tx">
            {t("addExistingBrand")}
          </label>
          <span className="min-w-0 flex-[1_1_240px]">
            <Select
              id={selectId}
              value=""
              disabled={others.length === 0 || link.isPending}
              onChange={(e) => {
                const brand = others.find((b) => b.id === e.target.value);
                if (brand) link.mutate({ brand, on: true });
              }}
            >
              <option value="">{others.length ? t("chooseBrandToAdd", { name: category.name }) : t("allBrandsAdded")}</option>
              {others.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </Select>
          </span>
        </div>
      </div>
    </div>
  );
}

/** What "All Categories" lists beside a main category (ADR-012 decision 8): its brand list,
 * otherwise its subcategories, otherwise the brands of its products. */
function StoreMenuSummary({ category, subs, brands, onEdit }: { category: Category; subs: Category[]; brands: Brand[] | undefined; onEdit: () => void }) {
  const t = useTranslations("admin.catalogue");
  const byId = new Map((brands ?? []).map((b) => [b.id, b]));
  const listed = (category.menu_brand_ids ?? []).map((id) => byId.get(id)).filter((b): b is Brand => Boolean(b));
  const mode = (category.menu_brand_ids ?? []).length ? "brands" : subs.length ? "subcategories" : "productBrands";
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-bd bg-page p-4">
        <div className="flex min-w-0 flex-[1_1_260px] items-start gap-3">
          <span aria-hidden="true" className="flex size-9 flex-none items-center justify-center rounded-lg bg-light text-pri-h">
            {mode === "subcategories" ? <Folder size={17} /> : <Tag size={17} />}
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <b className="text-sm">{t(`menuMode.${mode}.title`)}</b>
            <p className="m-0 text-sm text-tx2">{t(`menuMode.${mode}.body`, { name: category.name })}</p>
          </div>
        </div>
        <Button size="sm" variant="neutral" onClick={onEdit} className="gap-1.5">
          <Pencil size={14} aria-hidden="true" />
          {mode === "brands" ? t("editMenuBrands") : t("chooseMenuBrands")}
        </Button>
      </div>
      {mode === "brands" &&
        (!brands ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <ol className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2" aria-label={t("menuBrands")}>
            {listed.map((brand, index) => (
              <li key={brand.id} className="flex items-center gap-3 rounded-lg border border-bd px-3 py-2">
                <span className="w-5 flex-none text-cap text-tx2 tabular-nums">{index + 1}</span>
                <BrandMark brand={brand} size={32} />
                <span className={cx("min-w-0 flex-1 truncate text-sm font-medium", !brand.is_active && "text-tx2")}>{brand.name}</span>
                {!brand.is_active && <Badge tone="soft-neutral">{t("hiddenBadge")}</Badge>}
              </li>
            ))}
          </ol>
        ))}
      {mode === "subcategories" && (
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label={t("tabs.subcategories")}>
          {subs.map((sub) => (
            <li key={sub.id} className={cx("rounded-full border border-bd px-3 py-1 text-sm", sub.is_active ? "bg-white" : "bg-subtle text-tx2")}>
              {sub.is_active ? sub.name : t("hiddenName", { name: sub.name })}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CategoryDetails({ category, onEdit }: { category: Category; onEdit: () => void }) {
  const t = useTranslations("admin.catalogue");
  const spotlightId = category.spotlight_product_id;
  const spotlight = useQuery({
    queryKey: ["admin", "product", spotlightId],
    queryFn: () => must(browserApi.GET("/api/v1/staff/products/{product_id}", { params: { path: { product_id: spotlightId! } } })),
    enabled: Boolean(spotlightId),
  });
  const row = "flex flex-col gap-1 border-b border-subtle py-3.5 last:border-b-0 sm:flex-row sm:gap-6";
  const label = "m-0 w-48 flex-none text-sm font-medium text-tx2";
  return (
    <div className="flex flex-col gap-3">
      <dl className="m-0">
        <div className={row}>
          <dt className={label}>{t("name")}</dt>
          <dd className="m-0 text-sm">{category.name}</dd>
        </div>
        <div className={row}>
          <dt className={label}>{t("slug")}</dt>
          <dd className="m-0 font-mono text-sm">/{category.slug}</dd>
        </div>
        <div className={row}>
          <dt className={label}>{t("description")}</dt>
          <dd className={cx("m-0 text-sm", !category.description && "text-tx2")}>{category.description || t("noDescription")}</dd>
        </div>
        <div className={row}>
          <dt className={label}>{t("image")}</dt>
          <dd className="m-0 text-sm">
            {category.image ? <Thumb image={{ url: category.image.url, width: category.image.width, height: category.image.height, alt: "", position: 0 }} size={64} /> : <span className="text-tx2">{t("noImage")}</span>}
          </dd>
        </div>
        <div className={row}>
          <dt className={label}>{t("spotlight")}</dt>
          <dd className="m-0 text-sm">{!spotlightId ? <span className="text-tx2">{t("spotlightAuto")}</span> : spotlight.data ? spotlight.data.name : <Skeleton className="h-5 w-40" />}</dd>
        </div>
      </dl>
      <div>
        <Button size="sm" variant="neutral" onClick={onEdit} className="gap-1.5">
          <Pencil size={14} aria-hidden="true" />
          {t("editDetails")}
        </Button>
      </div>
    </div>
  );
}

/** /admin/brands: every brand in one table, with the store menus that list it. */
export function BrandsView() {
  const t = useTranslations("admin.catalogue");
  const brands = useStaffBrands();
  const categories = useStaffCategories();
  const [editing, setEditing] = useState<Brand | "new" | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<CategoryStatus>("all");
  const [category, setCategory] = useState("");
  const all = brands.data?.items ?? [];
  const shown = filterBrands(all, search, status, category);
  const menus = menusByBrand(categories.data?.items ?? []);
  const mains = categoryTree(categories.data?.items ?? [])
    .filter(({ level }) => level === 0)
    .map(({ item }) => item);
  const mainById = new Map(mains.map((c) => [c.id, c]));
  const unlinked = all.filter((b) => !b.category_ids?.length).length;
  return (
    <>
      <CatalogueHeader
        categories={categories.data?.items}
        brands={brands.data?.items}
        action={
          <Button onClick={() => setEditing("new")} className="gap-1.5">
            <Plus size={16} aria-hidden="true" />
            {t("addBrand")}
          </Button>
        }
      />
      <section aria-label={t("brands")} className="min-w-0 overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <FilterBar>
          <label className="relative min-w-0 flex-[1_1_240px]">
            <span className="sr-only">{t("searchBrands")}</span>
            <Search size={15} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-tx2" />
            <Input type="search" value={search} placeholder={t("searchPlaceholder")} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
          </label>
          <label className="min-w-0 flex-[0_1_200px]">
            <span className="sr-only">{t("statusFilter")}</span>
            <Select value={status} onChange={(e) => setStatus(e.target.value as CategoryStatus)}>
              <option value="all">{t("brandStatus.all")}</option>
              <option value="shown">{t("brandStatus.shown")}</option>
              <option value="hidden">{t("brandStatus.hidden")}</option>
            </Select>
          </label>
          <label className="min-w-0 flex-[0_1_220px]">
            <span className="sr-only">{t("categoryFilter")}</span>
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">{t("status.all")}</option>
              {mains.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
              <option value={NO_CATEGORY}>{t("noCategoryYet")}</option>
            </Select>
          </label>
          {brands.data && <span className="ml-auto text-sm text-tx2">{t("brandsShowing", { count: shown.length, total: all.length })}</span>}
        </FilterBar>
        {unlinked > 0 && category !== NO_CATEGORY && (
          <div role="status" className="flex flex-wrap items-center justify-between gap-3 border-b border-warn-bg bg-warn-bg/60 px-5 py-3 text-sm text-warn-tx">
            <span>{t("unlinkedNotice", { count: unlinked })}</span>
            <Button size="sm" variant="neutral" onClick={() => setCategory(NO_CATEGORY)}>
              {t("showUnlinked")}
            </Button>
          </div>
        )}
        {brands.isError ? (
          <LoadError onRetry={() => brands.refetch()} className="m-5" />
        ) : !brands.data ? (
          <div className="flex flex-col gap-2 p-5" aria-busy="true">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : all.length === 0 ? (
          <Empty Icon={Tag}>{t("noBrands")}</Empty>
        ) : shown.length === 0 ? (
          <Empty Icon={Search}>{t("noBrandMatches")}</Empty>
        ) : (
          <Table aria-busy={brands.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.brand")}</Th>
                <Th className="text-right">{t("columns.products")}</Th>
                <Th>{t("columns.categories")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th className="text-right">{t("columns.actions")}</Th>
              </tr>
            </thead>
            <tbody>
              {shown.map((brand) => {
                const inMenus = new Set((menus.get(brand.id) ?? []).map((c) => c.id));
                const homes = (brand.category_ids ?? []).map((id) => mainById.get(id)).filter((c): c is Category => Boolean(c));
                return (
                  <tr key={brand.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                    <Td>
                      <span className="flex min-w-0 items-center gap-3">
                        <BrandMark brand={brand} size={40} />
                        <span className="flex min-w-0 flex-col">
                          <b className={cx("text-sm font-semibold", !brand.is_active && "text-tx2")}>{brand.name}</b>
                          <span className="font-mono text-cap text-tx2">
                            /{brand.slug}
                            {!brand.logo && ` · ${t("noLogo")}`}
                          </span>
                        </span>
                      </span>
                    </Td>
                    <Td className="text-right tabular-nums">
                      {brand.product_count > 0 ? (
                        <NextLink href={`/admin/products?brand=${brand.id}`} aria-label={t("viewProductsOf", { count: brand.product_count, name: brand.name })} className="font-semibold text-pri-h hover:underline">
                          {brand.product_count}
                        </NextLink>
                      ) : (
                        <span className="text-tx2">0</span>
                      )}
                    </Td>
                    <Td>
                      {homes.length ? (
                        <span className="flex flex-wrap gap-1.5">
                          {homes.map((c) => (
                            <NextLink
                              key={c.id}
                              href={`/admin/categories?category=${c.id}&tab=brands`}
                              title={inMenus.has(c.id) ? t("alsoInMenu", { name: c.name }) : undefined}
                              className="inline-flex items-center gap-1 rounded-full bg-light px-2.5 py-0.5 text-cap font-medium whitespace-nowrap text-pri-h no-underline hover:underline"
                            >
                              {c.name}
                              {inMenus.has(c.id) && (
                                <>
                                  <LayoutList size={12} aria-hidden="true" />
                                  <span className="sr-only">{t("inItsMenu")}</span>
                                </>
                              )}
                            </NextLink>
                          ))}
                        </span>
                      ) : (
                        <Badge tone="soft-warn">{t("noCategoryYet")}</Badge>
                      )}
                    </Td>
                    <Td>
                      <ActiveToggle kind="brand" id={brand.id} name={brand.name} active={brand.is_active} showState />
                    </Td>
                    <Td className="text-right">
                      <span className="flex justify-end">
                        <button type="button" aria-label={t("editOf", { name: brand.name })} title={t("editOf", { name: brand.name })} onClick={() => setEditing(brand)} className={ICON_BUTTON}>
                          <Pencil size={14} aria-hidden="true" />
                        </button>
                      </span>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </section>
      {editing && <BrandDialog brand={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

const ICON_BUTTON =
  "flex size-8 flex-none cursor-pointer items-center justify-center rounded-lg border border-bd bg-white text-tx2 transition-colors duration-150 hover:border-pri hover:bg-light hover:text-pri-h motion-reduce:transition-none";

/** The most brands a category's menu may list (CATEGORY_MENU_BRANDS_MAX in the backend). */
const MENU_BRANDS_MAX = 30;

const MOVE_DISABLED = "disabled:cursor-default disabled:opacity-40 disabled:hover:border-bd disabled:hover:bg-white disabled:hover:text-tx2";

function Empty({ Icon, children }: { Icon: LucideIcon; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-subtle text-tx2">
        <Icon size={22} />
      </span>
      <p className="m-0 text-tx2">{children}</p>
    </div>
  );
}

/** The shown/hidden switch; `showState` writes "Shown" or "Hidden" beside it. */
function ActiveToggle({ kind, id, name, active, showState = false }: { kind: "category" | "brand"; id: string; name: string; active: boolean; showState?: boolean }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const change = useMutation({
    mutationFn: async (is_active: boolean): Promise<void> => {
      if (kind === "category") await must(browserApi.PATCH("/api/v1/staff/categories/{category_id}", { params: { path: { category_id: id } }, body: { is_active } }));
      else await must(browserApi.PATCH("/api/v1/staff/brands/{brand_id}", { params: { path: { brand_id: id } }, body: { is_active } }));
    },
    onSuccess: (_d, on) => {
      toast.show(t(on ? "catalogue.shown" : "catalogue.hidden", { name }));
      void client.invalidateQueries({ queryKey: ["admin", kind === "category" ? "categories" : "brands"] });
    },
    onError: () => toast.show(t("common.saveError"), "error"),
  });
  const named = t(kind === "category" ? "catalogue.showCategory" : "catalogue.showBrand", { name });
  return (
    <Toggle
      checked={active}
      disabled={change.isPending}
      onChange={(next) => change.mutate(next)}
      label={
        <>
          {showState && (
            <span aria-hidden="true" className={cx("text-sm font-medium", active ? "text-ok-tx" : "text-tx2")}>
              {active ? t("catalogue.stateShown") : t("catalogue.stateHidden")}
            </span>
          )}
          <span className="sr-only">{named}</span>
        </>
      }
    />
  );
}

/** The category image or brand logo: upload replaces it, remove clears it. */
export function ImagePicker({ label, image, uploadPath, onRemove, onChanged }: { label: string; image: Category["image"]; uploadPath: string; onRemove: () => Promise<unknown>; onChanged: () => void }) {
  const t = useTranslations("admin.catalogue");
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => postFiles(uploadPath, "file", [file]),
    onSuccess: () => {
      toast.show(t("imageSaved"));
      onChanged();
    },
    onError: (error) => toast.show(error instanceof ApiError && error.status === 413 ? t("imageTooLarge") : t("imageFailed"), "error"),
  });
  const remove = useMutation({
    mutationFn: onRemove,
    onSuccess: () => {
      toast.show(t("imageRemoved"));
      onChanged();
    },
    onError: () => toast.show(t("imageFailed"), "error"),
  });
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-3">
        <Thumb image={image ? { url: image.url, width: image.width, height: image.height, alt: "", position: 0 } : null} size={64} />
        <div className="flex flex-wrap gap-2">
          <Button variant="neutral" size="sm" disabled={upload.isPending} onClick={() => input.current?.click()}>
            {image ? t("replaceImage") : t("uploadImage")}
          </Button>
          {image && (
            <Button variant="danger-outline" size="sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {t("removeImage")}
            </Button>
          )}
        </div>
        <input
          ref={input}
          type="file"
          accept={IMAGE_TYPES}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) upload.mutate(file);
          }}
        />
      </div>
      <span className="text-cap text-tx2">{t("imageHint")}</span>
    </div>
  );
}

/** Which dialog tab shows a field, so a refused save opens the tab with the message. */
const DIALOG_TAB_OF: Record<string, DialogTab> = { spotlight_product_id: "media", brand_ids: "menu" };

function CategoryDialog({
  category,
  initialParentId,
  initialTab,
  initialName,
  all,
  onClose,
  onSaved,
  onDeleted,
}: {
  category: Category | null;
  initialParentId: string | null;
  initialTab?: DialogTab;
  initialName?: string;
  all: Category[];
  onClose: () => void;
  onSaved?: (saved: { id: string; parent_id?: string | null }) => void;
  onDeleted?: (deleted: Category) => void;
}) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(category?.name ?? initialName ?? "");
  const [slug, setSlug] = useState(category?.slug ?? "");
  const [parentId, setParentId] = useState(initialParentId ?? "");
  // A new main category can be created with its subcategories, one per line (2026-11-16).
  const [subNames, setSubNames] = useState("");
  const addingMain = !category && !parentId;
  const [description, setDescription] = useState(category?.description ?? "");
  const [active, setActive] = useState(category?.is_active ?? true);
  const [spotlight, setSpotlight] = useState(category?.spotlight_product_id ?? "");
  const [menuBrands, setMenuBrands] = useState<string[]>(category?.menu_brand_ids ?? []);
  const [errors, setErrorsOnly] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<DialogTab>(initialTab ?? "basics");
  const setErrors = (found: Record<string, string>) => {
    setErrorsOnly(found);
    const first = Object.keys(found)[0];
    if (first) setTab(DIALOG_TAB_OF[first] ?? "basics");
  };
  // The latest copy, so the image shows the upload at once.
  const live = useQuery({ queryKey: ["admin", "categories"], queryFn: () => must(browserApi.GET("/api/v1/staff/categories")), enabled: false }).data?.items.find((c) => c.id === category?.id) ?? category;
  // Two levels (2026-11-16): a parent is a main category, and one with subcategories stays main.
  const hasChildren = category ? all.some((c) => c.parent_id === category.id) : false;
  const parents = categoryTree(all).filter(({ item, level }) => level === 0 && item.id !== category?.id);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["admin", "categories"] });
    // A brand added to the store menu now belongs to the category (ADR-012 decision 9).
    void client.invalidateQueries({ queryKey: ["admin", "brands"] });
  };

  // Only a main category has a menu brand list (ADR-012, 2026-11-16).
  const isMain = Boolean(category) && !parentId;
  const menuChanged = isMain && menuBrands.join() !== (category?.menu_brand_ids ?? []).join();
  const save = useMutation({
    mutationFn: async () => {
      const saved = await saveCategory();
      if (menuChanged && category) {
        await must(browserApi.PUT("/api/v1/staff/categories/{category_id}/menu-brands", { params: { path: { category_id: category.id } }, body: { brand_ids: menuBrands } }));
      }
      const { names } = newSubcategoryNames(addingMain ? subNames : "", []);
      const subs = names.length ? await createSubcategories(saved.id, names, 1) : null;
      return { saved, subs };
    },
    onSuccess: ({ saved, subs }) => {
      if (subs?.failed.length) toast.show(t("catalogue.subsNotAdded", { name: name.trim(), names: subs.failed.map((f) => f.name).join(", ") }), "error");
      else if (subs?.added.length) toast.show(t("catalogue.savedWithSubs", { name: name.trim(), count: subs.added.length }));
      else toast.show(t("common.saved"));
      refresh();
      onSaved?.(saved);
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "slug_taken") setErrors({ slug: t("catalogue.errors.slugTaken") });
      else if (error instanceof ApiError && error.status === 409) setErrors({ parent_id: t("catalogue.errors.cycle") });
      else if (error instanceof ApiError && error.status === 422) setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
      // The category may be saved while its menu list was refused: show what is stored now.
      refresh();
    },
  });
  function saveCategory() {
      const parent = parentId || null;
      const body = {
        name: name.trim(),
        parent_id: parent,
        is_active: active,
        description: description.trim() || null,
      };
      // New categories, and categories moved to another parent, go last (the arrows reorder).
      if (!category) return must(browserApi.POST("/api/v1/staff/categories", { body: { ...body, slug: slug.trim() || null, sort_order: nextSortOrder(all, parent) } }));
      const moved = parent !== category.parent_id;
      return must(
        browserApi.PATCH("/api/v1/staff/categories/{category_id}", {
          params: { path: { category_id: category.id } },
          body: {
            ...body,
            spotlight_product_id: spotlight || null,
            ...(moved ? { sort_order: nextSortOrder(all, parent, category.id) } : {}),
            ...(slug.trim() && slug.trim() !== category.slug ? { slug: slug.trim() } : {}),
          },
        }),
      );
  }
  const remove = useMutation({
    mutationFn: () => must(browserApi.DELETE("/api/v1/staff/categories/{category_id}", { params: { path: { category_id: category!.id } } })),
    onSuccess: () => {
      toast.show(t("catalogue.deleted", { name: category!.name }));
      refresh();
      onDeleted?.(category!);
      onClose();
    },
    onError: (error) => toast.show(error instanceof ApiError && error.status === 409 ? t("catalogue.errors.categoryInUse") : t("common.saveError"), "error"),
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = t("catalogue.errors.name");
    if (slug.trim() && !SLUG.test(slug.trim())) found.slug = t("editor.errors.slug");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };

  const basics = (
    <div className="flex flex-col gap-4">
      <Field label={t("catalogue.name")} error={errors.name}>
        {(c) => <Input {...c} maxLength={160} value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <Field label={t("catalogue.parent")} error={errors.parent_id} help={hasChildren ? t("catalogue.parentLocked") : t("catalogue.parentHelp")}>
        {(c) => (
          <Select {...c} value={parentId} disabled={hasChildren} onChange={(e) => setParentId(e.target.value)}>
            <option value="">{t("catalogue.topLevel")}</option>
            {parents.length > 0 && (
              <optgroup label={t("catalogue.underMain")}>
                {parents.map(({ item }) => (
                  <option key={item.id} value={item.id}>
                    {item.is_active ? item.name : t("editor.hiddenOption", { name: item.name })}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
        )}
      </Field>
      <Field label={t("catalogue.slug")} error={errors.slug} help={category ? undefined : t("editor.slugHelp")}>
        {(c) => <Input {...c} maxLength={180} value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} />}
      </Field>
      <Field label={t("catalogue.description")} error={errors.description}>
        {(c) => <Textarea {...c} rows={3} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />}
      </Field>
      {addingMain && (
        <Field label={t("catalogue.newSubcategories")} help={t("catalogue.newSubcategoriesHelp")}>
          {(c) => <Textarea {...c} rows={4} value={subNames} placeholder={t("catalogue.newSubcategoriesPlaceholder")} onChange={(e) => setSubNames(e.target.value)} />}
        </Field>
      )}
      <Checkbox label={t("catalogue.activeCategory")} checked={active} onChange={(e) => setActive(e.target.checked)} />
      {category && category.product_count > 0 && <p className="text-cap text-tx2">{t("catalogue.deleteHint", { count: category.product_count })}</p>}
      {category && hasChildren && <p className="text-cap text-tx2">{t("catalogue.deleteHintChildren")}</p>}
    </div>
  );
  const media = category && (
    <div className="flex flex-col gap-4">
      <ImagePicker
        label={t("catalogue.image")}
        image={live?.image ?? null}
        uploadPath={`staff/categories/${category.id}/image`}
        onRemove={() => must(browserApi.DELETE("/api/v1/staff/categories/{category_id}/image", { params: { path: { category_id: category.id } } }))}
        onChanged={refresh}
      />
      <SpotlightPicker category={category} all={all} value={spotlight} onChange={setSpotlight} error={errors.spotlight_product_id} />
    </div>
  );

  return (
    <Dialog
      open
      onClose={onClose}
      title={category ? t("catalogue.editCategoryOf", { name: category.name }) : initialParentId ? t("catalogue.addSubcategory") : t("catalogue.addMainCategory")}
      closeLabel={t("common.close")}
      className="max-w-[560px]"
      footer={
        <>
          {category && (
            <Button variant="danger-outline" className="mr-auto" disabled={remove.isPending || category.product_count > 0 || hasChildren} onClick={() => remove.mutate()}>
              {t("common.delete")}
            </Button>
          )}
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      {media ? (
        <Tabs
          label={t("catalogue.dialogTabsLabel")}
          value={tab}
          onChange={(id) => setTab(id as DialogTab)}
          items={[
            { id: "basics", label: t("catalogue.dialogTabs.basics"), content: basics },
            { id: "media", label: t("catalogue.dialogTabs.media"), content: media },
            ...(isMain ? [{ id: "menu", label: t("catalogue.dialogTabs.menu"), content: <MenuBrandsPicker value={menuBrands} onChange={setMenuBrands} error={errors.brand_ids} category={category ?? undefined} /> }] : []),
          ]}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {basics}
          <p className="text-cap text-tx2">{t("catalogue.imageAfterSave")}</p>
        </div>
      )}
    </Dialog>
  );
}

/** The brands the store's "All Categories" menu lists under a main category, in order, even
 * before they have products in it (ADR-012, 2026-11-16). Saved with the dialog. */
function MenuBrandsPicker({ value, onChange, error, category }: { value: string[]; onChange: (ids: string[]) => void; error?: string; category?: { id: string; name: string } }) {
  const t = useTranslations("admin.catalogue");
  const te = useTranslations("admin.editor");
  const brands = useQuery({ queryKey: ["admin", "brands"], queryFn: () => must(browserApi.GET("/api/v1/staff/brands")) });
  const byId = new Map((brands.data?.items ?? []).map((b) => [b.id, b]));
  const addable = addableBrands(brands.data?.items ?? [], value);
  const full = value.length >= MENU_BRANDS_MAX;
  return (
    <Field label={t("menuBrands")} error={error} help={t("menuBrandsHelp")}>
      {(c) => (
        <div className="flex flex-col gap-2">
          {value.length === 0 ? (
            <p className="m-0 text-sm text-tx2">{t("noMenuBrands")}</p>
          ) : (
            <ol className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label={t("menuBrands")}>
              {value.map((id, index) => {
                const brand = byId.get(id);
                const name = brand ? (brand.is_active ? brand.name : te("hiddenOption", { name: brand.name })) : "…";
                return (
                  <li key={id} className="flex items-center gap-2 rounded-lg border border-bd bg-white px-3 py-1.5">
                    <span className="w-5 flex-none text-cap text-tx2">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate text-sm">{name}</span>
                    <button type="button" aria-label={t("moveBrandUp", { name })} title={t("moveBrandUp", { name })} disabled={index === 0} onClick={() => onChange(moveItem(value, index, -1))} className={cx(ICON_BUTTON, MOVE_DISABLED)}>
                      <ChevronUp size={15} aria-hidden="true" />
                    </button>
                    <button type="button" aria-label={t("moveBrandDown", { name })} title={t("moveBrandDown", { name })} disabled={index === value.length - 1} onClick={() => onChange(moveItem(value, index, 1))} className={cx(ICON_BUTTON, MOVE_DISABLED)}>
                      <ChevronDown size={15} aria-hidden="true" />
                    </button>
                    <button type="button" aria-label={t("removeMenuBrand", { name })} title={t("removeMenuBrand", { name })} onClick={() => onChange(value.filter((b) => b !== id))} className={ICON_BUTTON}>
                      <X size={15} aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
          <Select {...c} value="" disabled={brands.isPending || addable.length === 0 || full} onChange={(e) => e.target.value && onChange([...value, e.target.value])}>
            <option value="">{full ? t("menuBrandsFull", { max: MENU_BRANDS_MAX }) : t("addMenuBrand")}</option>
            {(() => {
              // The category's own brands first (ADR-012 decision 9), then every other brand.
              const own = category ? addable.filter((b) => (b.category_ids ?? []).includes(category.id)) : [];
              const rest = addable.filter((b) => !own.includes(b));
              const opts = (list: typeof addable) =>
                list.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ));
              if (!category || own.length === 0) return opts(addable);
              return (
                <>
                  <optgroup label={t("brandsInCategory", { name: category.name })}>{opts(own)}</optgroup>
                  {rest.length > 0 && <optgroup label={t("otherBrandsJoin", { name: category.name })}>{opts(rest)}</optgroup>}
                </>
              );
            })()}
          </Select>
        </div>
      )}
    </Field>
  );
}

/** The product the home page's spotlight showcases for a category: any product of the category
 * or its subcategories (only a published one appears on the store), or none for the best seller. */
function SpotlightPicker({ category, all, value, onChange, error }: { category: Category; all: Category[]; value: string; onChange: (id: string) => void; error?: string }) {
  const t = useTranslations("admin");
  const tree = categoryTree(all).filter(({ item }) => descendants(all, category.id).has(item.id));
  const products = useQuery({
    queryKey: ["admin", "spotlight-products", category.id, tree.map(({ item }) => item.id).join()],
    queryFn: () =>
      Promise.all(
        tree.map(async ({ item }) => ({
          category: item,
          items: (await must(browserApi.GET("/api/v1/staff/products", { params: { query: { category_id: item.id, size: 100 } } }))).items.sort((a, b) => a.name.localeCompare(b.name)),
        })),
      ),
  });
  const groups = (products.data ?? []).filter((g) => g.items.length > 0);
  return (
    <Field label={t("catalogue.spotlight")} error={error} help={t("catalogue.spotlightHelp")}>
      {(c) => (
        <Select {...c} value={value} disabled={products.isPending} onChange={(e) => onChange(e.target.value)}>
          <option value="">{t("catalogue.spotlightAuto")}</option>
          {groups.map((group) => (
            <optgroup key={group.category.id} label={group.category.name}>
              {group.items.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.status === "active" ? product.name : t("catalogue.spotlightUnpublished", { name: product.name })}
                </option>
              ))}
            </optgroup>
          ))}
        </Select>
      )}
    </Field>
  );
}

function BrandDialog({ brand, initialCategoryIds, onClose }: { brand: Brand | null; initialCategoryIds?: string[]; onClose: () => void }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(brand?.name ?? "");
  const [slug, setSlug] = useState(brand?.slug ?? "");
  const [active, setActive] = useState(brand?.is_active ?? true);
  // The main categories it belongs to, at least one (ADR-012 decision 9, 2026-11-17).
  const [categoryIds, setCategoryIds] = useState<string[]>(brand?.category_ids?.length ? brand.category_ids : (initialCategoryIds ?? []));
  const categoriesNoteId = useId();
  const categories = useStaffCategories();
  const mains = categoryTree(categories.data?.items ?? [])
    .filter(({ level }) => level === 0)
    .map(({ item }) => item);
  // Sent in menu order; only sent on an edit when the choice changed.
  const ordered = mains.filter((c) => categoryIds.includes(c.id)).map((c) => c.id);
  const categoriesChanged = [...ordered].sort().join() !== [...(brand?.category_ids ?? [])].sort().join();
  const inMenuOf = new Set(brand ? mains.filter((c) => (c.menu_brand_ids ?? []).includes(brand.id)).map((c) => c.id) : []);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const live = useQuery({ queryKey: ["admin", "brands"], queryFn: () => must(browserApi.GET("/api/v1/staff/brands")), enabled: false }).data?.items.find((b) => b.id === brand?.id) ?? brand;
  const refresh = () => void client.invalidateQueries({ queryKey: ["admin", "brands"] });
  const save = useMutation({
    mutationFn: () => {
      if (!brand) return must(browserApi.POST("/api/v1/staff/brands", { body: { name: name.trim(), slug: slug.trim() || null, is_active: active, category_ids: ordered } }));
      return must(
        browserApi.PATCH("/api/v1/staff/brands/{brand_id}", {
          params: { path: { brand_id: brand.id } },
          body: {
            name: name.trim(),
            is_active: active,
            ...(slug.trim() && slug.trim() !== brand.slug ? { slug: slug.trim() } : {}),
            ...(categoriesChanged ? { category_ids: ordered } : {}),
          },
        }),
      );
    },
    onSuccess: () => {
      toast.show(t("common.saved"));
      refresh();
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "slug_taken") setErrors({ slug: t("catalogue.errors.slugTaken") });
      else if (error instanceof ApiError && error.status === 422) setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
    },
  });
  const remove = useMutation({
    mutationFn: () => must(browserApi.DELETE("/api/v1/staff/brands/{brand_id}", { params: { path: { brand_id: brand!.id } } })),
    onSuccess: () => {
      toast.show(t("catalogue.deleted", { name: brand!.name }));
      refresh();
      onClose();
    },
    onError: (error) => toast.show(error instanceof ApiError && error.status === 409 ? t("catalogue.errors.brandInUse") : t("common.saveError"), "error"),
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = t("catalogue.errors.name");
    if (slug.trim() && !SLUG.test(slug.trim())) found.slug = t("editor.errors.slug");
    if (ordered.length === 0) found.category_ids = t("catalogue.errors.brandCategories");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={brand ? t("catalogue.editBrand") : t("catalogue.addBrand")}
      closeLabel={t("common.close")}
      footer={
        <>
          {brand && (
            <Button variant="danger-outline" className="mr-auto" disabled={remove.isPending || brand.product_count > 0} onClick={() => remove.mutate()}>
              {t("common.delete")}
            </Button>
          )}
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label={t("catalogue.name")} error={errors.name}>
          {(c) => <Input {...c} maxLength={160} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label={t("catalogue.slug")} error={errors.slug} help={brand ? undefined : t("editor.slugHelp")}>
          {(c) => <Input {...c} maxLength={180} value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} />}
        </Field>
        <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" aria-describedby={categoriesNoteId} aria-invalid={errors.category_ids ? true : undefined}>
          <legend className="mb-1.5 p-0 text-sm font-medium text-tx">{t("catalogue.brandCategories")}</legend>
          {!categories.data ? (
            <Skeleton className="h-20 w-full" />
          ) : (
            <div className="grid gap-2 rounded-lg border border-bd p-3 sm:grid-cols-2">
              {mains.map((c) => (
                <Checkbox
                  key={c.id}
                  label={
                    <>
                      {c.is_active ? c.name : t("editor.hiddenOption", { name: c.name })}
                      {inMenuOf.has(c.id) && categoryIds.includes(c.id) && <span className="text-cap text-tx2"> {t("catalogue.inItsMenuShort")}</span>}
                    </>
                  }
                  title={inMenuOf.has(c.id) && categoryIds.includes(c.id) ? t("catalogue.inMenuCannotRemove", { brand: brand?.name ?? "", category: c.name }) : undefined}
                  disabled={inMenuOf.has(c.id) && categoryIds.includes(c.id)}
                  checked={categoryIds.includes(c.id)}
                  onChange={(e) => setCategoryIds((prev) => (e.target.checked ? [...prev, c.id] : prev.filter((id) => id !== c.id)))}
                />
              ))}
            </div>
          )}
          <span id={categoriesNoteId} className={cx("text-cap", errors.category_ids ? "text-err" : "text-mut")}>
            {errors.category_ids ?? t("catalogue.brandCategoriesHelp")}
          </span>
        </fieldset>
        <Checkbox label={t("catalogue.activeBrand")} checked={active} onChange={(e) => setActive(e.target.checked)} />
        {brand ? (
          <ImagePicker
            label={t("catalogue.logo")}
            image={live?.logo ?? null}
            uploadPath={`staff/brands/${brand.id}/logo`}
            onRemove={() => must(browserApi.DELETE("/api/v1/staff/brands/{brand_id}/logo", { params: { path: { brand_id: brand.id } } }))}
            onChanged={refresh}
          />
        ) : (
          <p className="text-cap text-tx2">{t("catalogue.logoAfterSave")}</p>
        )}
        {brand && brand.product_count > 0 && <p className="text-cap text-tx2">{t("catalogue.deleteHint", { count: brand.product_count })}</p>}
      </div>
    </Dialog>
  );
}
