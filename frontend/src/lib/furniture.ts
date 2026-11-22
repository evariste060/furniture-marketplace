/** Furniture attributes (ADR-014 decision 14, phase 6). The backend owns them
 * (backend/app/core/furniture.py, served by GET /catalog/attributes); these lists mirror the
 * codes the storefront needs before any request: the listing filters read from the URL. A test
 * checks every code has an English and a Kinyarwanda label (messages "furniture"). */

export const FILTER_KEYS = ["material", "color", "style"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export const CHOICES = {
  material: ["solid_wood", "engineered_wood", "bamboo", "rattan", "metal", "glass", "marble", "stone", "fabric", "leather", "faux_leather", "plastic", "foam"],
  color: ["natural", "oak", "walnut", "white", "black", "grey", "beige", "brown", "blue", "green", "red", "yellow", "multicolour"],
  style: ["modern", "contemporary", "classic", "rustic", "industrial", "scandinavian", "mid_century", "african"],
  finish: ["natural", "matte", "satin", "gloss", "lacquered", "painted", "polished", "upholstered"],
  condition: ["new", "refurbished", "used"],
} as const;
export type ChoiceKey = keyof typeof CHOICES;

export const NUMBER_KEYS = ["width_cm", "depth_cm", "height_cm", "seat_height_cm", "weight_kg"] as const;
export type NumberKey = (typeof NUMBER_KEYS)[number];
export const BOOLEAN_KEYS = ["assembly_required"] as const;
export type AttributeKey = ChoiceKey | NumberKey | (typeof BOOLEAN_KEYS)[number];
export const ATTRIBUTE_KEYS: readonly AttributeKey[] = [...NUMBER_KEYS, "material", "color", "style", "finish", "condition", ...BOOLEAN_KEYS];

/** The codes chosen per filter key (in the attribute's own order). */
export type AttributeFilters = Record<FilterKey, string[]>;
export const EMPTY_ATTRIBUTES: AttributeFilters = { material: [], color: [], style: [] };

export function isAttributeKey(key: string): key is AttributeKey {
  return (ATTRIBUTE_KEYS as readonly string[]).includes(key);
}

/** Known codes only (an unknown one would be a 422), deduplicated, in the attribute's order. */
export function attributeCodes(key: FilterKey, values: string[]): string[] {
  const allowed: readonly string[] = CHOICES[key];
  return allowed.filter((code) => values.includes(code));
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** A specification as the product page shows it: a known attribute gets its translated name and
 * value (with its unit); any other is shown as the seller wrote it. `t` is useTranslations("furniture"). */
export function specificationRow(key: string, value: unknown, t: Translate): { label: string; value: string } {
  if (!isAttributeKey(key)) return { label: key, value: String(value) };
  const label = t(`names.${key}`);
  if (typeof value === "boolean") return { label, value: t(value ? "yes" : "no") };
  if (typeof value === "number") return { label, value: t(key.endsWith("_kg") ? "kg" : "cm", { value }) };
  if (key in CHOICES && (CHOICES[key as ChoiceKey] as readonly string[]).includes(String(value)))
    return { label, value: t(`${key}.${value}`) };
  return { label, value: String(value) };
}
