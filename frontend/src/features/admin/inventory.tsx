"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Boxes, Minus, PackageCheck, Plus, SlidersHorizontal, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, RadioOption, Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { useCatalogScope } from "./catalog-scope";
import { ListFooter, LoadError, PageHeader, SearchBox, useListParams } from "./ui";

type StockRow = components["schemas"]["InventoryListItem"];
type Reason = components["schemas"]["StockAdjustmentRequest"]["reason"];

const PAGE_SIZE = 20;
/** The backend's MAX_QUANTITY (a PostgreSQL integer). */
const QUANTITY_MAX = 2_147_483_647;

/** Inventory.dc.html "Reason": the backend keeps receipt, adjustment or inspected return; the
 * chosen wording goes into the note so the ledger keeps it. */
export const REASONS = {
  add: [
    { id: "delivery", reason: "receipt" },
    { id: "returned", reason: "inspected_return" },
    { id: "count", reason: "adjustment" },
  ],
  remove: [
    { id: "damaged", reason: "adjustment" },
    { id: "count", reason: "adjustment" },
  ],
} as const satisfies Record<"add" | "remove", readonly { id: string; reason: Reason }[]>;

/** The "N left" badge colour of Inventory.dc.html. */
export function availableTone(row: Pick<StockRow, "available_quantity" | "is_low_stock">): BadgeTone {
  if (row.available_quantity <= 0) return "soft-err";
  return row.is_low_stock ? "soft-warn" : "soft-ok";
}

/** The bar colour that goes with availableTone. */
const BAR: Partial<Record<BadgeTone, string>> = { "soft-err": "bg-err", "soft-warn": "bg-warn", "soft-ok": "bg-ok" };

const VIEWS: { id: "low" | "all"; Icon: LucideIcon; tone: string }[] = [
  { id: "low", Icon: AlertTriangle, tone: "bg-warn-bg text-warn-tx" },
  { id: "all", Icon: Boxes, tone: "bg-light text-pri-h" },
];

/** Inventory.dc.html. The URL holds q, view and page. Also the seller's /seller/inventory
 * (ADR-014 phase 4): their own store's SKUs only. */
export function InventoryView() {
  const t = useTranslations("admin.inventory");
  const scope = useCatalogScope();
  const { get, page, set, hrefWith } = useListParams();
  const q = get("q");
  // The design opens on "Low stock"; a search looks at every SKU unless low stock is chosen.
  const view = get("view") === "low" || get("view") === "all" ? get("view") : q ? "all" : "low";
  const [adjusting, setAdjusting] = useState<StockRow | null>(null);
  const list = useQuery({
    queryKey: [scope.key, "inventory", { q, view, page }],
    queryFn: () => scope.api.inventory({ q: q || undefined, low_stock: view === "low" ? true : undefined, page, size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const totals = useQuery({
    queryKey: [scope.key, "inventory", "totals"],
    queryFn: async () => {
      const [all, low] = await Promise.all([scope.api.inventory({ size: 1 }), scope.api.inventory({ size: 1, low_stock: true })]);
      return { all: all.total, low: low.total };
    },
  });
  const { adjust } = scope;
  const columns = adjust ? 6 : 5;

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />

      {/* The two views, with their totals: each tile switches the list. */}
      <div role="group" aria-label={t("viewLabel")} className="grid gap-3 sm:grid-cols-2">
        {VIEWS.map(({ id, Icon, tone }) => {
          const on = view === id;
          const n = totals.data?.[id];
          return (
            <button
              key={id}
              type="button"
              aria-pressed={on}
              onClick={() => set({ view: id })}
              className={cx(
                "flex cursor-pointer items-center gap-4 rounded-xl border p-4 text-left shadow-sh transition-[border-color,box-shadow,background-color] duration-150 motion-reduce:transition-none",
                on ? "border-pri bg-light ring-1 ring-pri" : "border-bd bg-card hover:border-bd2 hover:shadow-sh2",
              )}
            >
              <span aria-hidden="true" className={cx("flex size-12 flex-none items-center justify-center rounded-xl", tone)}>
                <Icon size={22} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className={cx("text-sm font-semibold", on ? "text-pri-h" : "text-tx")}>{t(`tiles.${id}`)}</span>
                <span className="text-cap text-tx2">{t(`tileHints.${id}`)}</span>
              </span>
              {n === undefined ? (
                <Skeleton className="h-8 w-12" />
              ) : (
                <b className={cx("t-h1 tabular-nums", id === "low" && n > 0 && "text-warn-tx")}>{n.toLocaleString("en-US")}</b>
              )}
            </button>
          );
        })}
      </div>

      <section className="overflow-hidden rounded-xl border border-bd bg-card shadow-sh">
        <div className="flex flex-wrap items-end gap-3 border-b border-bd p-4">
          <div className="flex min-w-0 flex-[1_1_260px] flex-col gap-1 sm:max-w-[380px]">
            <span aria-hidden="true" className="text-cap font-semibold text-tx2">
              {t("searchLabel")}
            </span>
            <SearchBox label={t("searchLabel")} placeholder={t("searchPlaceholder")} value={q} onSearch={(value) => set({ q: value, view: value ? "all" : null })} className="h-10 max-w-none flex-none" />
          </div>
          {list.data && (
            <span aria-live="polite" className="ml-auto flex h-10 items-center text-sm text-tx2 tabular-nums">
              {t("count", { count: list.data.total })}
            </span>
          )}
        </div>

        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && list.data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className={cx("flex size-14 items-center justify-center rounded-full", view === "low" && !q ? "bg-ok-bg text-ok-tx" : "bg-subtle text-tx2")}>
              {view === "low" && !q ? <PackageCheck size={26} /> : <Boxes size={26} />}
            </span>
            <p className="m-0 max-w-96 text-tx2">{view === "low" && !q ? t("noLow") : t("empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.product")}</Th>
                <Th>{t("columns.sku")}</Th>
                <Th className="text-right">{t("columns.onHand")}</Th>
                <Th className="text-right">{t("columns.reserved")}</Th>
                <Th>{t("columns.available")}</Th>
                {adjust && (
                  <Th>
                    <span className="sr-only">{t("columns.actions")}</span>
                  </Th>
                )}
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={columns}>
                        <Skeleton className="h-10 w-full" />
                      </Td>
                    </tr>
                  ))
                : list.data.items.map((row) => {
                    const tone = availableTone(row);
                    const reserved = row.reserved_quantity + row.committed_quantity;
                    const share = row.on_hand > 0 ? Math.max(0, Math.min(1, row.available_quantity / row.on_hand)) : 0;
                    return (
                      <tr key={row.variant_id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                        <Td>
                          <span className="flex flex-col gap-0.5">
                            <b className="font-semibold">{row.product_name}</b>
                            <span className="flex flex-wrap items-center gap-2 text-cap text-tx2">
                              {row.variant_name}
                              {!row.is_sellable && <span className="rounded bg-subtle px-1.5 py-px font-medium">{t("notForSale")}</span>}
                            </span>
                          </span>
                        </Td>
                        <Td className="font-mono text-cap whitespace-nowrap text-tx2">{row.sku}</Td>
                        <Td className="text-right font-semibold tabular-nums">{row.on_hand}</Td>
                        <Td className={cx("text-right tabular-nums", reserved > 0 ? "text-tx" : "text-tx2")}>{reserved}</Td>
                        <Td>
                          <span className="flex min-w-36 flex-col gap-1.5">
                            <span className="flex items-center justify-between gap-2">
                              <Badge tone={tone}>{t("left", { count: row.available_quantity })}</Badge>
                              {row.low_stock_threshold > 0 && <span className="text-cap whitespace-nowrap text-tx2">{t("alertAt", { count: row.low_stock_threshold })}</span>}
                            </span>
                            <span aria-hidden="true" className="h-1.5 overflow-hidden rounded-full bg-subtle">
                              <span className={cx("block h-full rounded-full", BAR[tone])} style={{ width: `${Math.round(share * 100)}%` }} />
                            </span>
                          </span>
                        </Td>
                        {adjust && (
                          <Td className="text-right">
                            <Button variant="outline" size="sm" onClick={() => setAdjusting(row)} aria-label={t("adjustOf", { sku: row.sku })} className="gap-1.5">
                              <SlidersHorizontal size={14} aria-hidden="true" />
                              {t("adjust")}
                            </Button>
                          </Td>
                        )}
                      </tr>
                    );
                  })}
            </tbody>
          </Table>
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
      {adjusting && <AdjustDialog row={adjusting} onClose={() => setAdjusting(null)} />}
    </>
  );
}

/** Inventory.dc.html "Adjust stock". One Idempotency-Key per dialog, so a retried save after a
 * lost response is applied once. */
function AdjustDialog({ row, onClose }: { row: StockRow; onClose: () => void }) {
  const t = useTranslations("admin");
  const scope = useCatalogScope();
  const client = useQueryClient();
  const toast = useToast();
  const [direction, setDirection] = useState<"add" | "remove">("add");
  const [quantity, setQuantity] = useState("");
  const [reasonId, setReasonId] = useState<string>(REASONS.add[0].id);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(() => crypto.randomUUID());
  const amount = /^\d+$/.test(quantity.trim()) ? Number(quantity.trim()) : null;
  const valid = amount !== null && amount > 0 && amount <= QUANTITY_MAX && (direction === "add" || amount <= row.on_hand);
  const after = amount === null ? null : row.on_hand + (direction === "add" ? amount : -amount);
  const reason = REASONS[direction].find((r) => r.id === reasonId) ?? REASONS[direction][0];
  const showAfter = after !== null && amount !== null && amount > 0;

  const save = useMutation({
    mutationFn: () => {
      const label = t(`inventory.reasons.${reason.id}`);
      return scope.api.adjust(row.sku, key, { reason: reason.reason, quantity_delta: direction === "add" ? amount! : -amount!, note: note.trim() ? `${label}: ${note.trim()}` : label });
    },
    onSuccess: () => {
      toast.show(t("inventory.adjusted", { sku: row.sku }));
      void client.invalidateQueries({ queryKey: [scope.key] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError && e.status === 409 ? t("inventory.errors.conflict") : t("common.saveError")),
  });

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("inventory.adjustTitle")}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={save.isPending}
            onClick={() => {
              if (!valid) setError(direction === "remove" && amount !== null && amount > row.on_hand ? t("inventory.errors.tooMany", { count: row.on_hand }) : t("inventory.errors.quantity"));
              else {
                setError(null);
                save.mutate();
              }
            }}
          >
            {t("inventory.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {/* The variant and its figures now. */}
        <div className="overflow-hidden rounded-xl border border-bd">
          <div className="flex flex-col gap-0.5 bg-page px-4 py-3">
            <b className="text-sm font-semibold">
              {row.product_name} · {row.variant_name}
            </b>
            <span className="font-mono text-cap text-tx2">{row.sku}</span>
          </div>
          <dl className="m-0 grid grid-cols-3 divide-x divide-bd border-t border-bd">
            <Figure label={t("inventory.columns.onHand")}>{row.on_hand}</Figure>
            <Figure label={t("inventory.columns.reserved")}>{row.reserved_quantity + row.committed_quantity}</Figure>
            <Figure label={t("inventory.columns.available")}>{row.available_quantity}</Figure>
          </dl>
        </div>

        <div role="radiogroup" aria-label={t("inventory.type")} className="grid grid-cols-2 gap-2.5">
          {(["add", "remove"] as const).map((d) => {
            const Icon = d === "add" ? Plus : Minus;
            return (
              <RadioOption
                key={d}
                name="direction"
                checked={direction === d}
                onChange={() => {
                  setDirection(d);
                  setReasonId(REASONS[d][0].id);
                }}
                className="px-3 py-2.5 has-checked:px-[11px] has-checked:py-[9px]"
                label={
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <span aria-hidden="true" className={cx("flex size-6 items-center justify-center rounded-md", d === "add" ? "bg-ok-bg text-ok-tx" : "bg-err-bg text-err-tx")}>
                      <Icon size={14} />
                    </span>
                    {t(`inventory.${d}`)}
                  </span>
                }
              />
            );
          })}
        </div>

        <Field label={t("inventory.quantity")} error={error ?? undefined}>
          {(c) => <Input {...c} inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}
        </Field>

        {/* Current → new stock, once a quantity is typed. */}
        <div aria-live="polite" className={cx("flex items-center justify-between gap-3 rounded-xl border px-4 py-3", showAfter ? "border-pri/30 bg-light" : "border-dashed border-bd bg-card")}>
          <span className="flex flex-col">
            <span className="text-cap text-tx2">{t("inventory.currentShort")}</span>
            <b className="t-h3 tabular-nums">{row.on_hand}</b>
          </span>
          <ArrowRight size={18} aria-hidden="true" className={showAfter ? "text-pri-fg" : "text-bd2"} />
          <span className="flex flex-col items-end">
            <span className="text-cap text-tx2">{t("inventory.newShort")}</span>
            {showAfter ? (
              <b className={cx("t-h3 tabular-nums", after! < 0 ? "text-err-tx" : direction === "add" ? "text-ok-tx" : "text-tx")}>
                <span className="sr-only">{t.rich("inventory.newStock", { count: after!, b: (chunks) => chunks })}</span>
                <span aria-hidden="true">{after}</span>
              </b>
            ) : (
              <b className="t-h3 text-bd2">—</b>
            )}
          </span>
        </div>

        <Field label={t("inventory.reason")}>
          {(c) => (
            <Select {...c} value={reason.id} onChange={(e) => setReasonId(e.target.value)}>
              {REASONS[direction].map((r) => (
                <option key={r.id} value={r.id}>
                  {t(`inventory.reasons.${r.id}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label={
            <>
              {t("inventory.note")} <span className="font-normal text-tx2">{t("common.optional")}</span>
            </>
          }
        >
          {(c) => <Input {...c} maxLength={300} placeholder={t("inventory.notePlaceholder")} value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </div>
    </Dialog>
  );
}

function Figure({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2.5">
      <dt className="text-cap text-tx2">{label}</dt>
      <dd className="m-0 font-semibold tabular-nums">{children}</dd>
    </div>
  );
}
