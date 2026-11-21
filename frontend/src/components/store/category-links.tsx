"use client";

import { useTranslations } from "next-intl";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { NavLink } from "./header-actions";
import { NavDropdown } from "./nav-dropdown";

export type CategoryLinkSub = { id: string; name: string; slug: string };
export type CategoryLinkItem = { id: string; name: string; slug: string; subcategories: CategoryLinkSub[] };

/** Room kept for "More" before it has been measured. */
const MORE_ESTIMATE = 96;
/** A category's subcategory dropdown. */
const SUB_WIDTH = 260;

/** The top-level categories on the blue nav bar (laptops up; tablets reach them through All
 * Categories), as text. Hovering one opens a dropdown of its own subcategories (owner,
 * 2026-11-17); one without subcategories is a plain link. As many as fit beside the bar's other
 * items are shown; the rest go into a "More" dropdown after them, so the bar never scrolls
 * sideways however many categories there are.
 *
 * The items stay laid out at their natural widths in a row that clips, and the bar is measured:
 * the room left is the bar's width less its other items (the spacer and "More" aside). Items past
 * the room are made invisible, which changes no widths, so measuring cannot loop. */
export function CategoryLinks({ items }: { items: CategoryLinkItem[] }) {
  const t = useTranslations("store.header");
  const pathname = usePathname();
  const row = useRef<HTMLDivElement>(null);
  const more = useRef<HTMLDivElement>(null);
  const moreWidth = useRef(MORE_ESTIMATE);
  const [fit, setFit] = useState(items.length);
  const [width, setWidth] = useState<number | null>(null);

  const measure = useCallback(() => {
    const el = row.current;
    const bar = el?.parentElement;
    if (!el || !bar) return;
    if (more.current?.offsetWidth) moreWidth.current = more.current.offsetWidth;
    const style = getComputedStyle(bar);
    let room = bar.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    for (const item of bar.children) {
      if (item === el || item === more.current || item.hasAttribute("data-nav-spacer")) continue;
      const s = getComputedStyle(item);
      room -= (item as HTMLElement).offsetWidth + parseFloat(s.marginLeft) + parseFloat(s.marginRight);
    }
    const widths = [...el.children].map((c) => (c as HTMLElement).offsetWidth);
    const total = widths.reduce((a, b) => a + b, 0);
    if (total <= room) {
      setFit(widths.length);
      setWidth(null);
      return;
    }
    room -= moreWidth.current;
    let n = 0;
    let used = 0;
    while (n < widths.length && used + widths[n] <= room) used += widths[n++];
    setFit(n);
    setWidth(used);
  }, []);

  useLayoutEffect(() => {
    const bar = row.current?.parentElement;
    if (!bar) return;
    measure();
    // The bar (window resizes) and each item (fonts loading, the language switching).
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    for (const link of row.current?.children ?? []) observer.observe(link, { box: "border-box" });
    void document.fonts?.ready.then(measure);
    return () => observer.disconnect();
  }, [measure, items.length]);

  const hidden = items.slice(fit);
  const overflowing = hidden.length > 0;
  // Once "More" is shown, measure again with its real width.
  useLayoutEffect(() => {
    if (overflowing) measure();
  }, [overflowing, measure]);
  const at = (slug: string) => pathname === `/category/${slug}` || pathname.startsWith(`/category/${slug}/`);
  // A category is current on its own page and on its subcategories' pages.
  const here = (c: CategoryLinkItem) => at(c.slug) || c.subcategories.some((s) => at(s.slug));
  return (
    <>
      <div ref={row} className="hidden min-w-0 flex-[0_1_auto] items-center overflow-hidden lg:flex" style={width === null ? undefined : { width }}>
        {items.map((c, i) =>
          c.subcategories.length ? (
            <NavDropdown
              key={c.id}
              label={c.name}
              href={`/category/${c.slug}`}
              toggleLabel={t("subcategoriesOf", { name: c.name })}
              active={here(c)}
              width={SUB_WIDTH}
              panelLabel={t("subcategoriesOf", { name: c.name })}
              className={i >= fit ? "invisible" : undefined}
            >
              {(close) => <SubcategoryList items={c.subcategories} at={at} onPick={close} />}
            </NavDropdown>
          ) : (
            <NavLink key={c.id} href={`/category/${c.slug}`} className={i >= fit ? "invisible" : undefined}>
              {c.name}
            </NavLink>
          ),
        )}
      </div>
      {hidden.length > 0 && (
        <div ref={more} className="hidden flex-none lg:flex">
          <NavDropdown label={t("more")} active={hidden.some(here)} width={280} panelLabel={t("moreCategories")} variant="bar">
            {(close) => (
              <ul className="m-0 flex max-h-[70vh] list-none flex-col gap-0.5 overflow-y-auto p-2">
                {hidden.map((c) => (
                  <li key={c.id}>
                    <Link
                      href={`/category/${c.slug}`}
                      aria-current={at(c.slug) ? "page" : undefined}
                      onClick={close}
                      className={cx(
                        "flex items-center rounded-md px-3 py-2 text-sm font-semibold transition-colors duration-150 motion-reduce:transition-none",
                        at(c.slug) ? "bg-light text-pri-h" : "text-tx hover:bg-page hover:text-pri",
                      )}
                    >
                      {c.name}
                    </Link>
                    {c.subcategories.length > 0 && <SubcategoryList items={c.subcategories} at={at} onPick={close} nested />}
                  </li>
                ))}
              </ul>
            )}
          </NavDropdown>
        </div>
      )}
    </>
  );
}

/** A category's subcategories, as links to their pages. */
function SubcategoryList({ items, at, onPick, nested = false }: { items: CategoryLinkSub[]; at: (slug: string) => boolean; onPick: () => void; nested?: boolean }) {
  return (
    <ul className={cx("m-0 flex list-none flex-col gap-0.5", nested ? "pb-1 pl-3" : "max-h-[70vh] overflow-y-auto p-2")}>
      {items.map((s) => (
        <li key={s.id}>
          <Link
            href={`/category/${s.slug}`}
            aria-current={at(s.slug) ? "page" : undefined}
            onClick={onPick}
            className={cx(
              "flex items-center rounded-md px-3 py-2 text-sm transition-colors duration-150 motion-reduce:transition-none",
              at(s.slug) ? "bg-light font-medium text-pri-h" : "text-tx hover:bg-page hover:text-pri",
            )}
          >
            {s.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}
