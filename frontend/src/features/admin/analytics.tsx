"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { formatMoney } from "@/lib/format";
import { reportWindows } from "./dashboard";
import { LoadError, must, PageHeader } from "./ui";

type MarketplaceReport = components["schemas"]["MarketplaceReport"];
type Figures = components["schemas"]["MarketplaceFigures"];

/** The windows offered, each with its natural grouping (as on the overview). */
const RANGES = [30, 90, 365] as const;
type Range = (typeof RANGES)[number];
const GROUP_BY: Record<Range, "day" | "week" | "month"> = {
  30: "day",
  90: "week",
  365: "month",
};

const COLUMNS: (keyof Figures)[] = [
  "orders",
  "merchandise_total",
  "commission_amount",
  "new_stores",
  "new_customers",
];
const MONEY = new Set<keyof Figures>([
  "merchandise_total",
  "commission_amount",
]);

const day = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const month = new Intl.DateTimeFormat("en-GB", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const asDate = (value: string) => new Date(`${value.slice(0, 10)}T12:00:00Z`);

/** A period's label: the month, or the first (and last) day of a day or week. */
export function periodLabel(
  groupBy: MarketplaceReport["group_by"],
  start: string,
  end: string,
): string {
  if (groupBy === "month") return month.format(asDate(start));
  if (start === end) return day.format(asDate(start));
  return `${day.format(asDate(start))} – ${day.format(asDate(end))}`;
}

/** The browser download of a report's Excel export, through the app's API proxy (the session
 * cookie goes with it; reports:read is checked by the backend). */
export function exportHref(
  type: "sales" | "top-products",
  query: Record<string, string | number>,
): string {
  const params = new URLSearchParams(
    Object.entries(query).map(([k, v]) => [k, String(v)]),
  );
  return `/api/backend/api/v1/staff/reports/${type}/export?${params}`;
}

/** Analytics & Reports (SC-06, ADR-014 phase 7): the marketplace's growth per period from GET
 * /staff/reports/marketplace, the best-selling products, and the Excel exports. Aggregates only:
 * no customer, seller or order is shown. */
export function AnalyticsView() {
  const t = useTranslations("admin.analytics");
  const [range, setRange] = useState<Range>(90);
  const [now] = useState(() => Math.floor(Date.now() / 60_000) * 60_000);
  const window = reportWindows(range, now).current;
  const groupBy = GROUP_BY[range];

  const report = useQuery({
    queryKey: ["admin", "analytics", "marketplace", window, groupBy],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/reports/marketplace", {
          params: { query: { ...window, group_by: groupBy } },
        }),
      ),
  });
  const top = useQuery({
    queryKey: ["admin", "analytics", "top", window],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/reports/top-products", {
          params: { query: { ...window, limit: 10 } },
        }),
      ),
  });
  const failed = report.isError || top.isError;
  const salesGroup = groupBy === "day" ? "day" : "week";
  const value = (key: keyof Figures, n: number) =>
    MONEY.has(key) ? formatMoney(n) : n.toLocaleString("en-US");

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Select
            aria-label={t("range")}
            value={range}
            onChange={(e) => setRange(Number(e.target.value) as Range)}
            className="h-10 w-44 bg-white text-sm shadow-sh"
          >
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {t(`ranges.${r}`)}
              </option>
            ))}
          </Select>
        }
      />
      {failed && (
        <LoadError
          onRetry={() => {
            if (report.isError) void report.refetch();
            if (top.isError) void top.refetch();
          }}
        />
      )}

      <Card padding="none" className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5 pb-3 max-sm:px-4">
          <div className="flex flex-col gap-0.5">
            <h2 className="t-h3">{t("growth")}</h2>
            <p className="text-sm text-tx2">{t("growthHelp")}</p>
          </div>
          <a
            href={exportHref("sales", { ...window, group_by: salesGroup })}
            download
            className={buttonClasses({
              variant: "neutral",
              size: "sm",
              className: "gap-2",
            })}
          >
            <Download size={16} aria-hidden="true" />
            {t("exportSales")}
          </a>
        </div>
        <div className="overflow-x-auto">
          <Table aria-busy={report.isFetching}>
            <thead>
              <tr>
                <Th>{t("period")}</Th>
                {COLUMNS.map((c) => (
                  <Th key={c} className="text-right">
                    {t(`columns.${c}`)}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!report.data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={COLUMNS.length + 1}>
                        <Skeleton className="h-6 w-full" />
                      </Td>
                    </tr>
                  ))
                : [...report.data.periods].reverse().map((p) => (
                    <tr key={p.period_start}>
                      <Td className="whitespace-nowrap">
                        {periodLabel(
                          report.data.group_by,
                          p.period_start,
                          p.period_end,
                        )}
                      </Td>
                      {COLUMNS.map((c) => (
                        <Td
                          key={c}
                          className="text-right whitespace-nowrap tabular-nums"
                        >
                          {value(c, p[c])}
                        </Td>
                      ))}
                    </tr>
                  ))}
            </tbody>
            {report.data && (
              <tfoot>
                <tr className="border-t border-bd bg-page font-semibold">
                  <Td>{t("total")}</Td>
                  {COLUMNS.map((c) => (
                    <Td
                      key={c}
                      className="text-right whitespace-nowrap tabular-nums"
                    >
                      {value(c, report.data.totals[c])}
                    </Td>
                  ))}
                </tr>
              </tfoot>
            )}
          </Table>
        </div>
      </Card>

      <Card padding="none" className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-5 pb-3 max-sm:px-4">
          <h2 className="t-h3">{t("topProducts")}</h2>
          <a
            href={exportHref("top-products", { ...window, limit: 10 })}
            download
            className={buttonClasses({
              variant: "neutral",
              size: "sm",
              className: "gap-2",
            })}
          >
            <Download size={16} aria-hidden="true" />
            {t("exportTop")}
          </a>
        </div>
        <div className="overflow-x-auto">
          <Table aria-busy={top.isFetching}>
            <thead>
              <tr>
                <Th className="w-12">#</Th>
                <Th>{t("product")}</Th>
                <Th className="text-right">{t("units")}</Th>
                <Th className="text-right">{t("orders")}</Th>
                <Th className="text-right">{t("revenue")}</Th>
              </tr>
            </thead>
            <tbody>
              {!top.data ? (
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <Td colSpan={5}>
                      <Skeleton className="h-6 w-full" />
                    </Td>
                  </tr>
                ))
              ) : top.data.items.length === 0 ? (
                <tr>
                  <Td colSpan={5} className="py-8 text-center text-tx2">
                    {t("noSales")}
                  </Td>
                </tr>
              ) : (
                top.data.items.map((item) => (
                  <tr key={`${item.rank}-${item.product_name}`}>
                    <Td className="tabular-nums">{item.rank}</Td>
                    <Td>{item.product_name}</Td>
                    <Td className="text-right tabular-nums">
                      {item.units.toLocaleString("en-US")}
                    </Td>
                    <Td className="text-right tabular-nums">
                      {item.orders.toLocaleString("en-US")}
                    </Td>
                    <Td className="text-right whitespace-nowrap tabular-nums">
                      {formatMoney(item.revenue)}
                    </Td>
                  </tr>
                ))
              )}
            </tbody>
          </Table>
        </div>
      </Card>
    </>
  );
}
