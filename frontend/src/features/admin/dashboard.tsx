"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Building2,
  Headset,
  HandCoins,
  MessageSquare,
  ShoppingCart,
  Store,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { useStaffAccess } from "./access";
import type { Permission } from "./nav";
import { timeAgo } from "./time";
import { LoadError, must, PageHeader } from "./ui";

export { timeAgo };

/** The overview's windows (SC-06): a month by day, a quarter by week, a year by month. */
const PERIODS = [30, 90, 365] as const;
type Period = (typeof PERIODS)[number];
const GROUP_BY: Record<Period, "day" | "week" | "month"> = {
  30: "day",
  90: "week",
  365: "month",
};
const DAY = 24 * 60 * 60 * 1000;
const KIGALI = "Africa/Kigali";

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
export function percentChange(
  current: number,
  previous: number,
): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

/** A Kigali calendar day (YYYY-MM-DD), the reports' date format. */
function kigaliDay(time: number): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: KIGALI,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(time));
}

/** The reports' day windows: the last `days` Kigali days (today included) and the ones before. */
export function reportWindows(days: number, now: number) {
  return {
    current: { from: kigaliDay(now - (days - 1) * DAY), to: kigaliDay(now) },
    previous: {
      from: kigaliDay(now - (2 * days - 1) * DAY),
      to: kigaliDay(now - days * DAY),
    },
  };
}

/** A round axis top and step for values up to `max` (4 steps). */
export function niceScale(max: number): { top: number; step: number } {
  if (max <= 0) return { top: 4, step: 1 };
  const raw = max / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ??
    10 * power;
  return { top: step * 4, step };
}

/** 6450000 → "6.5M", 12000 → "12K". */
export function compactNumber(value: number, digits = 1): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: digits,
  }).format(value);
}

/** Large amounts shortened on the KPI cards ("RWF 4.87M"), the exact amount in the title. */
function shortMoney(value: number | undefined): string | undefined {
  if (value === undefined) return undefined;
  return value >= 1_000_000
    ? `RWF ${compactNumber(value, 2)}`
    : formatMoney(value);
}

type MarketplaceReport = components["schemas"]["MarketplaceReport"];

type TaskKey =
  "applications" | "reviews" | "messages" | "quotes";

/** How many wait, from each list's total (one row asked for). */
async function waitingCount(key: TaskKey): Promise<number> {
  switch (key) {
    case "applications":
      return (
        await must(
          browserApi.GET("/api/v1/staff/sellers", {
            params: { query: { status: "pending", size: 1 } },
          }),
        )
      ).total;
    case "reviews":
      return (
        await must(
          browserApi.GET("/api/v1/staff/reviews", {
            params: { query: { status: "pending", size: 1 } },
          }),
        )
      ).total;
    case "messages":
      return (
        await must(
          browserApi.GET("/api/v1/staff/support-threads", {
            params: { query: { status: "open", size: 1 } },
          }),
        )
      ).total;
    case "quotes":
      return (
        await must(
          browserApi.GET("/api/v1/staff/quote-requests", {
            params: { query: { status: "new", size: 1 } },
          }),
        )
      ).total;
  }
}

/** The marketplace overview (SC-06, ADR-014 phase 7): platform health and growth from GET
 * /staff/reports/marketplace, and the decisions waiting for the administrator. Store operations
 * (orders, stock, payments) are the sellers' and are not shown here. */
export function Dashboard() {
  const t = useTranslations("admin.dashboard");
  const { can, fullName } = useStaffAccess();
  const [period, setPeriod] = useState<Period>(30);
  // One "now" for the page, so the query keys stay the same while it is open.
  const [now] = useState(() => Math.floor(Date.now() / 60_000) * 60_000);
  const days = reportWindows(period, now);
  const reportsOn = can("reports:read");
  const groupBy = GROUP_BY[period];

  const reports = useQueries({
    queries: [days.current, days.previous].map((window) => ({
      queryKey: ["admin", "dashboard", "marketplace", window, groupBy],
      enabled: reportsOn,
      queryFn: () =>
        must(
          browserApi.GET("/api/v1/staff/reports/marketplace", {
            params: { query: { ...window, group_by: groupBy } },
          }),
        ),
    })),
  });
  const top = useQuery({
    queryKey: ["admin", "dashboard", "top", days.current],
    enabled: reportsOn,
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/reports/top-products", {
          params: { query: { ...days.current, limit: 5 } },
        }),
      ),
  });
  const waiting = useQueries({
    queries: TASKS.map((task) => ({
      queryKey: ["admin", "dashboard", "waiting", task.key],
      enabled: can(task.perm),
      queryFn: () => waitingCount(task.key),
    })),
  });

  const all = [...reports, top, ...waiting];
  const failed = all.some((q) => q.isError);
  const retry = () => all.forEach((q) => q.isError && q.refetch());

  const report = reports[0].data;
  const previous = reports[1].data;
  const change = (pick: (r: MarketplaceReport) => number) =>
    report && previous
      ? percentChange(pick(report), pick(previous))
      : undefined;
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: KIGALI,
      hour: "2-digit",
      hourCycle: "h23",
    }).format(new Date(now)),
  );
  const greeting = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
  const firstName = fullName.trim().split(/\s+/)[0] || fullName;
  const note = t("vsPreviousDays", { days: period });

  return (
    <>
      <PageHeader
        title={
          <span suppressHydrationWarning>{t(`greeting.${greeting}`, { name: firstName })}</span>
        }
        description={t("subtitle")}
        actions={
          reportsOn ? (
            <Select
              aria-label={t("period")}
              value={period}
              onChange={(e) => setPeriod(Number(e.target.value) as Period)}
              className="h-10 w-44 bg-card text-sm shadow-sh"
            >
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

      {reportsOn && (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-4">
            <Kpi
              href="/admin/analytics"
              Icon={Wallet}
              variant="navy"
              label={t("goodsSales")}
              value={shortMoney(report?.totals.merchandise_total)}
              title={
                report
                  ? formatMoney(report.totals.merchandise_total)
                  : undefined
              }
              change={change((r) => r.totals.merchandise_total)}
              note={note}
            />
            <Kpi
              href="/admin/analytics"
              Icon={HandCoins}
              variant="blue"
              label={t("commission")}
              value={shortMoney(report?.totals.commission_amount)}
              title={
                report
                  ? formatMoney(report.totals.commission_amount)
                  : undefined
              }
              change={change((r) => r.totals.commission_amount)}
              note={note}
            />
            <Kpi
              href="/admin/analytics"
              Icon={ShoppingCart}
              variant="light"
              label={t("orders")}
              value={report?.totals.orders.toLocaleString("en-US")}
              change={change((r) => r.totals.orders)}
              note={note}
            />
            <Kpi
              href="/admin/sellers?status=approved"
              Icon={Store}
              variant="purple"
              label={t("approvedStores")}
              value={report?.stores.approved.toLocaleString("en-US")}
              note={
                report
                  ? t("newInPeriod", { count: report.totals.new_stores })
                  : note
              }
            />
          </div>
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            <TrendOverview report={report} previous={previous} />
            <MarketplaceCard report={report} />
          </div>
        </>
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(300px,1fr))] gap-5">
        <Attention
          tasks={TASKS.map(
            (task, i) => can(task.perm) && { ...task, count: waiting[i].data },
          )}
        />
        {reportsOn && <TopProducts items={top.data?.items} />}
      </div>
    </>
  );
}

/** What waits for the administrator: seller applications, reviews, support and quote requests. */
const TASKS: {
  key: TaskKey;
  href: string;
  perm: Permission;
  Icon: LucideIcon;
  tone: string;
}[] = [
  {
    key: "applications",
    href: "/admin/sellers?status=pending",
    perm: "sellers:read",
    Icon: Store,
    tone: "bg-light text-pri-h",
  },
  {
    key: "reviews",
    href: "/admin/reviews",
    perm: "reviews:moderate",
    Icon: MessageSquare,
    tone: "bg-pur-bg text-pur",
  },
  {
    key: "messages",
    href: "/admin/messages",
    perm: "support:read",
    Icon: Headset,
    tone: "bg-warn-bg text-warn-tx",
  },
  {
    key: "quotes",
    href: "/admin/quotes",
    perm: "quotes:manage",
    Icon: Building2,
    tone: "bg-ok-bg text-ok-tx",
  },
];

/** Every clickable dashboard card: lifts a little on hover, with a stronger shadow. */
const CARD_LINK =
  "group rounded-xl no-underline transition-[border-color,box-shadow,translate] duration-200 ease-soft hover:-translate-y-0.5 hover:shadow-sh2 motion-reduce:transition-none motion-reduce:hover:translate-y-0";

const KPI_STYLE = {
  navy: {
    card: "bg-navy text-white hover:text-white",
    icon: "bg-white/15 text-white",
    note: "text-white/75",
    ghost: "text-white/10",
  },
  blue: {
    card: "bg-pri text-white hover:text-white",
    icon: "bg-white/20 text-white",
    note: "text-white/80",
    ghost: "text-white/15",
  },
  light: {
    card: "border border-pri/20 bg-light text-tx hover:text-tx",
    icon: "bg-card text-pri-h",
    note: "text-tx2",
    ghost: "text-pri/10",
  },
  purple: {
    card: "border border-pur/20 bg-pur-bg text-tx hover:text-tx",
    icon: "bg-card text-pur",
    note: "text-tx2",
    ghost: "text-pur/10",
  },
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
    <NextLink
      href={href}
      className={cx(
        CARD_LINK,
        "relative flex min-h-[148px] flex-col gap-2 overflow-hidden p-5 shadow-sh",
        style.card,
      )}
    >
      <Icon
        aria-hidden="true"
        size={92}
        strokeWidth={1.5}
        className={cx(
          "pointer-events-none absolute -right-3 -bottom-4",
          style.ghost,
        )}
      />
      <span className="relative flex items-center gap-2.5">
        <span
          aria-hidden="true"
          className={cx(
            "flex size-9 flex-none items-center justify-center rounded-lg",
            style.icon,
          )}
        >
          <Icon size={18} />
        </span>
        <span className="text-sm font-semibold">{label}</span>
      </span>
      <span className="relative">
        {value === undefined ? (
          <Skeleton className={cx("h-9 w-28", dark && "bg-white/20")} />
        ) : (
          <b title={title} className="t-price-l block truncate tabular-nums">
            {value}
            {title && title !== value && (
              <span className="sr-only"> ({title})</span>
            )}
          </b>
        )}
      </span>
      <span className="relative mt-auto flex flex-wrap items-center gap-2">
        {change !== undefined && change !== null && (
          <span
            className={cx(
              "inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-cap font-semibold tabular-nums",
              change >= 0 ? "bg-ok-bg text-ok-tx" : "bg-err-bg text-err-tx",
            )}
          >
            {change > 0 ? (
              <ArrowUp size={12} aria-hidden="true" />
            ) : change < 0 ? (
              <ArrowDown size={12} aria-hidden="true" />
            ) : null}
            <span className="sr-only">
              {change === 0
                ? t("flat")
                : change > 0
                  ? t("up", { percent: change })
                  : t("down", { percent: -change })}
            </span>
            <span aria-hidden="true">
              {change > 0 ? "+" : ""}
              {change}%
            </span>
          </span>
        )}
        <span className={cx("text-cap", style.note)}>{note}</span>
      </span>
    </NextLink>
  );
}

/** A dashboard panel: the title row, then its content. */
function Section({
  title,
  link,
  action,
  children,
  className,
}: {
  title: string;
  link?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cx(
        "flex min-w-0 flex-col rounded-xl border border-bd bg-card shadow-sh",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5 pb-3 max-sm:px-4">
        <h2 className="t-h3">{title}</h2>
        {action ?? link}
      </div>
      <div className="flex grow flex-col gap-3.5 px-6 pb-6 max-sm:px-4 max-sm:pb-4">
        {children}
      </div>
    </section>
  );
}

/** "View all →" in a panel's title row. */
function SectionLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <NextLink
      href={href}
      className="group flex items-center gap-1 rounded-md text-sm font-semibold text-pri-h no-underline hover:text-pri-fg"
    >
      {children}
      <ArrowRight
        size={14}
        aria-hidden="true"
        className="transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none"
      />
    </NextLink>
  );
}

const dayLabel = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});
const monthLabel = new Intl.DateTimeFormat("en-GB", {
  month: "short",
  timeZone: "UTC",
});
const fullDay = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const asDate = (day: string) => new Date(`${day.slice(0, 10)}T12:00:00Z`);

const fullMonth = new Intl.DateTimeFormat("en-GB", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
type TrendMetric = "merchandise_total" | "commission_amount" | "orders";
const TREND_METRICS: TrendMetric[] = [
  "merchandise_total",
  "commission_amount",
  "orders",
];

/** The marketplace trend: goods sold by the stores, the platform's commission or orders per day,
 * week or month, from the marketplace report. */
function TrendOverview({
  report,
  previous,
}: {
  report?: MarketplaceReport;
  previous?: MarketplaceReport;
}) {
  const t = useTranslations("admin.dashboard");
  const [metric, setMetric] = useState<TrendMetric>("merchandise_total");
  const [hover, setHover] = useState<number | null>(null);
  const periods = report?.periods ?? [];
  const values = periods.map((p) => p[metric]);
  const total = report?.totals[metric];
  const change =
    total !== undefined && previous
      ? percentChange(total, previous.totals[metric])
      : null;
  const { top, step } = niceScale(Math.max(0, ...values));
  const n = values.length;
  const x = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);
  const y = (v: number) => 100 - (v / top) * 100;
  const line = values
    .map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`)
    .join(" ");
  const area = n ? `${line} L${x(n - 1)},100 L${x(0)},100 Z` : "";
  const shown = hover ?? n - 1;
  const pointDate = (i: number) => {
    const start = asDate(periods[i].period_start);
    if (report?.group_by === "month") return fullMonth.format(start);
    if (report?.group_by === "week")
      return t("weekOf", { date: dayLabel.format(start) });
    return fullDay.format(start);
  };
  const format = (v: number) =>
    metric === "orders" ? t("ordersCount", { count: v }) : formatMoney(v);
  // About six date labels under the chart.
  const every = Math.max(1, Math.ceil(n / 6));
  const tickLabel = (day: string) =>
    report?.group_by === "month"
      ? monthLabel.format(asDate(day))
      : dayLabel.format(asDate(day));
  const ticks = periods
    .map((p, i) => ({ i, label: tickLabel(p.period_start) }))
    .filter(({ i }) => i % every === 0);

  return (
    <Section
      title={t("trend")}
      action={
        <div
          role="group"
          aria-label={t("metricLabel")}
          className="flex flex-wrap rounded-lg bg-page p-1"
        >
          {TREND_METRICS.map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={metric === m}
              onClick={() => setMetric(m)}
              className={cx(
                "h-8 cursor-pointer rounded-md border-0 px-3.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                metric === m
                  ? "bg-pri text-white shadow-sh"
                  : "bg-transparent text-tx2 hover:text-tx",
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
              <span
                className={cx(
                  "inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-cap font-semibold",
                  change >= 0 ? "bg-ok-bg text-ok-tx" : "bg-err-bg text-err-tx",
                )}
              >
                {change >= 0 ? (
                  <ArrowUp size={12} aria-hidden="true" />
                ) : (
                  <ArrowDown size={12} aria-hidden="true" />
                )}
                <span className="sr-only">
                  {change >= 0
                    ? t("up", { percent: change })
                    : t("down", { percent: -change })}
                </span>
                <span aria-hidden="true">
                  {change > 0 ? "+" : ""}
                  {change}%
                </span>
              </span>
            )}
          </div>
          {values.every((v) => v === 0) ? (
            <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-bd text-sm text-tx2">
              {t("noSales")}
            </div>
          ) : (
            <div className="grid grow grid-cols-[auto_minmax(0,1fr)] grid-rows-[minmax(16rem,1fr)_auto] gap-x-3">
              {/* The value axis. */}
              <div
                aria-hidden="true"
                className="flex h-full flex-col justify-between text-right text-cap text-tx2 tabular-nums"
              >
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
                aria-valuetext={
                  n
                    ? `${pointDate(shown)}: ${format(values[shown])}`
                    : undefined
                }
                aria-label={t("chartLabel", {
                  metric: t(`metric.${metric}`),
                  from: fullDay.format(asDate(report.from)),
                  to: fullDay.format(asDate(report.to)),
                  total: format(total ?? 0),
                })}
                onPointerMove={(e) => {
                  const box = e.currentTarget.getBoundingClientRect();
                  setHover(
                    Math.max(
                      0,
                      Math.min(
                        n - 1,
                        Math.round(
                          ((e.clientX - box.left) / box.width) * (n - 1),
                        ),
                      ),
                    ),
                  );
                }}
                onPointerLeave={() => setHover(null)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft" || e.key === "ArrowDown")
                    setHover(Math.max(0, shown - 1));
                  if (e.key === "ArrowRight" || e.key === "ArrowUp")
                    setHover(Math.min(n - 1, shown + 1));
                  if (e.key === "Home") setHover(0);
                  if (e.key === "End") setHover(n - 1);
                }}
                onBlur={() => setHover(null)}
                className="relative h-full touch-none rounded-sm outline-offset-4 focus-visible:outline-2 focus-visible:outline-pri"
              >
                {[0, 25, 50, 75, 100].map((p) => (
                  <span
                    key={p}
                    aria-hidden="true"
                    className={cx(
                      "absolute inset-x-0 h-px",
                      p === 100 ? "bg-bd" : "bg-subtle",
                    )}
                    style={{ top: `${p}%` }}
                  />
                ))}
                <svg
                  aria-hidden="true"
                  viewBox="0 0 100 100"
                  preserveAspectRatio="none"
                  className="absolute inset-0 size-full overflow-visible"
                >
                  <defs>
                    <linearGradient id="sales-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="0%"
                        stopColor="var(--color-pri)"
                        stopOpacity="0.28"
                      />
                      <stop
                        offset="100%"
                        stopColor="var(--color-pri)"
                        stopOpacity="0.02"
                      />
                    </linearGradient>
                  </defs>
                  <path d={area} fill="url(#sales-fill)" />
                  <path
                    d={line}
                    fill="none"
                    stroke="var(--color-pri)"
                    strokeWidth="2.5"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
                {n > 0 && (
                  <>
                    <span
                      aria-hidden="true"
                      className="absolute top-0 bottom-0 w-px bg-pri/30"
                      style={{ left: `${x(shown)}%` }}
                    />
                    <span
                      aria-hidden="true"
                      className="absolute size-3 -translate-1/2 rounded-full border-2 border-white bg-pri shadow-sh"
                      style={{
                        left: `${x(shown)}%`,
                        top: `${y(values[shown])}%`,
                      }}
                    />
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute z-10 flex flex-col rounded-lg border border-bd bg-card px-3 py-2 whitespace-nowrap shadow-sh2"
                      style={{
                        left: `${x(shown)}%`,
                        top: `${y(values[shown])}%`,
                        translate: `${x(shown) > 70 ? "-100%" : x(shown) < 30 ? "0" : "-50%"} calc(-100% - 12px)`,
                      }}
                    >
                      <b className="text-sm font-semibold tabular-nums">
                        {format(values[shown])}
                      </b>
                      <span className="text-cap text-tx2">
                        {pointDate(shown)}
                      </span>
                    </span>
                  </>
                )}
              </div>
              <span />
              <div
                aria-hidden="true"
                className="relative mt-2 h-4 text-cap text-tx2"
              >
                {ticks.map(({ i, label }) => (
                  <span
                    key={i}
                    className="absolute whitespace-nowrap"
                    style={{
                      left: `${x(i)}%`,
                      translate:
                        i === 0 ? "0 0" : i === n - 1 ? "-100% 0" : "-50% 0",
                    }}
                  >
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

/** The marketplace now: stores by status, customer accounts and products on the storefront. */
function MarketplaceCard({ report }: { report?: MarketplaceReport }) {
  const t = useTranslations("admin.dashboard");
  const rows: {
    key: string;
    href?: string;
    value?: number;
    note?: string;
    tone?: string;
  }[] = [
    {
      key: "approved",
      href: "/admin/sellers?status=approved",
      value: report?.stores.approved,
      tone: "bg-ok",
    },
    {
      key: "pending",
      href: "/admin/sellers?status=pending",
      value: report?.stores.pending,
      tone: "bg-warn",
    },
    {
      key: "suspended",
      href: "/admin/sellers?status=suspended",
      value: report?.stores.suspended,
      tone: "bg-err",
    },
    {
      key: "rejected",
      href: "/admin/sellers?status=rejected",
      value: report?.stores.rejected,
      tone: "bg-mut",
    },
  ];
  return (
    <Section
      title={t("marketplace")}
      link={<SectionLink href="/admin/sellers">{t("viewSellers")}</SectionLink>}
    >
      <ul className="m-0 -my-1 flex list-none flex-col divide-y divide-subtle p-0">
        {rows.map(({ key, href, value, tone }) => (
          <li key={key} className="flex items-center gap-3 py-2.5">
            <span
              aria-hidden="true"
              className={cx("size-2.5 flex-none rounded-full", tone)}
            />
            <NextLink
              href={href ?? "#"}
              className="grow text-sm text-tx no-underline hover:text-pri-h hover:underline"
            >
              {t(`stores.${key}`)}
            </NextLink>
            {value === undefined ? (
              <Skeleton className="h-5 w-10" />
            ) : (
              <b className="text-sm font-semibold tabular-nums">
                {value.toLocaleString("en-US")}
              </b>
            )}
          </li>
        ))}
      </ul>
      <div className="grid grid-cols-2 gap-3 border-t border-subtle pt-3.5">
        <Figure
          label={t("customers")}
          value={report?.customers}
          note={
            report
              ? t("newInPeriod", { count: report.totals.new_customers })
              : undefined
          }
        />
        <Figure
          label={t("publishedProducts")}
          value={report?.published_products}
          href="/admin/products?status=active"
        />
      </div>
    </Section>
  );
}

function Figure({
  label,
  value,
  note,
  href,
}: {
  label: string;
  value?: number;
  note?: string;
  href?: string;
}) {
  const body = (
    <>
      <span className="text-cap text-tx2">{label}</span>
      {value === undefined ? (
        <Skeleton className="h-7 w-16" />
      ) : (
        <b className="t-h2 tabular-nums">{value.toLocaleString("en-US")}</b>
      )}
      {note && <span className="text-cap text-tx2">{note}</span>}
    </>
  );
  return href ? (
    <NextLink
      href={href}
      className="flex flex-col gap-0.5 rounded-lg text-tx no-underline hover:text-pri-h"
    >
      {body}
    </NextLink>
  ) : (
    <div className="flex flex-col gap-0.5">{body}</div>
  );
}

type TopRow = components["schemas"]["TopProduct"];

function TopProducts({ items }: { items?: TopRow[] }) {
  const t = useTranslations("admin.dashboard");
  return (
    <Section title={t("topSelling")}>
      {!items ? (
        Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))
      ) : items.length === 0 ? (
        <p className="text-tx2">{t("noTopSelling")}</p>
      ) : (
        <ol className="m-0 -my-1 flex list-none flex-col divide-y divide-subtle p-0">
          {items.map((item) => {
            const name = (
              <b className="truncate text-sm font-semibold">
                {item.product_name}
              </b>
            );
            return (
              <li
                key={`${item.rank}-${item.product_name}`}
                className="flex items-center gap-3 py-2.5"
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    "flex size-9 flex-none items-center justify-center rounded-lg text-sm font-bold tabular-nums",
                    item.rank === 1
                      ? "bg-pri text-white"
                      : item.rank <= 3
                        ? "bg-light text-pri-h"
                        : "bg-subtle text-tx2",
                  )}
                >
                  {item.rank}
                </span>
                <span className="flex min-w-0 grow flex-col">
                  {item.product_id ? (
                    <NextLink
                      href={`/admin/products/${item.product_id}`}
                      className="truncate text-tx no-underline hover:text-pri-h hover:underline"
                    >
                      {name}
                    </NextLink>
                  ) : (
                    name
                  )}
                  <span className="text-cap text-tx2">
                    {t("sold", { count: item.units })}
                  </span>
                </span>
                <b className="text-sm font-semibold whitespace-nowrap tabular-nums">
                  {formatMoney(item.revenue)}
                </b>
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}

type Task = (typeof TASKS)[number] & { count?: number };

/** Needs your attention: the marketplace decisions waiting, each with a link to act on it. */
function Attention({ tasks }: { tasks: (Task | false)[] }) {
  const t = useTranslations("admin.dashboard");
  const shown = tasks.filter((a): a is Task => Boolean(a));
  if (shown.length === 0) return null;
  return (
    <Section title={t("attention")}>
      <ul className="m-0 -my-1 flex list-none flex-col divide-y divide-subtle p-0">
        {shown.map(({ key, href, Icon, tone, count }) => (
          <li key={key} className="flex items-center gap-3 py-3">
            <span
              aria-hidden="true"
              className={cx(
                "flex size-10 flex-none items-center justify-center rounded-full",
                count === 0 ? "bg-ok-bg text-ok-tx" : tone,
              )}
            >
              <Icon size={18} />
            </span>
            <span className="flex min-w-0 grow flex-col">
              <b className="text-sm font-semibold">{t(`tasks.${key}.title`)}</b>
              {count === undefined ? (
                <Skeleton className="mt-1 h-4 w-36" />
              ) : (
                <span className="text-cap text-tx2">
                  {t(`tasks.${key}.body`, { count })}
                </span>
              )}
            </span>
            <NextLink
              href={href}
              aria-label={t("tasks.view", { name: t(`tasks.${key}.title`) })}
              className="group flex items-center gap-1 text-sm font-semibold whitespace-nowrap text-pri-h no-underline hover:text-pri-fg"
            >
              <span aria-hidden="true">{t("tasks.viewShort")}</span>
              <ArrowRight
                size={14}
                aria-hidden="true"
                className="transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none"
              />
            </NextLink>
          </li>
        ))}
      </ul>
    </Section>
  );
}
