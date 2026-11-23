"use client";

import { Wallet } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { PaymentStatusBadge } from "@/features/admin/status";
import {
  ListFooter,
  LoadError,
  PageHeader,
  useListParams,
} from "@/features/admin/ui";
import { formatDate, formatMoney } from "@/lib/format";
import { EarningsCard } from "./dashboard";
import { useSellerEarnings, useSellerOrders } from "./orders-api";
import { SellerOrderBadge } from "./status";
import { percent, useSellerStore } from "./store-context";

const PAGE_SIZE = 20;
const COLUMNS = 7;

/** /seller/earnings (SC-06, ADR-014 phase 7): the store's pending and earned totals from GET
 * /seller/earnings, and each seller order's goods, commission and share from GET /seller/orders.
 * The backend computes every amount; payouts are not built, so nothing here is paid out. */
export function SellerEarningsView() {
  const t = useTranslations("admin.seller.earnings");
  const td = useTranslations("admin.seller.dashboard");
  const store = useSellerStore();
  const { page, hrefWith } = useListParams();
  const earnings = useSellerEarnings();
  const list = useSellerOrders({ page, size: PAGE_SIZE });
  const rows = list.data?.items ?? [];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      {earnings.isError ? (
        <LoadError onRetry={() => earnings.refetch()} />
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          <EarningsCard
            title={td("pending")}
            hint={td("pendingHint")}
            bucket={earnings.data?.pending}
          />
          <EarningsCard
            title={td("earned")}
            hint={td("earnedHint")}
            bucket={earnings.data?.earned}
          />
        </div>
      )}
      <p className="m-0 text-sm text-tx2">
        {td("commissionRate", { rate: percent(store.commissionRateBps) })}
      </p>
      <section className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <div className="border-b border-bd px-5 py-[18px]">
          <h2 className="t-h3">{t("byOrder")}</h2>
        </div>
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span
              aria-hidden="true"
              className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2"
            >
              <Wallet size={26} />
            </span>
            <p className="m-0 max-w-96 text-tx2">{t("empty")}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table aria-busy={list.isFetching}>
              <thead>
                <tr>
                  <Th>{t("columns.order")}</Th>
                  <Th>{t("columns.placed")}</Th>
                  <Th className="text-right">{t("columns.goods")}</Th>
                  <Th className="text-right">{t("columns.commission")}</Th>
                  <Th className="text-right">{t("columns.net")}</Th>
                  <Th>{t("columns.payment")}</Th>
                  <Th>{t("columns.status")}</Th>
                </tr>
              </thead>
              <tbody>
                {!list.data
                  ? Array.from({ length: 6 }, (_, i) => (
                      <tr key={i}>
                        <Td colSpan={COLUMNS}>
                          <Skeleton className="h-10 w-full" />
                        </Td>
                      </tr>
                    ))
                  : rows.map((row) => (
                      <tr
                        key={row.id}
                        className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none"
                      >
                        <Td>
                          <NextLink
                            href={`/seller/orders/${row.id}`}
                            className="font-semibold whitespace-nowrap"
                          >
                            {row.order_number}
                          </NextLink>
                        </Td>
                        <Td className="whitespace-nowrap text-tx2">
                          {formatDate(row.created_at, "dayTime")}
                        </Td>
                        <Td className="text-right whitespace-nowrap tabular-nums">
                          {formatMoney(row.merchandise_total)}
                        </Td>
                        <Td className="text-right whitespace-nowrap tabular-nums">
                          −{formatMoney(row.commission_amount)}
                        </Td>
                        <Td className="text-right font-semibold whitespace-nowrap tabular-nums">
                          {formatMoney(row.seller_net_amount)}
                        </Td>
                        <Td>
                          {row.payment_status ? (
                            <PaymentStatusBadge
                              status={row.payment_status}
                              method={row.payment_method}
                            />
                          ) : (
                            "—"
                          )}
                        </Td>
                        <Td>
                          <SellerOrderBadge status={row.status} />
                        </Td>
                      </tr>
                    ))}
              </tbody>
            </Table>
          </div>
        )}
        {list.data && (
          <ListFooter
            page={page}
            size={PAGE_SIZE}
            total={list.data.total}
            hrefFor={(n) => hrefWith({ page: n })}
          />
        )}
      </section>
    </>
  );
}
