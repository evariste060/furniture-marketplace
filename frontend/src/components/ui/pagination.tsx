import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { buttonClasses } from "./button";

/** The numbered page links under listings (Category.dc.html). Driven by the API's
 * {total, page, size}; `hrefFor` builds each page's URL. */
export function Pagination({
  total,
  page,
  size,
  hrefFor,
  labels,
}: {
  total: number;
  page: number;
  size: number;
  hrefFor: (page: number) => string;
  labels: { nav: string; previous: string; next: string; page: (n: number) => string };
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return null;
  const numbers = pageWindow(page, pages);
  return (
    <nav aria-label={labels.nav} className="flex flex-wrap items-center justify-center gap-2 pt-3">
      <PageLink href={page > 1 ? hrefFor(page - 1) : undefined} className={buttonClasses({ variant: "neutral", size: "sm" })}>
        <ChevronLeft size={14} aria-hidden="true" />
        {labels.previous}
      </PageLink>
      {numbers.map((n, i) =>
        n === null ? (
          <span key={`gap-${i}`} className="px-1 text-mut" aria-hidden="true">
            …
          </span>
        ) : (
          <Link
            key={n}
            href={hrefFor(n)}
            aria-label={labels.page(n)}
            aria-current={n === page ? "page" : undefined}
            className={buttonClasses({ variant: n === page ? "primary" : "neutral", size: "sm", square: true })}
          >
            {n}
          </Link>
        ),
      )}
      <PageLink href={page < pages ? hrefFor(page + 1) : undefined} className={buttonClasses({ variant: "neutral", size: "sm" })}>
        {labels.next}
        <ChevronRight size={14} aria-hidden="true" />
      </PageLink>
    </nav>
  );
}

function PageLink({ href, className, children }: { href?: string; className: string; children: React.ReactNode }) {
  if (!href) {
    return (
      <span aria-disabled="true" className={`${className} text-mut`}>
        {children}
      </span>
    );
  }
  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

/** Page numbers to show: first, last, and two around the current page; null marks a gap. */
export function pageWindow(page: number, pages: number): Array<number | null> {
  const wanted = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const sorted = [...wanted].sort((a, b) => a - b);
  const out: Array<number | null> = [];
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1] > 1) out.push(null);
    out.push(n);
  });
  return out;
}
