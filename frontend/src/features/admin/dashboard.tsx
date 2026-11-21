"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Boxes,
  FileUp,
  MessageSquare,
  Package,
  Scale,
  ShoppingCart,
  Tag,
  Truck,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { useStaffAccess } from "./access";
import type { Permission } from "./nav";
import { ORDER_STATUSES, OrderStatusBadge, type OrderStatus } from "./status";
import { timeAgo } from "./time";
import { LoadError, must, PageHeader, Thumb } from "./ui";

export { timeAgo };

const PERIODS = [7, 30, 90] as const;
type Period = (typeof PERIODS)[number];
const DAY = 24 * 60 * 60 * 1000;
const KIGALI = "Africa/Kigali";

/** The donut's colours (Dashboard.dc.html), one per backend order status. */
const STATUS_COLOUR: Record<OrderStatus, string> = {
  delivered: "var(--color-navy)",
  processing: "var(--color-ok)",
  received: "var(--color-warn)",
  confirmed: "var(--color-pri)",
  dispatched: "var(--color-pur)",
  cancelled: "var(--color-err)",
};

/** The two windows the KPI compares: [from, to] now and the same length before. */
export function periodWindows(days: number, now: number) {
  const to = new Date(now);
  const from = new Date(now - days * DAY);
  const previousFrom = new Date(now - 2 * days * DAY);
  return {
    current: { from: from.toISOString(), to: to.toISOString() },
    previous: { from: previousFrom.toISOString(), to: from.toISOString() },
  };
}

/** Whole-percent change from the previous period; null when there was nothing before. */
export function percentChange(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

/** A Kigali calendar day (YYYY-MM-DD), the reports' date format. */
function kigaliDay(time: number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: KIGALI, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(time));
}

/** The reports' day windows: the last `days` Kigali days (today included) and the ones before. */
export function reportWindows(days: number, now: number) {
  return {
    current: { from: kigaliDay(now - (days - 1) * DAY), to: kigaliDay(now) },
    previous: { from: kigaliDay(now - (2 * days - 1) * DAY), to: kigaliDay(now - days * DAY) },
  };
}

/** A round axis top and step for values up to `max` (4 steps). */
export function niceScale(max: number): { top: number; step: number } {
  if (max <= 0) return { top: 4, step: 1 };
  const raw = max / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power;
  return { top: step * 4, step };
}

/** 6450000 → "6.5M", 12000 → "12K". */
export function compactNumber(value: number, digits = 1): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: digits }).format(value);
}

async function orderCount(query: Record<string, string>) {
  const page = await must(browserApi.GET("/api/v1/staff/orders", { params: { query: { ...query, size: 1 } } }));
  return page.total;
}

/** Dashboard.dc.html, with every widget the API supports. Customers and sales by category wait for
 * their endpoints. */
export function Dashboard() {
  const t = useTranslations("admin.dashboard");
  const { can, fullName } = useStaffAccess();
  const [period, setPeriod] = useState<Period>(30);
  // One "now" for the page, so the query keys stay the same while it is open.
  const [now] = useState(() => Math.floor(Date.now() / 60_000) * 60_000);
  const windows = periodWindows(period, now);
  const days = reportWindows(period, now);
  const ordersOn = can("orders:read");
  const reportsOn = can("reports:read");

  const totals = useQueries({
    queries: [windows.current, windows.previous].map((w) => ({
      queryKey: ["admin", "dashboard", "orders", w.from, w.to],
      enabled: ordersOn,
      queryFn: () => orderCount(w),
    })),
  });
  const byStatus = useQueries({
    queries: ORDER_STATUSES.map((status) => ({
      queryKey: ["admin", "dashboard", "status", status, windows.current.from],
      enabled: ordersOn,
      queryFn: () => orderCount({ status, ...windows.current }),
    })),
  });
  const recent = useQuery({
    queryKey: ["admin", "dashboard", "recent"],
    enabled: ordersOn,
    queryFn: () => must(browserApi.GET("/api/v1/staff/orders", { params: { query: { size: 5 } } })),
  });
  const ready = useQuery({ queryKey: ["admin", "dashboard", "ready"], enabled: ordersOn, queryFn: () => orderCount({ status: "processing" }) });
  const sales = useQueries({
    queries: [
      { ...days.current, group_by: period === 90 ? ("week" as const) : ("day" as const) },
      { ...days.previous, group_by: "week" as const },
    ].map((query) => ({
      queryKey: ["admin", "dashboard", "sales", query],
      enabled: reportsOn,
      queryFn: () => must(browserApi.GET("/api/v1/staff/reports/sales", { params: { query } })),
    })),
  });
  const top = useQuery({
    queryKey: ["admin", "dashboard", "top", days.current],
    enabled: reportsOn,
    queryFn: () => must(browserApi.GET("/api/v1/staff/reports/top-products", { params: { query: { ...days.current, limit: 5 } } })),
  });
  const products = useQuery({
    queryKey: ["admin", "dashboard", "products"],
    enabled: can("catalog:read"),
    queryFn: async () => (await must(browserApi.GET("/api/v1/staff/products", { params: { query: { size: 1 } } }))).total,
  });
  const pending = useQuery({
    queryKey: ["admin", "dashboard", "pending-payments"],
    enabled: can("payments:read"),
    queryFn: async () => (await must(browserApi.GET("/api/v1/staff/payments", { params: { query: { status: "pending", size: 1 } } }))).total,
  });
  const reconcile = useQuery({
    queryKey: ["admin", "dashboard", "reconcile"],
    enabled: can("payments:read"),
    queryFn: async () => (await must(browserApi.GET("/api/v1/staff/payments", { params: { query: { needs_reconciliation: true, size: 1 } } }))).total,
  });
  const low = useQuery({
    queryKey: ["admin", "dashboard", "low-stock"],
    enabled: can("inventory:read"),
    queryFn: () => must(browserApi.GET("/api/v1/inventory", { params: { query: { low_stock: true, size: 5 } } })),
  });
  const reviews = useQuery({
    queryKey: ["admin", "dashboard", "reviews"],
    enabled: can("reviews:moderate"),
    queryFn: async () => (await must(browserApi.GET("/api/v1/staff/reviews", { params: { query: { status: "pending", size: 1 } } }))).total,
  });

  const all = [...totals, ...byStatus, ...sales, recent, ready, top, products, pending, reconcile, low, reviews];
  const failed = all.some((q) => q.isError);
  const retry = () => all.forEach((q) => q.isError && q.refetch());

  const revenue = sales[0].data?.totals.total;
  const previousRevenue = sales[1].data?.totals.total;
  const change = (a?: number, b?: number) => (a !== undefined && b !== undefined ? percentChange(a, b) : undefined);
  const hour = Number(new Intl.DateTimeFormat("en-GB", { timeZone: KIGALI, hour: "2-digit", hourCycle: "h23" }).format(new Date(now)));
  const greeting = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
  const firstName = fullName.trim().split(/\s+/)[0] || fullName;

  return (
    <>
      <PageHeader
        title={
          <span suppressHydrationWarning>
            {t(`greeting.${greeting}`, { name: firstName })} <span aria-hidden="true">👋</span>
          </span>
        }
        description={t("subtitle")}
        actions={
          ordersOn || reportsOn ? (
            <Select aria-label={t("period")} value={period} onChange={(e) => setPeriod(Number(e.target.value) as Period)} className="h-10 w-44 bg-white text-sm shadow-sh">
              {PERIODS.map((p) => (
                <option key={p} value={p}>
                  {t(`periods.${p}`)}
                </option>
              ))}
            </Select>
          ) : null
        }
      />
      {failed && <LoadError onRetry={retry} />}

      <div className="grid items-start gap-5 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-5">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-4">
            {ordersOn && (
              <Kpi
                href="/admin/orders"
                Icon={ShoppingCart}
                variant="navy"
                label={t("totalOrders")}
                value={totals[0].data?.toLocaleString("en-US")}
                change={change(totals[0].data, totals[1].data)}
                note={t("vsPreviousDays", { days: period })}
              />
            )}
            {reportsOn && (
              <Kpi
                href="/admin/payments?status=succeeded"
                Icon={Wallet}
                variant="blue"
                label={t("totalRevenue")}
                value={revenue === undefined ? undefined : revenue >= 1_000_000 ? `RWF ${compactNumber(revenue, 2)}` : formatMoney(revenue)}
                title={revenue === undefined ? undefined : formatMoney(revenue)}
                change={change(revenue, previousRevenue)}
                note={t("vsPreviousDays", { days: period })}
              />
            )}
            {can("payments:read") && (
              <Kpi href="/admin/payments?status=pending" Icon={Scale} variant="light" label={t("pendingPayments")} value={pending.data?.toLocaleString("en-US")} note={t("pendingHint")} />
            )}
            {can("catalog:read") && <Kpi href="/admin/products" Icon={Package} variant="purple" label={t("products")} value={products.data?.toLocaleString("en-US")} note={t("inCatalogue")} />}
          </div>

          {(reportsOn || ordersOn) && (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
              {reportsOn && <SalesOverview report={sales[0].data} previous={sales[1].data} />}
              {ordersOn && <StatusCard counts={byStatus.map((q) => q.data)} />}
            </div>
          )}
        </div>

        {/* Beside the charts on wide screens; in the grid below otherwise. */}
        {ordersOn && <RecentOrders orders={recent.data?.items} now={now} className="hidden 2xl:flex" />}
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-5">
        {ordersOn && <RecentOrders orders={recent.data?.items} now={now} className="2xl:hidden" />}
        {reportsOn && <TopProducts items={top.data?.items} />}
        {can("inventory:read") && <LowStockCard rows={low.data?.items} />}
        <QuickActions />
        <SystemAlerts
          alerts={[
            can("inventory:read") && { key: "lowStock", href: "/admin/inventory?view=low", Icon: AlertTriangle, tone: "bg-warn-bg text-warn-tx", count: low.data?.total },
            ordersOn && { key: "dispatch", href: "/admin/orders?status=processing", Icon: Truck, tone: "bg-light text-pri-h", count: ready.data },
            can("payments:read") && { key: "reconcile", href: "/admin/payments", Icon: Scale, tone: "bg-err-bg text-err-tx", count: reconcile.data },
            can("reviews:moderate") && { key: "reviews", href: "/admin/reviews", Icon: MessageSquare, tone: "bg-pur-bg text-pur", count: reviews.data },
          ]}
        />
      </div>
    </>
  );
}

/** Every clickable dashboard card: lifts a little on hover, with a stronger shadow. */
const CARD_LINK =
  "group rounded-xl no-underline transition-[border-color,box-shadow,translate] duration-200 ease-soft hover:-translate-y-0.5 hover:shadow-sh2 motion-reduce:transition-none motion-reduce:hover:translate-y-0";

const KPI_STYLE = {
  navy: { card: "bg-navy text-white hover:text-white", icon: "bg-white/15 text-white", note: "text-white/75", ghost: "text-white/10" },
  blue: { card: "bg-pri text-white hover:text-white", icon: "bg-white/20 text-white", note: "text-white/80", ghost: "text-white/15" },
  light: { card: "border border-pri/20 bg-light text-tx hover:text-tx", icon: "bg-white text-pri-h", note: "text-tx2", ghost: "text-pri/10" },
  purple: { card: "border border-pur/20 bg-pur-bg text-tx hover:text-tx", icon: "bg-white text-pur", note: "text-tx2", ghost: "text-pur/10" },
};

function Kpi({
  href,
  Icon,
  variant,
  label,
  value,
  change,
  note,
  title,
}: {
  title?: string;
  href: string;
  Icon: LucideIcon;
  variant: keyof typeof KPI_STYLE;
  label: string;
  value?: string;
  change?: number | null;
  note: string;
}) {
  const t = useTranslations("admin.dashboard");
  const style = KPI_STYLE[variant];
  const dark = variant === "navy" || variant === "blue";
  return (
    <NextLink href={href} className={cx(CARD_LINK, "relative flex min-h-[148px] flex-col gap-2 overflow-hidden p-5 shadow-sh", style.card)}>
      <Icon aria-hidden="true" size={92} strokeWidth={1.5} className={cx("pointer-events-none absolute -right-3 -bottom-4", style.ghost)} />
      <span className="relative flex items-center gap-2.5">
        <span aria-hidden="true" className={cx("flex size-9 flex-none items-center justify-center rounded-lg", style.icon)}>
          <Icon size={18} />
        </span>
        <span className="text-sm font-semibold">{label}</span>
      </span>
      <span className="relative">
        {value === undefined ? <Skeleton className={cx("h-9 w-28", dark && "bg-white/20")} /> : <b title={title} className="t-price-l block truncate tabular-nums">
            {value}
            {title && title !== value && <span className="sr-only"> ({title})</span>}
          </b>}
      </span>
      <span className="relative mt-auto flex flex-wrap items-center gap-2">
        {change !== undefined && change !== null && (
          <span
            className={cx(
              "inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-cap font-semibold tabular-nums",
              change >= 0 ? "bg-ok-bg text-ok-tx" : "bg-err-bg text-err-tx",
            )}
          >
            {change > 0 ? <ArrowUp size={12} aria-hidden="true" /> : change < 0 ? <ArrowDown size={12} aria-hidden="true" /> : null}
            <span className="sr-only">{change === 0 ? t("flat") : change > 0 ? t("up", { percent: change }) : t("down", { percent: -change })}</span>
            <span aria-hidden="true">{change > 0 ? "+" : ""}{change}%</span>
          </span>
        )}
        <span className={cx("text-cap", style.note)}>{note}</span>
      </span>
    </NextLink>
  );
}

/** A dashboard panel: the title row, then its content. */
function Section({ title, link, action, children, className }: { title: string; link?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("flex min-w-0 flex-col rounded-xl border border-bd bg-white shadow-sh", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5 pb-3 max-sm:px-4">
        <h2 className="t-h3">{title}</h2>
        {action ?? link}
      </div>
      <div className="flex grow flex-col gap-3.5 px-6 pb-6 max-sm:px-4 max-sm:pb-4">{children}</div>
    </section>
  );
}

/** "View all →" in a panel's title row. */
function SectionLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <NextLink href={href} className="group flex items-center gap-1 rounded-md text-sm font-semibold text-pri-h no-underline hover:text-pri">
      {children}
      <ArrowRight size={14} aria-hidden="true" className="transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none" />
    </NextLink>
  );
}

type SalesReport = components["schemas"]["SalesReport"];
const dayLabel = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const fullDay = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const asDate = (day: string) => new Date(`${day.slice(0, 10)}T12:00:00Z`);

/** Sales Overview: revenue or paid orders per day (per week over 90 days), from the sales report. */
function SalesOverview({ report, previous }: { report?: SalesReport; previous?: SalesReport }) {
  const t = useTranslations("admin.dashboard");
  const [metric, setMetric] = useState<"total" | "orders">("total");
  const [hover, setHover] = useState<number | null>(null);
  const periods = report?.periods ?? [];
  const values = periods.map((p) => p[metric]);
  const total = report?.totals[metric];
  const change = total !== undefined && previous ? percentChange(total, previous.totals[metric]) : null;
  const { top, step } = niceScale(Math.max(0, ...values));
  const n = values.length;
  const x = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);
  const y = (v: number) => 100 - (v / top) * 100;
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const area = n ? `${line} L${x(n - 1)},100 L${x(0)},100 Z` : "";
  const shown = hover ?? n - 1;
  const pointDate = (i: number) =>
    report?.group_by === "week" ? t("weekOf", { date: dayLabel.format(asDate(periods[i].period_start)) }) : fullDay.format(asDate(periods[i].period_start));
  const format = (v: number) => (metric === "total" ? formatMoney(v) : t("ordersCount", { count: v }));
  // About six date labels under the chart.
  const every = Math.max(1, Math.ceil(n / 6));
  const ticks = periods.map((p, i) => ({ i, label: dayLabel.format(asDate(p.period_start)) })).filter(({ i }) => i % every === 0);

  return (
    <Section
      title={t("salesOverview")}
      action={
        <div role="group" aria-label={t("metricLabel")} className="flex rounded-lg bg-page p-1">
          {(["total", "orders"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={metric === m}
              onClick={() => setMetric(m)}
              className={cx(
                "h-8 cursor-pointer rounded-md border-0 px-3.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                metric === m ? "bg-pri text-white shadow-sh" : "bg-transparent text-tx2 hover:text-tx",
              )}
            >
              {t(`metric.${m}`)}
            </button>
          ))}
        </div>
      }
    >
      {!report ? (
        <>
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-64 w-full" />
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            <b className="t-price-l tabular-nums">{format(total ?? 0)}</b>
            {change !== null && (
              <span className={cx("inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-cap font-semibold", change >= 0 ? "bg-ok-bg text-ok-tx" : "bg-err-bg text-err-tx")}>
                {change >= 0 ? <ArrowUp size={12} aria-hidden="true" /> : <ArrowDown size={12} aria-hidden="true" />}
                <span className="sr-only">{change >= 0 ? t("up", { percent: change }) : t("down", { percent: -change })}</span>
                <span aria-hidden="true">{change > 0 ? "+" : ""}{change}%</span>
              </span>
            )}
          </div>
          {values.every((v) => v === 0) ? (
            <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-bd text-sm text-tx2">{t("noSales")}</div>
          ) : (
            <div className="grid grow grid-cols-[auto_minmax(0,1fr)] grid-rows-[minmax(16rem,1fr)_auto] gap-x-3">
              {/* The value axis. */}
              <div aria-hidden="true" className="flex h-full flex-col justify-between text-right text-cap text-tx2 tabular-nums">
                {[4, 3, 2, 1, 0].map((k) => (
                  <span key={k} className="-my-2 leading-4">
                    {compactNumber(k * step)}
                  </span>
                ))}
              </div>
              <div
                role="slider"
                tabIndex={0}
                aria-valuemin={0}
                aria-valuemax={Math.max(0, n - 1)}
                aria-valuenow={shown}
                aria-valuetext={n ? `${pointDate(shown)}: ${format(values[shown])}` : undefined}
                aria-label={t("chartLabel", {
                  metric: t(`metric.${metric}`),
                  from: fullDay.format(asDate(report.from)),
                  to: fullDay.format(asDate(report.to)),
                  total: format(total ?? 0),
                })}
                onPointerMove={(e) => {
                  const box = e.currentTarget.getBoundingClientRect();
                  setHover(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - box.left) / box.width) * (n - 1)))));
                }}
                onPointerLeave={() => setHover(null)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft" || e.key === "ArrowDown") setHover(Math.max(0, shown - 1));
                  if (e.key === "ArrowRight" || e.key === "ArrowUp") setHover(Math.min(n - 1, shown + 1));
                  if (e.key === "Home") setHover(0);
                  if (e.key === "End") setHover(n - 1);
                }}
                onBlur={() => setHover(null)}
                className="relative h-full touch-none rounded-sm outline-offset-4 focus-visible:outline-2 focus-visible:outline-pri"
              >
                {[0, 25, 50, 75, 100].map((p) => (
                  <span key={p} aria-hidden="true" className={cx("absolute inset-x-0 h-px", p === 100 ? "bg-bd" : "bg-subtle")} style={{ top: `${p}%` }} />
                ))}
                <svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible">
                  <defs>
                    <linearGradient id="sales-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--color-pri)" stopOpacity="0.28" />
                      <stop offset="100%" stopColor="var(--color-pri)" stopOpacity="0.02" />
                    </linearGradient>
                  </defs>
                  <path d={area} fill="url(#sales-fill)" />
                  <path d={line} fill="none" stroke="var(--color-pri)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                </svg>
                {n > 0 && (
                  <>
                    <span aria-hidden="true" className="absolute top-0 bottom-0 w-px bg-pri/30" style={{ left: `${x(shown)}%` }} />
                    <span
                      aria-hidden="true"
                      className="absolute size-3 -translate-1/2 rounded-full border-2 border-white bg-pri shadow-sh"
                      style={{ left: `${x(shown)}%`, top: `${y(values[shown])}%` }}
                    />
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute z-10 flex flex-col rounded-lg border border-bd bg-white px-3 py-2 whitespace-nowrap shadow-sh2"
                      style={{
                        left: `${x(shown)}%`,
                        top: `${y(values[shown])}%`,
                        translate: `${x(shown) > 70 ? "-100%" : x(shown) < 30 ? "0" : "-50%"} calc(-100% - 12px)`,
                      }}
                    >
                      <b className="text-sm font-semibold tabular-nums">{format(values[shown])}</b>
                      <span className="text-cap text-tx2">{pointDate(shown)}</span>
                    </span>
                  </>
                )}
              </div>
              <span />
              <div aria-hidden="true" className="relative mt-2 h-4 text-cap text-tx2">
                {ticks.map(({ i, label }) => (
                  <span key={i} className="absolute whitespace-nowrap" style={{ left: `${x(i)}%`, translate: i === 0 ? "0 0" : i === n - 1 ? "-100% 0" : "-50% 0" }}>
                    {label}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Section>
  );
}

function StatusCard({ counts }: { counts: (number | undefined)[] }) {
  const t = useTranslations("admin");
  const ready = counts.every((c) => c !== undefined);
  const values = counts.map((c) => c ?? 0);
  const total = values.reduce((a, b) => a + b, 0);
  const circumference = 2 * Math.PI * 70;
  const lengths = values.map((v) => (total ? (v / total) * circumference : 0));
  const parts = ORDER_STATUSES.map((status, i) => ({
    status,
    count: values[i],
    percent: total ? Math.round((values[i] / total) * 1000) / 10 : 0,
    length: lengths[i],
    // Each slice starts where the ones before it end.
    offset: lengths.slice(0, i).reduce((a, b) => a + b, 0),
  }));
  const summary = parts
    .filter((p) => p.count > 0)
    .map((p) => `${p.count} ${t(`status.order.${p.status}`).toLowerCase()}`)
    .join(", ");

  return (
    <Section title={t("dashboard.ordersByStatus")} link={<SectionLink href="/admin/orders">{t("dashboard.viewAll")}</SectionLink>}>
      {!ready ? (
        <Skeleton className="h-[200px] w-full" />
      ) : total === 0 ? (
        <p className="text-tx2">{t("dashboard.noOrders")}</p>
      ) : (
        <div className="flex grow flex-wrap items-center justify-center gap-x-6 gap-y-5">
          <svg viewBox="0 0 180 180" width="168" height="168" className="flex-none" role="img" aria-label={t("dashboard.statusChart", { total, parts: summary })}>
            <circle cx="90" cy="90" r="70" fill="none" stroke="var(--color-subtle)" strokeWidth="24" />
            <g transform="rotate(-90 90 90)" fill="none" strokeWidth="24">
              {parts.map((p) =>
                p.length > 0 ? <circle key={p.status} cx="90" cy="90" r="70" stroke={STATUS_COLOUR[p.status]} strokeDasharray={`${p.length} ${circumference}`} strokeDashoffset={-p.offset} /> : null,
              )}
            </g>
            <text x="90" y="90" textAnchor="middle" fontSize="28" fontWeight="700" fill="var(--color-tx)">
              {total.toLocaleString("en-US")}
            </text>
            <text x="90" y="110" textAnchor="middle" fontSize="11" fill="var(--color-tx2)">
              {t("dashboard.totalLabel")}
            </text>
          </svg>
          <ul className="m-0 flex min-w-[170px] grow list-none flex-col gap-0.5 p-0">
            {parts.map((p) => (
              <li key={p.status}>
                <NextLink
                  href={`/admin/orders?status=${p.status}`}
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-tx no-underline transition-colors duration-150 hover:bg-page hover:text-tx motion-reduce:transition-none"
                >
                  <span aria-hidden="true" className="size-2.5 flex-none rounded-full" style={{ background: STATUS_COLOUR[p.status] }} />
                  <span className="grow text-tx2">{t(`status.order.${p.status}`)}</span>
                  <b className="font-semibold tabular-nums">{p.count}</b>
                  <span className="w-12 text-right text-cap text-tx2 tabular-nums">({p.percent}%)</span>
                </NextLink>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}

type OrderRow = components["schemas"]["StaffOrderSummaryResponse"];

function RecentOrders({ orders, now, className }: { orders?: OrderRow[]; now: number; className?: string }) {
  const t = useTranslations("admin");
  return (
    <Section title={t("dashboard.recentOrders")} link={<SectionLink href="/admin/orders">{t("dashboard.viewAll")}</SectionLink>} className={className}>
      {!orders ? (
        Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-14 w-full" />)
      ) : orders.length === 0 ? (
        <p className="text-tx2">{t("dashboard.noRecent")}</p>
      ) : (
        <ul className="m-0 -mx-2 -my-1 flex list-none flex-col p-0">
          {orders.map((order) => (
            <li key={order.id} className="border-b border-subtle last:border-b-0">
              <NextLink
                href={`/admin/orders/${order.id}`}
                aria-label={t("orders.open", { number: order.order_number })}
                className="flex items-center gap-3 rounded-lg px-2 py-3 text-tx no-underline transition-colors duration-150 hover:bg-page hover:text-tx motion-reduce:transition-none"
              >
                <span aria-hidden="true" className="flex size-11 flex-none items-center justify-center rounded-lg bg-light text-pri-h">
                  <ShoppingCart size={18} />
                </span>
                <span className="flex min-w-0 grow flex-col">
                  <b className="truncate font-mono text-sm font-semibold">#{order.order_number}</b>
                  <span className="truncate text-cap text-tx2">
                    {order.customer_name} · {t("orders.items", { count: order.item_count })}
                  </span>
                  <b className="text-sm font-semibold tabular-nums">{formatMoney(order.total)}</b>
                </span>
                <span className="flex flex-none flex-col items-end gap-1.5">
                  <OrderStatusBadge status={order.status} />
                  <span className="text-cap whitespace-nowrap text-tx2" suppressHydrationWarning>
                    {timeAgo(order.created_at, now)}
                  </span>
                </span>
              </NextLink>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

type TopRow = components["schemas"]["TopProduct"];

function TopProducts({ items }: { items?: TopRow[] }) {
  const t = useTranslations("admin.dashboard");
  return (
    <Section title={t("topSelling")}>
      {!items ? (
        Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)
      ) : items.length === 0 ? (
        <p className="text-tx2">{t("noTopSelling")}</p>
      ) : (
        <ol className="m-0 -my-1 flex list-none flex-col divide-y divide-subtle p-0">
          {items.map((item) => {
            const name = <b className="truncate text-sm font-semibold">{item.product_name}</b>;
            return (
              <li key={`${item.rank}-${item.product_name}`} className="flex items-center gap-3 py-2.5">
                <span
                  aria-hidden="true"
                  className={cx(
                    "flex size-9 flex-none items-center justify-center rounded-lg text-sm font-bold tabular-nums",
                    item.rank === 1 ? "bg-pri text-white" : item.rank <= 3 ? "bg-light text-pri-h" : "bg-subtle text-tx2",
                  )}
                >
                  {item.rank}
                </span>
                <span className="flex min-w-0 grow flex-col">
                  {item.product_id ? (
                    <NextLink href={`/admin/products/${item.product_id}`} className="truncate text-tx no-underline hover:text-pri-h hover:underline">
                      {name}
                    </NextLink>
                  ) : (
                    name
                  )}
                  <span className="text-cap text-tx2">{t("sold", { count: item.units })}</span>
                </span>
                <b className="text-sm font-semibold whitespace-nowrap tabular-nums">{formatMoney(item.revenue)}</b>
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}

type LowRow = {
  sku: string;
  product_name: string;
  variant_name: string;
  available_quantity: number;
};

function LowStockCard({ rows }: { rows?: LowRow[] }) {
  const t = useTranslations("admin.dashboard");
  return (
    <Section title={t("lowStockItems")} link={<SectionLink href="/admin/inventory?view=low">{t("viewAll")}</SectionLink>}>
      {!rows ? (
        Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)
      ) : rows.length === 0 ? (
        <p className="text-tx2">{t("noLowStock")}</p>
      ) : (
        <ul className="m-0 -my-1 flex list-none flex-col divide-y divide-subtle p-0">
          {rows.map((row) => (
            <li key={row.sku} className="flex items-center gap-3 py-2.5">
              <Thumb />
              <span className="flex min-w-0 grow flex-col">
                <b className="truncate text-sm font-semibold">{row.product_name}</b>
                <span className="truncate text-cap text-tx2">
                  {row.variant_name} · {t("sku", { sku: row.sku })}
                </span>
              </span>
              <Badge tone={row.available_quantity <= 0 ? "soft-err" : "soft-warn"}>{t("left", { count: row.available_quantity })}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

const ACTIONS: { key: string; href: string; Icon: LucideIcon; tone: string; perm: Permission }[] = [
  { key: "orders", href: "/admin/orders", Icon: ShoppingCart, tone: "bg-pur-bg text-pur", perm: "orders:read" },
  { key: "stock", href: "/admin/inventory", Icon: Boxes, tone: "bg-ok-bg text-ok-tx", perm: "inventory:adjust" },
  { key: "promotion", href: "/admin/promotions?new=1", Icon: Tag, tone: "bg-warn-bg text-warn-tx", perm: "promotions:manage" },
  { key: "import", href: "/admin/import", Icon: FileUp, tone: "bg-subtle text-tx2", perm: "catalog:manage" },
];

function QuickActions() {
  const t = useTranslations("admin.dashboard");
  const { can } = useStaffAccess();
  const actions = ACTIONS.filter((a) => can(a.perm));
  if (actions.length === 0) return null;
  return (
    <Section title={t("quickActions")}>
      <div className="grid grow grid-cols-2 gap-3">
        {actions.map(({ key, href, Icon, tone }, i) => (
          <NextLink
            key={key}
            href={href}
            className={cx(
              CARD_LINK,
              "flex flex-col items-center justify-center gap-2 p-4 text-center text-tx hover:text-tx",
              tone.split(" ")[0],
              // An odd last tile spans the row.
              i === actions.length - 1 && actions.length % 2 === 1 && "col-span-2",
            )}
          >
            <span
              aria-hidden="true"
              className={cx(
                "flex size-10 items-center justify-center rounded-[10px] bg-white shadow-sh transition-transform duration-200 ease-pop group-hover:scale-105 motion-reduce:transition-none",
                tone.split(" ")[1],
              )}
            >
              <Icon size={20} />
            </span>
            <b className="text-sm font-semibold">{t(`actions.${key}`)}</b>
          </NextLink>
        ))}
      </div>
    </Section>
  );
}

type Alert = { key: "lowStock" | "dispatch" | "reconcile" | "reviews"; href: string; Icon: LucideIcon; tone: string; count?: number };

function SystemAlerts({ alerts }: { alerts: (Alert | false)[] }) {
  const t = useTranslations("admin.dashboard");
  const shown = alerts.filter((a): a is Alert => Boolean(a));
  if (shown.length === 0) return null;
  return (
    <Section title={t("systemAlerts")}>
      <ul className="m-0 -my-1 flex list-none flex-col divide-y divide-subtle p-0">
        {shown.map(({ key, href, Icon, tone, count }) => (
          <li key={key} className="flex items-center gap-3 py-3">
            <span aria-hidden="true" className={cx("flex size-10 flex-none items-center justify-center rounded-full", count === 0 ? "bg-ok-bg text-ok-tx" : tone)}>
              <Icon size={18} />
            </span>
            <span className="flex min-w-0 grow flex-col">
              <b className="text-sm font-semibold">{t(`alerts.${key}.title`)}</b>
              {count === undefined ? <Skeleton className="mt-1 h-4 w-36" /> : <span className="text-cap text-tx2">{t(`alerts.${key}.body`, { count })}</span>}
            </span>
            <NextLink href={href} aria-label={t("alerts.view", { name: t(`alerts.${key}.title`) })} className="group flex items-center gap-1 text-sm font-semibold whitespace-nowrap text-pri-h no-underline hover:text-pri">
              <span aria-hidden="true">{t("alerts.viewShort")}</span>
              <ArrowRight size={14} aria-hidden="true" className="transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none" />
            </NextLink>
          </li>
        ))}
      </ul>
    </Section>
  );
}
