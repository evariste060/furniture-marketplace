"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, PackageOpen, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { LoadError, must, PageHeader } from "@/features/admin/ui";
import { browserApi } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { useSellerEarnings, useSellerOrders, type SellerEarnings } from "./orders-api";
import { SellerOrderTable } from "./orders";
import { useToConfirm } from "./shell";
import { percent, useSellerStore } from "./store-context";

const RECENT = 5;

/** /seller: what needs the seller's attention, the store's earnings (computed from its seller
 * orders; payouts are not built) and the latest orders. */
export function SellerDashboardView({ name }: { name: string }) {
  const t = useTranslations("admin.seller.dashboard");
  const store = useSellerStore();
  const toConfirm = useToConfirm();
  const toShip = useQueries({
    queries: (["confirmed", "processing"] as const).map((status) => ({
      queryKey: ["seller", "count", "orders", status],
      queryFn: async () => (await must(browserApi.GET("/api/v1/seller/orders", { params: { query: { status, size: 1 } } }))).total,
    })),
  });
  const lowStock = useQuery({
    queryKey: ["seller", "inventory", "low-count"],
    queryFn: async () => (await must(browserApi.GET("/api/v1/seller/inventory", { params: { query: { low_stock: true, size: 1 } } }))).total,
  });
  const earnings = useSellerEarnings();
  const recent = useSellerOrders({ page: 1, size: RECENT });
  const shipping = toShip.every((q) => q.data !== undefined) ? toShip.reduce((sum, q) => sum + (q.data ?? 0), 0) : undefined;

  return (
    <>
      <PageHeader title={name ? t("title", { name }) : t("titleNoName")} description={t("description", { store: store.name })} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Waiting href="/seller/orders?status=pending" Icon={ClipboardCheck} tone="bg-warn-bg text-warn-tx" label={t("toConfirm")} hint={t("toConfirmHint")} value={toConfirm.data} />
        <Waiting href="/seller/orders?status=confirmed" Icon={PackageOpen} tone="bg-light text-pri-h" label={t("toShip")} hint={t("toShipHint")} value={shipping} />
        <Waiting href="/seller/inventory?view=low" Icon={AlertTriangle} tone="bg-err-bg text-err-tx" label={t("lowStock")} hint={t("lowStockHint")} value={lowStock.data} />
      </div>
      {earnings.isError ? (
        <LoadError onRetry={() => earnings.refetch()} />
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          <EarningsCard title={t("pending")} hint={t("pendingHint")} bucket={earnings.data?.pending} />
          <EarningsCard title={t("earned")} hint={t("earnedHint")} bucket={earnings.data?.earned} />
        </div>
      )}
      <p className="m-0 text-sm text-tx2">{t("commissionRate", { rate: percent(store.commissionRateBps) })}</p>
      <section className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <div className="flex items-center justify-between gap-3 border-b border-bd px-5 py-[18px]">
          <h2 className="t-h3">{t("recent")}</h2>
          <NextLink href="/seller/orders" className="text-sm font-medium">
            {t("viewAll")}
          </NextLink>
        </div>
        {recent.isError ? (
          <LoadError onRetry={() => recent.refetch()} className="m-5" />
        ) : recent.data && recent.data.items.length === 0 ? (
          <p className="m-0 px-5 py-8 text-center text-tx2">{t("noOrders")}</p>
        ) : (
          <SellerOrderTable rows={recent.data?.items ?? []} loading={!recent.data} skeletonRows={RECENT} />
        )}
      </section>
    </>
  );
}

function Waiting({ href, Icon, tone, label, hint, value }: { href: string; Icon: LucideIcon; tone: string; label: string; hint: string; value: number | undefined }) {
  return (
    <NextLink
      href={href}
      className="flex items-center gap-3.5 rounded-xl border border-bd bg-white p-4 text-tx no-underline shadow-sh transition-[border-color,box-shadow] duration-150 hover:border-bd2 hover:text-tx hover:shadow-sh2 motion-reduce:transition-none"
    >
      <span aria-hidden="true" className={cx("flex size-11 flex-none items-center justify-center rounded-xl", tone)}>
        <Icon size={20} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-semibold">{label}</span>
        <span className="text-cap text-tx2">{hint}</span>
      </span>
      {value === undefined ? <Skeleton className="h-7 w-10" /> : <b className="t-h2 tabular-nums">{value.toLocaleString("en-US")}</b>}
    </NextLink>
  );
}

/** A pending or earned total; also on the admin's seller page, where `netLabel` names the share. */
export function EarningsCard({ title, hint, bucket, netLabel }: { title: string; hint: string; bucket: SellerEarnings["pending"] | undefined; netLabel?: string }) {
  const t = useTranslations("admin.seller.dashboard");
  return (
    <Card padding={24} className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="t-h3">{title}</h2>
        <span className="text-cap text-tx2">{hint}</span>
      </div>
      {bucket ? (
        <>
          <b className="t-display tabular-nums">{formatMoney(bucket.seller_net_amount)}</b>
          <span className="text-sm text-tx2">{t("orders", { count: bucket.orders })}</span>
          <dl className="m-0 flex flex-col gap-1.5 border-t border-bd pt-3 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-tx2">{t("merchandise")}</dt>
              <dd className="m-0 tabular-nums">{formatMoney(bucket.merchandise_total)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-tx2">{t("commission")}</dt>
              <dd className="m-0 tabular-nums">−{formatMoney(bucket.commission_amount)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="font-semibold">{netLabel ?? t("net")}</dt>
              <dd className="m-0 font-semibold tabular-nums">{formatMoney(bucket.seller_net_amount)}</dd>
            </div>
          </dl>
        </>
      ) : (
        <Skeleton className="h-32 w-full" />
      )}
    </Card>
  );
}
