/** Whole-RWF amounts as typed in admin forms. */

/** The backend's MAX_MONEY_RWF. */
const MAX_MONEY = 999_999_999_999;

/** "520,000" or "520000" → 520000; anything else → null. */
export function parseAmount(text: string): number | null {
  const clean = text.replace(/[\s,]/g, "");
  if (!/^\d+$/.test(clean)) return null;
  const value = Number(clean);
  return value <= MAX_MONEY ? value : null;
}

/** 520000 → "520,000" (how the editor shows amounts; parseAmount reads it back). */
export function groupDigits(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}
