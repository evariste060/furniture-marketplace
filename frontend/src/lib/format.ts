/** Display formats for the storefront and admin: amounts are whole RWF (ADR-007), phones are
 * Rwandan mobiles, and dates are shown in Kigali time whatever the viewer's time zone. */

export const KIGALI_TIME_ZONE = "Africa/Kigali";

const groups = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** 580000 → "RWF 580,000". */
export function formatMoney(amount: number): string {
  return `RWF ${groups.format(Math.round(amount))}`;
}

/** "+250788123456", "250788123456" or "0788123456" → "+250 788 123 456". Anything else is
 * returned unchanged. */
export function formatPhone(value: string): string {
  const digits = value.replace(/\D/g, "");
  const local = digits.startsWith("250") ? digits.slice(3) : digits.replace(/^0/, "");
  if (!/^7\d{8}$/.test(local)) return value;
  return `+250 ${local.slice(0, 3)} ${local.slice(3, 6)} ${local.slice(6)}`;
}

const DATE_STYLES = {
  date: { day: "numeric", month: "short", year: "numeric" },
  dateTime: { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
  time: { hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
  dayTime: { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" },
} as const satisfies Record<string, Intl.DateTimeFormatOptions>;

/** An ISO timestamp in Kigali time, e.g. "24 Oct 2026" or "24 Oct 2026, 09:40". */
export function formatDate(
  value: string | Date,
  style: keyof typeof DATE_STYLES = "date",
  locale = "en-GB",
): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return new Intl.DateTimeFormat(locale, { ...DATE_STYLES[style], timeZone: KIGALI_TIME_ZONE }).format(date);
}
