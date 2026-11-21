"use client";

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Clock, CreditCard, Landmark, ReceiptText, Wallet, X, XCircle, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { browserApi } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import { formatDate, formatMoney } from "@/lib/format";
import { MethodMark, PAYMENT_METHODS, PaymentStatusBadge, type PaymentMethod } from "./status";
import { ListFooter, LoadError, must, PageHeader, useListParams } from "./ui";

const PAGE_SIZE = 20;
/** Payments.dc.html tabs: All, Successful, Pending (n), Failed (n). */
const TABS = ["", "succeeded", "pending", "failed"] as const;
type Tab = (typeof TABS)[number];

/** The status tiles: an icon and its colours per tab. */
const TILE: Record<Tab, { Icon: LucideIcon; tone: string }> = {
  "": { Icon: ReceiptText, tone: "bg-subtle text-tx2" },
  succeeded: { Icon: Wallet, tone: "bg-ok-bg text-ok-tx" },
  pending: { Icon: Clock, tone: "bg-warn-bg text-warn-tx" },
  failed: { Icon: XCircle, tone: "bg-err-bg text-err-tx" },
};

function isTab(value: string): value is Tab {
  return (TABS as readonly string[]).includes(value);
}
function isMethod(value: string): value is PaymentMethod {
  return (PAYMENT_METHODS as string[]).includes(value);
}

/** Payments.dc.html: the payment attempts, newest first. Filters live in the URL: status, method, page. */
export function PaymentsView() {
  const t = useTranslations("admin");
  const { get, page, set, hrefWith } = useListParams();
  const status: Tab = isTab(get("status")) ? (get("status") as Tab) : "";
  const method = isMethod(get("method")) ? (get("method") as PaymentMethod) : "";
  const shared = { method: method || undefined };

  const list = useQuery({
    queryKey: ["admin", "payments", { status, ...shared, page }],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/payments", {
          params: {
            query: {
              ...shared,
              status: status || undefined,
              page,
              size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const counts = useQueries({
    queries: TABS.map((s) => ({
      queryKey: ["admin", "payments", "count", s, shared],
      queryFn: async () =>
        (
          await must(
            browserApi.GET("/api/v1/staff/payments", {
              params: { query: { ...shared, status: s || undefined, size: 1 } },
            }),
          )
        ).total,
    })),
  });

  return (
    <>
      <PageHeader title={t("payments.title")} description={t("payments.description")} />

      {/* Each tile filters the list by status. */}
      <div role="group" aria-label={t("payments.tabsLabel")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {TABS.map((s, i) => {
          const on = s === status;
          const { Icon, tone } = TILE[s];
          const n = counts[i].data;
          return (
            <button
              key={s || "all"}
              type="button"
              aria-pressed={on}
              onClick={() => set({ status: s })}
              className={cx(
                "flex cursor-pointer items-center gap-3.5 rounded-xl border p-4 text-left shadow-sh transition-[border-color,box-shadow,background-color] duration-150 motion-reduce:transition-none",
                on ? "border-pri bg-light ring-1 ring-pri" : "border-bd bg-white hover:border-bd2 hover:shadow-sh2",
              )}
            >
              <span aria-hidden="true" className={cx("flex size-11 flex-none items-center justify-center rounded-xl", tone)}>
                <Icon size={20} />
              </span>
              <span className="flex min-w-0 flex-col">
                <span className={cx("truncate text-sm font-medium", on ? "text-pri-h" : "text-tx2")}>{t(`payments.tiles.${s || "all"}`)}</span>
                {n === undefined ? <Skeleton className="mt-1 h-7 w-12" /> : <b className="t-h2 tabular-nums">{n.toLocaleString("en-US")}</b>}
              </span>
            </button>
          );
        })}
      </div>

      {/* The sum of every payment matching the filters (all pages). */}
      <section aria-labelledby="payments-total" className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl bg-navy px-6 py-5 text-white shadow-sh">
        <span aria-hidden="true" className="flex size-12 flex-none items-center justify-center rounded-xl bg-white/15">
          <Landmark size={24} />
        </span>
        <div className="flex min-w-0 flex-col">
          <h2 id="payments-total" className="text-sm font-semibold text-white/80">
            {t("payments.totalLabel")}
          </h2>
          {list.data ? (
            <b aria-live="polite" className="t-price-l tabular-nums">
              {formatMoney(list.data.amount_total)}
            </b>
          ) : (
            <Skeleton className="mt-1 h-9 w-48 bg-white/20" />
          )}
        </div>
        <div className="flex flex-col gap-2 sm:ml-auto sm:items-end">
          <span className="text-sm text-white/80 tabular-nums">{list.data ? t("payments.totalCount", { count: list.data.total }) : <Skeleton className="h-4 w-36 bg-white/20" />}</span>
          <span className="flex flex-wrap gap-2">
            <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-cap font-semibold">{t(`payments.tiles.${status || "all"}`)}</span>
            <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-cap font-semibold">{method ? t(`status.method.${method}`) : t("payments.allMethods")}</span>
          </span>
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <div className="flex flex-wrap items-end gap-3 border-b border-bd p-4">
          <Filter label={t("payments.methodLabel")} className="sm:w-56">
            {(id) => (
              <Select id={id} value={method} onChange={(e) => set({ method: e.target.value })} className="h-10 text-sm">
                <option value="">{t("payments.allMethods")}</option>
                {PAYMENT_METHODS.map((m) => (
                  <option key={m} value={m}>
                    {t(`status.method.${m}`)}
                  </option>
                ))}
              </Select>
            )}
          </Filter>
          <div className="ml-auto flex items-center gap-3 max-sm:w-full max-sm:justify-between">
            {list.data && (
              <span aria-live="polite" className="text-sm text-tx2 tabular-nums">
                {t("payments.count", { count: list.data.total })}
              </span>
            )}
            {method && (
              <Button variant="neutral" size="sm" onClick={() => set({ method: null })} className="gap-1.5">
                <X size={14} aria-hidden="true" />
                {t("payments.clearFilters")}
              </Button>
            )}
          </div>
        </div>

        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && list.data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <CreditCard size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{t("payments.empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("payments.columns.order")}</Th>
                <Th>{t("payments.columns.method")}</Th>
                <Th>{t("payments.columns.reference")}</Th>
                <Th>{t("payments.columns.date")}</Th>
                <Th className="text-right">{t("payments.columns.amount")}</Th>
                <Th>{t("payments.columns.status")}</Th>
                <Th>
                  <span className="sr-only">{t("common.actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={7}>
                        <Skeleton className="h-10 w-full" />
                      </Td>
                    </tr>
                  ))
                : list.data.items.map((p) => (
                    // The order number's link covers the whole row; a payment needing a check gets an amber edge.
                    <tr
                      key={p.id}
                      className={cx(
                        "group relative transition-colors duration-150 hover:bg-page motion-reduce:transition-none",
                        p.needs_reconciliation && "bg-warn-bg/40 shadow-[inset_3px_0_0_var(--color-warn)]",
                      )}
                    >
                      <Td>
                        <NextLink
                          href={`/admin/orders/${p.order_id}`}
                          className="font-mono text-sm font-semibold whitespace-nowrap text-pri-h no-underline after:absolute after:inset-0 after:content-[''] hover:underline"
                        >
                          {p.order_number}
                        </NextLink>
                      </Td>
                      <Td>
                        <MethodMark method={p.method} />
                      </Td>
                      <Td className="max-w-56">
                        {p.provider_reference ? (
                          <span className="font-mono text-cap break-all text-tx">{p.provider_reference}</span>
                        ) : (
                          <span className="text-tx2">{t("payments.noReference")}</span>
                        )}
                      </Td>
                      <Td>
                        <span className="flex flex-col whitespace-nowrap">
                          <span className="text-tx">{formatDate(p.created_at, "date")}</span>
                          <span className="text-cap text-tx2">{formatDate(p.created_at, "time")}</span>
                        </span>
                      </Td>
                      <Td className="text-right font-semibold whitespace-nowrap tabular-nums">{formatMoney(p.amount)}</Td>
                      <Td>
                        <span className="flex flex-col items-start gap-1">
                          <PaymentStatusBadge status={p.status} method={p.method} />
                          {p.needs_reconciliation && (
                            <span className="flex items-center gap-1 text-cap font-semibold whitespace-nowrap text-warn-tx">
                              <AlertTriangle size={13} aria-hidden="true" />
                              {t("payments.needsCheck")}
                            </span>
                          )}
                        </span>
                      </Td>
                      <Td className="text-right">
                        <ChevronRight
                          size={18}
                          aria-hidden="true"
                          className="inline-block text-bd2 transition-[color,translate] duration-150 group-hover:translate-x-0.5 group-hover:text-pri motion-reduce:transition-none"
                        />
                      </Td>
                    </tr>
                  ))}
            </tbody>
          </Table>
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
    </>
  );
}

/** A labelled filter control. */
function Filter({ label, className, children }: { label: string; className?: string; children: (id: string) => ReactNode }) {
  const id = `payments-filter-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className={cx("flex min-w-0 flex-col gap-1 max-sm:flex-1", className)}>
      <label htmlFor={id} className="text-cap font-semibold text-tx2">
        {label}
      </label>
      {children(id)}
    </div>
  );
}
