"use client";

import { useId, useState, type ReactNode } from "react";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { useHoverMenu } from "./use-hover-menu";

/** A category-nav item that opens a panel below it: the trigger looks like the row's links
 * (label, then a caret that turns while open) and the panel fades and slides in. The panel's
 * content is drawn only once the menu has first opened, so its images load on demand rather than
 * on every page view. With `href` the label is a link (a category's page) and hovering opens the
 * panel; the caret is then its own button, for keyboard and touch. */
export function NavDropdown({
  icon,
  label,
  href,
  toggleLabel,
  active = false,
  width,
  panelLabel,
  variant = "bar",
  className,
  children,
}: {
  icon?: ReactNode;
  label: string;
  /** The label links here; the caret alone opens the panel on click or tap. */
  href?: string;
  /** With `href`: the caret button's accessible name. */
  toggleLabel?: string;
  className?: string;
  /** The current page belongs to this menu (e.g. a brand page under Brands). */
  active?: boolean;
  /** The panel's width in px; narrower windows get the window less its gutters. */
  width: number;
  /** The panel's accessible name. */
  panelLabel: string;
  /** "box": a white box on the blue bar with a blue icon, label and caret, as wide as the mega
   * menu's category column (All Categories; design/screens/mega menu.png). "bar": white like the
   * bar's links (Brands). */
  variant?: "box" | "bar";
  children: (close: () => void) => ReactNode;
}) {
  const menu = useHoverMenu({ width });
  const panelId = useId();
  const [drawn, setDrawn] = useState(false);
  if (menu.open && !drawn) setDrawn(true);
  const lit = menu.open || active;
  return (
    <div {...menu.rootProps} className={cx("flex h-12 flex-none items-center", variant === "box" && "mr-3", className)}>
      {href ? (
        <span className={cx("flex h-9 items-center rounded-md transition-colors duration-150 motion-reduce:transition-none", lit ? "bg-nav-h" : "hover:bg-nav-h")}>
          <Link
            href={href}
            aria-current={active ? "page" : undefined}
            className="flex h-9 items-center rounded-l-md pr-1 pl-2.5 text-sm font-medium whitespace-nowrap text-white hover:text-white focus-visible:outline-white xl:pl-3"
          >
            {label}
          </Link>
          <button
            type="button"
            {...menu.triggerProps}
            aria-expanded={menu.open}
            aria-controls={panelId}
            aria-label={toggleLabel}
            className="flex h-9 cursor-pointer items-center rounded-r-md border-0 bg-transparent pr-2.5 pl-1 text-white focus-visible:outline-white xl:pr-3"
          >
            <Caret open={menu.open} size={8} />
          </button>
        </span>
      ) : variant === "box" ? (
        <button
          type="button"
          {...menu.triggerProps}
          aria-expanded={menu.open}
          aria-controls={panelId}
          className={cx(
            "flex h-10 w-48 cursor-pointer items-center gap-3 rounded-md border-0 px-4 xl:w-64 text-base font-semibold whitespace-nowrap shadow-sh transition-colors duration-150 hover:bg-light hover:text-pri-h focus-visible:outline-white motion-reduce:transition-none",
            lit ? "bg-light text-pri-h" : "bg-card text-pri-fg",
          )}
        >
          {icon && (
            <span aria-hidden="true" className="flex">
              {icon}
            </span>
          )}
          <span className="flex-1 text-center">{label}</span>
          <Caret open={menu.open} size={10} />
        </button>
      ) : (
        <button
          type="button"
          {...menu.triggerProps}
          aria-expanded={menu.open}
          aria-controls={panelId}
          className={cx(
            "flex h-9 cursor-pointer items-center gap-1.5 rounded-md border-0 px-3 py-0 text-sm font-medium whitespace-nowrap text-white transition-colors duration-150 focus-visible:outline-white motion-reduce:transition-none",
            lit ? "bg-nav-h" : "bg-transparent hover:bg-nav-h",
          )}
        >
          {icon && (
            <span aria-hidden="true" className="flex">
              {icon}
            </span>
          )}
          {label}
          <Caret open={menu.open} size={8} />
        </button>
      )}
      <div
        id={panelId}
        role="region"
        aria-label={panelLabel}
        // Closed: invisible (so it takes no clicks, focus or screen-reader attention) but still
        // laid out, so it can fade out.
        style={menu.position ? { top: menu.position.top, left: menu.position.left, width: menu.position.width } : undefined}
        className={cx(
          "fixed z-50 overflow-hidden rounded-b-xl border border-t-0 border-bd bg-card shadow-sh2",
          "transition-[opacity,translate,visibility] duration-150 ease-out motion-reduce:transition-none",
          menu.open && menu.position ? "visible translate-y-0 opacity-100" : "invisible -translate-y-1 opacity-0",
        )}
      >
        {drawn && children(menu.close)}
      </div>
    </div>
  );
}

/** The solid down-pointing caret of the design (design/screens/mega menu.png); it turns over
 * while the menu is open. */
function Caret({ open, size }: { open: boolean; size: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={Math.round(size * 0.6)}
      viewBox="0 0 10 6"
      fill="currentColor"
      className={cx("flex-none transition-transform duration-200 motion-reduce:transition-none", open && "rotate-180")}
    >
      <path d="M0 0h10L5 6z" />
    </svg>
  );
}
