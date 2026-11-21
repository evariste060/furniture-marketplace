/** The product editor's category pickers (category hierarchy, 2026-11-16): a main category, then
 * one of its subcategories (optional), from the staff category list. A product stores only its
 * category; the main category is that category's root, so the two can never disagree.
 *
 * Only visible categories and brands are offered for a new choice (the backend refuses hidden
 * ones). A product's current category or brand stays listed even when it was hidden later,
 * marked `hidden`, so editing other fields keeps it. */

export type CategoryNode = { id: string; name: string; parent_id: string | null; is_active: boolean; sort_order: number };
export type Option = { id: string; name: string; hidden: boolean };

function byId(all: readonly CategoryNode[]): Map<string, CategoryNode> {
  return new Map(all.map((c) => [c.id, c]));
}

function ordered<T extends Pick<CategoryNode, "sort_order" | "name">>(items: T[]): T[] {
  return items.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
}

/** The main category of a category (itself for a main one); undefined for an unknown id. */
export function rootOf(all: readonly CategoryNode[], id: string): CategoryNode | undefined {
  const nodes = byId(all);
  let node = nodes.get(id);
  const seen = new Set<string>();
  while (node?.parent_id && nodes.has(node.parent_id) && !seen.has(node.id)) {
    seen.add(node.id);
    node = nodes.get(node.parent_id);
  }
  return node;
}

/** Hidden: the category or one of its ancestors is inactive (the store hides the subtree). */
export function isHidden(all: readonly CategoryNode[], id: string): boolean {
  const nodes = byId(all);
  const seen = new Set<string>();
  for (let node = nodes.get(id); node && !seen.has(node.id); node = node.parent_id ? nodes.get(node.parent_id) : undefined) {
    if (!node.is_active) return true;
    seen.add(node.id);
  }
  return false;
}

/** Main categories to choose from: the visible ones, plus the current one if it is hidden. */
export function mainOptions(all: readonly CategoryNode[], currentId: string): Option[] {
  const current = currentId ? rootOf(all, currentId)?.id : undefined;
  return ordered(all.filter((c) => c.parent_id === null && (c.is_active || c.id === current))).map((c) => ({
    id: c.id,
    name: c.name,
    hidden: !c.is_active,
  }));
}

/** Subcategories of a main category: the visible ones, plus the current one if it is hidden or
 * deeper (a tree from before the two-level cap). */
export function subOptions(all: readonly CategoryNode[], mainId: string, currentId: string): Option[] {
  if (!mainId) return [];
  const children = all.filter((c) => c.parent_id === mainId && (!isHidden(all, c.id) || c.id === currentId));
  const current = all.find((c) => c.id === currentId);
  if (current && current.id !== mainId && rootOf(all, current.id)?.id === mainId && !children.includes(current)) children.push(current);
  return ordered(children).map((c) => ({ id: c.id, name: c.name, hidden: isHidden(all, c.id) }));
}

/** The picker values for a stored category: its main category and its subcategory ("" if none). */
export function splitCategory(all: readonly CategoryNode[], categoryId: string): { mainId: string; subId: string } {
  const root = categoryId ? rootOf(all, categoryId) : undefined;
  if (!root) return { mainId: "", subId: "" };
  return { mainId: root.id, subId: root.id === categoryId ? "" : categoryId };
}

/** Brands to choose from: the active ones, plus the current one if it is hidden, by name. */
/** The brand options split for a main category (ADR-012 decision 9, a suggestion only): the
 * brands that belong to it, then the others. Without a main category every option is "other". */
export function groupBrandOptions(options: readonly Option[], brands: readonly { id: string; category_ids?: string[] }[], mainId: string): { own: Option[]; other: Option[] } {
  const of = new Map(brands.map((b) => [b.id, b.category_ids ?? []]));
  const own = mainId ? options.filter((o) => of.get(o.id)?.includes(mainId)) : [];
  return { own, other: options.filter((o) => !own.includes(o)) };
}

export function brandOptions(brands: readonly { id: string; name: string; is_active: boolean }[], currentId: string): Option[] {
  return brands
    .filter((b) => b.is_active || b.id === currentId)
    .map((b) => ({ id: b.id, name: b.name, hidden: !b.is_active }))
    .sort((a, b) => a.name.localeCompare(b.name));
}
