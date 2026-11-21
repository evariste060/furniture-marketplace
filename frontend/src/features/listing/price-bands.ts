import type { components } from "@/lib/api/schema";

export type PriceBand = Pick<components["schemas"]["PriceBandFacet"], "min_price" | "max_price">;

const groups = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function bandKey(band: PriceBand): string {
  return `${band.min_price ?? ""}-${band.max_price ?? ""}`;
}

/** 200000 → "200k", 1000000 → "1M" (the mobile chips). */
export function shortAmount(n: number): string {
  if (n >= 1_000_000 && n % 100_000 === 0) return `${n / 1_000_000}M`;
  if (n >= 1000 && n % 1000 === 0) return `${n / 1000}k`;
  return groups.format(n);
}

type T = (key: "under" | "between" | "above", values: Record<string, string>) => string;

/** The band as the design labels it. The API's bands end one franc below the next band's start
 * (200,000–399,999), so the upper bound is shown rounded up: "200,000 – 400,000". */
export function bandLabel(band: PriceBand, t: T, style: "long" | "short"): string {
  const fmt = style === "long" ? (n: number) => groups.format(n) : shortAmount;
  const top = band.max_price === null || band.max_price === undefined ? null : band.max_price + 1;
  const bottom = band.min_price ?? null;
  if (bottom === null && top !== null) return t("under", { max: fmt(top) });
  if (bottom !== null && top === null) return t("above", { min: fmt(bottom) });
  return t("between", { min: fmt(bottom ?? 0), max: fmt(top ?? 0) });
}
