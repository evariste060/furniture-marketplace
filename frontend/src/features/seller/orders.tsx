"use client";

import { ShoppingCart } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { OrderStatusBadge, PaymentStatusBadge } from "@/features/admin/status";
import { FilterBar, FilterTabs, ListFooter, LoadError, PageHeader, SearchBox, useListParams } from "@/features/admin/ui";
import { formatDate, formatMoney } from "@/lib/format";
import { isSellerOrderStatus, SELLER_ORDER_STATUSES, useSellerOrders, type SellerOrderSummary } from "./orders-api";
import { SellerOrderBadge } from "./status";

const PAGE_SIZE = 20;
const COLUMNS = 9;

/** /seller/orders: the store's part of each order, newest first, filtered by the store's status and
 * the order number (both in the URL). */
export function SellerOrdersView() {
  const t = useTranslations("admin.seller.orders");
  const ts = useTranslations("admin.status.sellerOrder");
  const { get, page, set, hrefWith } = useListParams();
  const raw = get("status");
  const status = isSellerOrderStatus(raw) ? raw : "";
  const q = get("q");
  const list = useSellerOrders({ status: status || undefined, q: q || undefined, page, size: PAGE_SIZE });
  const rows = list.data?.items ?? [];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <section className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <FilterTabs
          label={t("statusLabel")}
          items={[{ id: "", label: t("allStatuses") }, ...SELLER_ORDER_STATUSES.map((s) => ({ id: s, label: ts(s) }))]}
          value={status}
          onChange={(id) => set({ status: id || null })}
        />
        <FilterBar>
          <SearchBox label={t("searchLabel")} placeholder={t("searchPlaceholder")} value={q} onSearch={(value) => set({ q: value })} />
          {list.data && (
            <span aria-live="polite" className="ml-auto text-sm text-tx2 tabular-nums">
              {t("count", { count: list.data.total })}
            </span>
          )}
        </FilterBar>
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <ShoppingCart size={26} />
            </span>
            <p className="m-0 max-w-96 text-tx2">{status || q ? t("emptyFiltered") : t("empty")}</p>
          </div>
        ) : (
          <SellerOrderTable rows={rows} loading={!list.data} busy={list.isFetching} />
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
    </>
  );
}

/** The orders table, also on the dashboard's Recent orders. */
export function SellerOrderTable({ rows, loading, busy, skeletonRows = 6 }: { rows: SellerOrderSummary[]; loading: boolean; busy?: boolean; skeletonRows?: number }) {
  const t = useTranslations("admin.seller.orders");
  return (
    <Table aria-busy={busy}>
      <thead>
        <tr>
          <Th>{t("columns.order")}</Th>
          <Th>{t("columns.placed")}</Th>
          <Th>{t("columns.recipient")}</Th>
          <Th className="text-right">{t("columns.units")}</Th>
          <Th className="text-right">{t("columns.goods")}</Th>
          <Th className="text-right">{t("columns.net")}</Th>
          <Th>{t("columns.payment")}</Th>
          <Th>{t("columns.status")}</Th>
          <Th>{t("columns.orderStatus")}</Th>
        </tr>
      </thead>
      <tbody>
        {loading
          ? Array.from({ length: skeletonRows }, (_, i) => (
              <tr key={i}>
                <Td colSpan={COLUMNS}>
                  <Skeleton className="h-10 w-full" />
                </Td>
              </tr>
            ))
          : rows.map((row) => (
              <tr key={row.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                <Td>
                  <NextLink href={`/seller/orders/${row.id}`} aria-label={t("open", { number: row.order_number })} className="font-semibold whitespace-nowrap">
                    {row.order_number}
                  </NextLink>
                </Td>
                <Td className="whitespace-nowrap text-tx2">{formatDate(row.created_at, "dayTime")}</Td>
                <Td>{row.recipient_name}</Td>
                <Td className="text-right tabular-nums">{row.units}</Td>
                <Td className="text-right whitespace-nowrap tabular-nums">{formatMoney(row.merchandise_total)}</Td>
                <Td className="text-right font-semibold whitespace-nowrap tabular-nums">{formatMoney(row.seller_net_amount)}</Td>
                <Td>{row.payment_status ? <PaymentStatusBadge status={row.payment_status} method={row.payment_method} /> : "—"}</Td>
                <Td>
                  <SellerOrderBadge status={row.status} />
                </Td>
                <Td>
                  <OrderStatusBadge status={row.order_status} />
                </Td>
              </tr>
            ))}
      </tbody>
    </Table>
  );
}
