import Link from "next/link";
import { cx } from "@/lib/cx";

export type Crumb = { label: string; href?: string; lang?: string };

/** .crumb: links in secondary text (--mut on the listing hero's --light is below 4.5:1, so
 * --tx2 is used), the current page in bold. The last item is the current page. */
export function Breadcrumb({ items, label, className }: { items: Crumb[]; label: string; className?: string }) {
  return (
    <nav aria-label={label} className={className}>
      <ol className="m-0 flex list-none flex-wrap items-center gap-2 p-0 text-sm text-mut">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex items-center gap-2">
              {last || !item.href ? (
                <b lang={item.lang} className={cx("font-medium", last && "text-tx")} aria-current={last ? "page" : undefined}>
                  {item.label}
                </b>
              ) : (
                <Link href={item.href} className="text-tx2 hover:text-pri-fg">
                  {item.label}
                </Link>
              )}
              {!last && <span aria-hidden="true">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
