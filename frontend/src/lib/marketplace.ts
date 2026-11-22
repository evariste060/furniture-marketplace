/** The marketplace's name (ADR-014 decision 16). FurniHub is provisional: a rename is the
 * NEXT_PUBLIC_MARKETPLACE_NAME setting (and the backend's MARKETPLACE_NAME), never a change to
 * components or messages. */
export const MARKETPLACE_NAME = process.env.NEXT_PUBLIC_MARKETPLACE_NAME?.trim() || "FurniHub";

const TOKEN = "{marketplace}";

/** Messages write the name as {marketplace}; it is filled in once, when they are loaded
 * (i18n/request.ts), so every t() call sees plain text. An apostrophe in the name is escaped
 * for ICU. */
export function withMarketplace<T>(messages: T, name: string = MARKETPLACE_NAME): T {
  const text = name.replaceAll("'", "''");
  const walk = (value: unknown): unknown => {
    if (typeof value === "string") return value.replaceAll(TOKEN, text);
    if (Array.isArray(value)) return value.map(walk);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, walk(v)]));
    return value;
  };
  return walk(messages) as T;
}
