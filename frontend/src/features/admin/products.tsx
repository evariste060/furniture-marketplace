"use client";

import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckSquare, ExternalLink, ImageOff, Layers, PackageSearch, Pencil, Rocket, Upload, X, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Checkbox, Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { Toggle } from "@/components/ui/toggle";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { useStaffAccess } from "./access";
import { ListFooter, LoadError, must, PageHeader, SearchBox, Thumb, useListParams } from "./ui";

type ProductRow = components["schemas"]["StaffProductListItem"];
export type ProductStatus = ProductRow["status"];

const PAGE_SIZE = 20;
/** The backend's BULK_ACTIVATE_MAX. */
const BULK_ACTIVATE_MAX = 200;
export const PRODUCT_STATUSES: ProductStatus[] = ["active", "hidden", "draft", "archived"];
export const PRODUCT_TONE: Record<ProductStatus, BadgeTone> = { active: "soft-ok", hidden: "soft-neutral", draft: "soft-warn", archived: "soft-neutral" };

/** The two working views over the list (frontend plan, phase 6). */
const VIEWS = {
  "": {},
  "missing-images": { status: "active", has_images: false },
  "ready-to-publish": { status: "draft", has_images: true },
} as const;
type View = keyof typeof VIEWS;
const VIEW_IDS = Object.keys(VIEWS) as View[];

/** The view tiles: label key, hint key, icon and colours. */
const VIEW_TILE: Record<View, { key: string; Icon: LucideIcon; tone: string }> = {
  "": { key: "all", Icon: Layers, tone: "bg-light text-pri-h" },
  "missing-images": { key: "missingImages", Icon: ImageOff, tone: "bg-warn-bg text-warn-tx" },
  "ready-to-publish": { key: "readyToPublish", Icon: Rocket, tone: "bg-ok-bg text-ok-tx" },
};

function isView(value: string): value is View {
  return value in VIEWS;
}
function isStatus(value: string): value is ProductStatus {
  return (PRODUCT_STATUSES as string[]).includes(value);
}

/** Products.dc.html. Filters live in the URL: view, status, q, category, brand, low, page. */
export function ProductsView() {
  const t = useTranslations("admin");
  const { can } = useStaffAccess();
  const manage = can("catalog:manage");
  const { get, page, set, hrefWith } = useListParams();
  const view: View = isView(get("view")) ? (get("view") as View) : "";
  const status = isStatus(get("status")) ? (get("status") as ProductStatus) : "";
  const q = get("q");
  const categoryId = get("category");
  const brandId = get("brand");
  const lowStock = get("low") === "1";
  const shared = {
    q: q || undefined,
    category_id: categoryId || undefined,
    brand_id: brandId || undefined,
    low_stock: lowStock || undefined,
  };
  const query = { ...shared, status: status || undefined, ...VIEWS[view] };

  const list = useQuery({
    queryKey: ["admin", "products", { ...query, page }],
    queryFn: () => must(browserApi.GET("/api/v1/staff/products", { params: { query: { ...query, page, size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
  });
  // Each view's count under the search, category, brand and low-stock filters.
  const counts = useQueries({
    queries: VIEW_IDS.map((v) => ({
      queryKey: ["admin", "products", "count", v, shared],
      queryFn: async () => (await must(browserApi.GET("/api/v1/staff/products", { params: { query: { ...shared, ...VIEWS[v], size: 1 } } }))).total,
    })),
  });
  const categories = useQuery({ queryKey: ["admin", "categories"], queryFn: () => must(browserApi.GET("/api/v1/staff/categories")), staleTime: 60_000 });
  const brands = useQuery({ queryKey: ["admin", "brands"], queryFn: () => must(browserApi.GET("/api/v1/staff/brands")), staleTime: 60_000 });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const rows = list.data?.items ?? [];
  const allOnPage = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const toggleRow = (id: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const filtered = Boolean(q || categoryId || brandId || lowStock || status);

  return (
    <>
      <PageHeader
        title={t("products.title")}
        description={t("products.description")}
        actions={
          manage && (
            // Administrators moderate products but do not create them (SC-05): sellers add products
            // to their own store, so there is no New product action here.
            <>
              <NextLink href="/admin/import" className={buttonClasses({ variant: "neutral", size: "sm", className: "gap-2" })}>
                <Upload size={16} aria-hidden="true" />
                {t("products.import")}
              </NextLink>
            </>
          )
        }
      />

      {/* The working views: each tile switches the list. */}
      <div role="group" aria-label={t("products.viewsLabel")} className="grid gap-3 sm:grid-cols-3">
        {VIEW_IDS.map((v, i) => {
          const on = v === view;
          const { key, Icon, tone } = VIEW_TILE[v];
          const n = counts[i].data;
          return (
            <button
              key={v || "all"}
              type="button"
              aria-pressed={on}
              onClick={() => {
                setSelected(new Set());
                set({ view: v, status: null });
              }}
              className={cx(
                "flex cursor-pointer items-center gap-3.5 rounded-xl border p-4 text-left shadow-sh transition-[border-color,box-shadow,background-color] duration-150 motion-reduce:transition-none",
                on ? "border-pri bg-light ring-1 ring-pri" : "border-bd bg-white hover:border-bd2 hover:shadow-sh2",
              )}
            >
              <span aria-hidden="true" className={cx("flex size-11 flex-none items-center justify-center rounded-xl", tone)}>
                <Icon size={20} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className={cx("truncate text-sm font-semibold", on ? "text-pri-h" : "text-tx")}>{t(`products.views.${key}`)}</span>
                <span className="truncate text-cap text-tx2">{t(`products.viewHints.${key}`)}</span>
              </span>
              {n === undefined ? <Skeleton className="h-7 w-10" /> : <b className="t-h2 tabular-nums">{n.toLocaleString("en-US")}</b>}
            </button>
          );
        })}
      </div>

      <section className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <div className="flex flex-wrap items-end gap-3 border-b border-bd p-4">
          <Filter label={t("products.searchLabel")} className="flex-[1_1_200px] sm:max-w-[300px]">
            {() => <SearchBox label={t("products.searchLabel")} placeholder={t("products.searchPlaceholder")} value={q} onSearch={(value) => set({ q: value })} className="h-10 max-w-none flex-none" />}
          </Filter>
          <Filter label={t("products.category")} className="sm:w-40">
            {(id) => (
              <Select id={id} value={categoryId} onChange={(e) => set({ category: e.target.value })} className="h-10 text-sm">
                <option value="">{t("products.allCategories")}</option>
                {categories.data?.items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.parent_id ? `– ${c.name}` : c.name}
                  </option>
                ))}
              </Select>
            )}
          </Filter>
          <Filter label={t("products.brand")} className="sm:w-36">
            {(id) => (
              <Select id={id} value={brandId} onChange={(e) => set({ brand: e.target.value })} className="h-10 text-sm">
                <option value="">{t("products.allBrands")}</option>
                {brands.data?.items.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            )}
          </Filter>
          {view === "" && (
            <Filter label={t("products.statusLabel")} className="sm:w-36">
              {(id) => (
                <Select id={id} value={status} onChange={(e) => set({ status: e.target.value })} className="h-10 text-sm">
                  <option value="">{t("products.allStatuses")}</option>
                  {PRODUCT_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {t(`products.status.${s}`)}
                    </option>
                  ))}
                </Select>
              )}
            </Filter>
          )}
          <Checkbox
            label={t("products.lowOnly")}
            checked={lowStock}
            onChange={(e) => set({ low: e.target.checked ? "1" : null })}
            className={cx(
              "h-10 rounded-lg border px-3 font-medium transition-colors duration-150 motion-reduce:transition-none",
              lowStock ? "border-pri bg-light text-pri-h" : "border-bd hover:border-bd2",
            )}
          />
          <div className="ml-auto flex h-10 items-center gap-3 max-sm:w-full max-sm:justify-between">
            {list.data && (
              <span aria-live="polite" className="text-sm text-tx2 tabular-nums">
                {t("products.count", { count: list.data.total })}
              </span>
            )}
            {filtered && (
              <Button variant="neutral" size="sm" onClick={() => set({ q: null, category: null, brand: null, low: null, status: null })} className="gap-1.5">
                <X size={14} aria-hidden="true" />
                {t("products.clearFilters")}
              </Button>
            )}
          </div>
        </div>

        {manage && selected.size > 0 && <BulkBar ids={[...selected]} onDone={() => setSelected(new Set())} />}

        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <PackageSearch size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{t("products.empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                {manage && (
                  <Th className="w-10">
                    <input
                      type="checkbox"
                      aria-label={t("products.selectAll")}
                      className="m-0 size-4 accent-pri"
                      checked={allOnPage}
                      onChange={(e) => rows.forEach((r) => toggleRow(r.id, e.target.checked))}
                    />
                  </Th>
                )}
                <Th>{t("products.columns.product")}</Th>
                <Th>{t("products.columns.category")}</Th>
                <Th className="text-right">{t("products.columns.price")}</Th>
                <Th>{t("products.columns.stock")}</Th>
                <Th>{t("products.columns.status")}</Th>
                <Th>{t("products.columns.visible")}</Th>
                <Th>
                  <span className="sr-only">{t("common.actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={manage ? 8 : 7}>
                        <Skeleton className="h-12 w-full" />
                      </Td>
                    </tr>
                  ))
                : rows.map((p) => {
                    const picked = selected.has(p.id);
                    return (
                      <tr key={p.id} className={cx("transition-colors duration-150 motion-reduce:transition-none", picked ? "bg-light" : "hover:bg-page")}>
                        {manage && (
                          <Td>
                            <input
                              type="checkbox"
                              aria-label={t("products.select", { name: p.name })}
                              className="m-0 size-4 accent-pri"
                              checked={picked}
                              onChange={(e) => toggleRow(p.id, e.target.checked)}
                            />
                          </Td>
                        )}
                        <Td>
                          <span className="flex items-center gap-3">
                            <Thumb image={p.image} size={48} />
                            <span className="flex min-w-0 flex-col gap-0.5">
                              <NextLink href={`/admin/products/${p.id}`} className="line-clamp-2 font-semibold text-tx no-underline hover:text-pri-h hover:underline">
                                {p.name}
                              </NextLink>
                              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-cap text-tx2">
                                {p.sku && <span className="font-mono">{p.sku}</span>}
                                {p.variant_count > 1 && (
                                  <span className="rounded bg-subtle px-1.5 py-px font-medium">{t("products.variants", { count: p.variant_count })}</span>
                                )}
                                {p.image_count === 0 && (
                                  <span className="flex items-center gap-1 font-semibold text-warn-tx">
                                    <ImageOff size={12} aria-hidden="true" />
                                    {t("products.noPhotos")}
                                  </span>
                                )}
                              </span>
                            </span>
                          </span>
                        </Td>
                        <Td>
                          <span className="flex flex-col">
                            <span className="text-tx">{p.category.name}</span>
                            <span className="text-cap text-tx2">{p.brand?.name ?? t("products.noBrand")}</span>
                          </span>
                        </Td>
                        <Td className="text-right font-semibold whitespace-nowrap tabular-nums">{p.price == null ? <span className="font-normal text-tx2">—</span> : formatMoney(p.price)}</Td>
                        <Td>
                          <Stock product={p} />
                        </Td>
                        <Td>
                          <Badge tone={PRODUCT_TONE[p.status]}>{t(`products.status.${p.status}`)}</Badge>
                        </Td>
                        <Td>
                          <VisibleToggle product={p} disabled={!manage} />
                        </Td>
                        <Td>
                          <span className="flex items-center justify-end gap-1.5">
                            <NextLink
                              href={`/admin/products/${p.id}`}
                              aria-label={t(manage ? "products.edit" : "products.open", { name: p.name })}
                              title={t(manage ? "products.edit" : "products.open", { name: p.name })}
                              className="flex size-8 items-center justify-center rounded-lg border border-bd bg-white text-tx2 transition-colors duration-150 hover:border-pri hover:bg-light hover:text-pri-h motion-reduce:transition-none"
                            >
                              <Pencil size={15} aria-hidden="true" />
                            </NextLink>
                            {p.status === "active" ? (
                              <a
                                href={`/product/${p.slug}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label={t("products.view", { name: p.name })}
                                title={t("products.view", { name: p.name })}
                                className="flex size-8 items-center justify-center rounded-lg border border-bd bg-white text-tx2 transition-colors duration-150 hover:border-pri hover:bg-light hover:text-pri-h motion-reduce:transition-none"
                              >
                                <ExternalLink size={15} aria-hidden="true" />
                              </a>
                            ) : (
                              <span aria-hidden="true" className="size-8" />
                            )}
                          </span>
                        </Td>
                      </tr>
                    );
                  })}
            </tbody>
          </Table>
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
    </>
  );
}

/** Units available, with an out-of-stock or low-stock note. */
function Stock({ product }: { product: ProductRow }) {
  const t = useTranslations("admin.products");
  const n = product.available_quantity;
  const out = n === 0;
  const low = !out && product.has_low_stock;
  return (
    <span className="flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden="true" className={cx("size-2 flex-none rounded-full", out ? "bg-err" : low ? "bg-warn" : "bg-ok")} />
      <b className={cx("font-semibold tabular-nums", out && "text-err-tx")}>{n}</b>
      {out ? <span className="text-cap font-medium text-err-tx">{t("outOfStock")}</span> : low && <Badge tone="soft-err">{t("low")}</Badge>}
    </span>
  );
}

/** A labelled filter control. */
function Filter({ label, className, children }: { label: string; className?: string; children: (id: string) => ReactNode }) {
  const id = `products-filter-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className={cx("flex min-w-0 flex-col gap-1 max-sm:flex-1", className)}>
      <label htmlFor={id} className="text-cap font-semibold text-tx2">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/** "Visible": an active product is on the store; switching it off hides it. Drafts and archived
 * products are published from the editor or the bulk action. */
function VisibleToggle({ product, disabled }: { product: ProductRow; disabled: boolean }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const change = useMutation({
    mutationFn: (status: "active" | "hidden") =>
      must(browserApi.PATCH("/api/v1/staff/products/{product_id}", { params: { path: { product_id: product.id } }, body: { status } })),
    onSuccess: (_d, status) => {
      toast.show(t(status === "active" ? "products.shown" : "products.hidden", { name: product.name }));
      void client.invalidateQueries({ queryKey: ["admin", "products"] });
    },
    onError: (error) => toast.show(error instanceof ApiError && error.code === "product_has_no_images" ? t("products.needsPhoto") : t("common.saveError"), "error"),
  });
  const on = product.status === "active";
  const canSwitch = !disabled && (product.status === "active" || product.status === "hidden");
  return (
    <Toggle
      checked={on}
      disabled={!canSwitch || change.isPending}
      onChange={(next) => change.mutate(next ? "active" : "hidden")}
      label={<span className="sr-only">{t("products.showOnStore", { name: product.name })}</span>}
    />
  );
}

/** Publishes the selected products; ones without a photo are skipped (backend rule). */
function BulkBar({ ids, onDone }: { ids: string[]; onDone: () => void }) {
  const t = useTranslations("admin.products");
  const client = useQueryClient();
  const toast = useToast();
  const activate = useMutation({
    mutationFn: () => must(browserApi.POST("/api/v1/staff/products/bulk-activate", { body: { product_ids: ids } })),
    onSuccess: (result) => {
      toast.show(t("bulkResult", { activated: result.activated, skipped: result.skipped_no_images, already: result.already_active }), result.skipped_no_images ? "info" : "success");
      onDone();
      void client.invalidateQueries({ queryKey: ["admin", "products"] });
    },
    onError: () => toast.show(t("bulkFailed"), "error"),
  });
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-pri/30 bg-light px-5 py-3">
      <span className="flex items-center gap-2.5">
        <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-lg bg-pri text-white">
          <CheckSquare size={16} />
        </span>
        <span className="flex flex-col">
          <b className="text-sm font-semibold text-navy">{t("selected", { count: ids.length })}</b>
          <span className="text-cap text-tx2">{t("bulkHint")}</span>
        </span>
      </span>
      <div className="flex gap-2.5">
        <Button variant="neutral" size="sm" onClick={onDone}>
          {t("clearSelection")}
        </Button>
        <Button size="sm" disabled={activate.isPending || ids.length > BULK_ACTIVATE_MAX} onClick={() => activate.mutate()} className="gap-1.5">
          <Rocket size={14} aria-hidden="true" />
          {t("publishSelected")}
        </Button>
      </div>
    </div>
  );
}
