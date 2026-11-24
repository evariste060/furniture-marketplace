/** The shopper's recent searches (SC-07), kept in this browser only (localStorage): newest
 * first, at most RECENT_MAX, a repeat moves to the top (compared without case or extra spaces).
 * Storage that is blocked or holds something unexpected reads as an empty list. */
export const RECENT_KEY = "furnihub-recent-searches";
export const RECENT_MAX = 6;
/** The header's search box accepts up to 160 characters. */
const TERM_MAX = 160;

const tidy = (term: string) => term.trim().replace(/\s+/g, " ").slice(0, TERM_MAX);
const same = (a: string, b: string) => a.toLocaleLowerCase() === b.toLocaleLowerCase();

export function readRecent(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((v): v is string => typeof v === "string" && tidy(v) !== "").slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}

function write(list: string[]): string[] {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    // Storage blocked (private mode): the list is not kept.
  }
  return list;
}

/** Adds a search to the top; returns the new list. */
export function addRecent(term: string): string[] {
  const t = tidy(term);
  if (!t) return readRecent();
  return write([t, ...readRecent().filter((r) => !same(r, t))].slice(0, RECENT_MAX));
}

export function removeRecent(term: string): string[] {
  return write(readRecent().filter((r) => !same(r, term)));
}

export function clearRecent(): string[] {
  return write([]);
}
