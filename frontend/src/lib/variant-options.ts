import type { CatalogVariant } from "./catalogue";

/** The product page's option groups (Product.dc.html: Colour, Storage …) from the variants'
 * attributes. A group is an attribute key whose text values differ between variants; when no
 * attribute tells the variants apart, one "variant" group lists them by name. */

export type OptionGroup = { key: string; values: string[] };

/** The variant-name group's key. */
export const VARIANT_GROUP = "variant";
const FIRST = ["colour", "color", "storage", "ram", "size"];

function text(value: unknown): string | null {
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** The variant's value for a group. */
export function optionValue(variant: CatalogVariant, key: string): string | null {
  return key === VARIANT_GROUP ? variant.name : text(variant.attributes[key]);
}

function rank(key: string): number {
  const index = FIRST.indexOf(key.toLowerCase());
  return index === -1 ? FIRST.length : index;
}

export function optionGroups(variants: readonly CatalogVariant[]): OptionGroup[] {
  if (variants.length < 2) return [];
  const keys = [...new Set(variants.flatMap((v) => Object.keys(v.attributes)))];
  const groups = keys
    .map((key) => ({
      key,
      values: [...new Set(variants.map((v) => text(v.attributes[key])).filter((v): v is string => v !== null))],
    }))
    // Every variant needs a value, and the values must tell some variants apart.
    .filter((g) => g.values.length > 1 && variants.every((v) => text(v.attributes[g.key]) !== null))
    .sort((a, b) => rank(a.key) - rank(b.key) || a.key.localeCompare(b.key));
  const distinct = new Set(variants.map((v) => groups.map((g) => optionValue(v, g.key)).join("\u0000")));
  if (groups.length && distinct.size === variants.length) return groups;
  return [{ key: VARIANT_GROUP, values: variants.map((v) => v.name) }];
}

/** The variant chosen by picking `value` in `key` while `current` is selected: the one that keeps
 * the other choices, else the first with that value in stock, else the first with that value. */
export function pickVariant(
  variants: readonly CatalogVariant[],
  groups: readonly OptionGroup[],
  current: CatalogVariant,
  key: string,
  value: string,
): CatalogVariant | null {
  const candidates = variants.filter((v) => optionValue(v, key) === value);
  const keeps = (v: CatalogVariant) =>
    groups.every((g) => g.key === key || optionValue(v, g.key) === optionValue(current, g.key));
  return candidates.find(keeps) ?? candidates.find((v) => v.in_stock) ?? candidates[0] ?? null;
}

/** The variant shown first: the cheapest in stock, else the cheapest. */
export function initialVariant(variants: readonly CatalogVariant[]): CatalogVariant | null {
  const byPrice = [...variants].sort((a, b) => a.price - b.price);
  return byPrice.find((v) => v.in_stock) ?? byPrice[0] ?? null;
}
