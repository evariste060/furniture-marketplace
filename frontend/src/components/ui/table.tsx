import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

/** .tbl inside a horizontally scrolling wrapper (.scrollx). The wrapper takes keyboard focus so a
 * table wider than a phone can be scrolled with the arrow keys even when it has no links. It is
 * `relative` so screen-reader-only text in the cells (absolutely positioned) is clipped with the
 * table instead of widening the whole page on phones. */
export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    // eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex -- a scrollable region must be focusable (WCAG 2.1.1)
    <div tabIndex={0} className="relative overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-pri">
      <table className={cx("w-full border-collapse text-sm", className)} {...props} />
    </div>
  );
}

export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cx(
        // WCAG AA: --mut on --page is 4.47:1, so headers use --tx2.
        "border-b border-bd bg-page px-4 py-3 text-left text-cap font-semibold whitespace-nowrap text-tx2",
        className,
      )}
      {...props}
    />
  );
}

export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cx("border-b border-bd px-4 py-3.5 align-middle text-tx [tr:last-child_&]:border-b-0", className)}
      {...props}
    />
  );
}
