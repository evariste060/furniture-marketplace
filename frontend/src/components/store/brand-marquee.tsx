import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import type { CatalogBrand } from "@/lib/catalogue";
import { cx } from "@/lib/cx";

/** A brand shown in the marquee: one with a logo uploaded in the admin. */
export type MarqueeBrand = Pick<CatalogBrand, "id" | "name" | "slug"> & { logo: NonNullable<CatalogBrand["logo"]> };

/** Each half of the track holds at least this many cards (the logos repeated when there are
 * few), so it is wider than the widest screen and the loop never shows a gap. */
export const MARQUEE_MIN_CARDS = 12;
/** Seconds each card takes to pass, so the speed stays the same however many brands there are. */
const SECONDS_PER_CARD = 3;

/** The brands with a logo, in their order (GET /catalog/brands lists the active brands by name).
 * Brands without a logo are left out: the marquee shows real logos only. */
export function marqueeBrands(brands: CatalogBrand[]): MarqueeBrand[] {
  return brands.flatMap(({ id, name, slug, logo }) => (logo ? [{ id, name, slug, logo }] : []));
}

/** One half of the track: the brands, repeated until there are MARQUEE_MIN_CARDS of them. */
export function marqueeHalf<T>(brands: T[]): T[] {
  if (!brands.length) return [];
  const copies = Math.max(1, Math.ceil(MARQUEE_MIN_CARDS / brands.length));
  return Array.from({ length: copies }, () => brands).flat();
}

/** Trusted Brands' moving row (owner, 2026-11-17): the brands' logos on white cards, sliding from
 * right to left in an endless loop. The track holds the same half twice and moves left by one half
 * (the marquee keyframes in globals.css), so the end joins the start without a seam; the cards are
 * spaced with padding rather than a flex gap, so both halves are exactly the same width. The
 * motion pauses while the pointer or keyboard focus is on it. Only the first half is read out
 * and reachable by Tab; the rest is a visual copy. With reduced motion nothing moves: the first
 * half is a row that scrolls sideways. Each card links to the brand's page. */
export function BrandMarquee({ brands, label }: { brands: MarqueeBrand[]; label: string }) {
  const half = marqueeHalf(brands);
  const card = (brand: MarqueeBrand, key: string, copy: boolean) => (
    <li key={key} aria-hidden={copy || undefined} className={cx("flex-none pr-3 sm:pr-4", copy && "motion-reduce:hidden")}>
      <Link
        href={`/brand/${brand.slug}`}
        tabIndex={copy ? -1 : undefined}
        className="flex h-20 w-36 items-center justify-center rounded-xl border border-bd bg-white p-4 shadow-sh transition-[border-color,box-shadow] duration-200 hover:border-pri hover:shadow-sh2 sm:h-24 sm:w-44 lg:w-48"
      >
        <ProductImage image={brand.logo} alt={brand.name} sizes="(max-width: 700px) 120px, 160px" className="size-full rounded-none bg-white" />
      </Link>
    </li>
  );
  return (
    <div
      className={cx(
        "overflow-hidden py-2 motion-reduce:overflow-x-auto",
        // The row fades out at both edges.
        "[mask-image:linear-gradient(to_right,transparent,black_6%,black_94%,transparent)]",
      )}
    >
      <div
        className="flex w-max animate-marquee hover:[animation-play-state:paused] focus-within:[animation-play-state:paused] motion-reduce:animate-none"
        style={{ animationDuration: `${half.length * SECONDS_PER_CARD}s` }}
      >
        <ul aria-label={label} className="m-0 flex list-none p-0">
          {half.map((brand, i) => card(brand, `${brand.id}-${i}`, i >= brands.length))}
        </ul>
        <ul aria-hidden="true" className="m-0 flex list-none p-0 motion-reduce:hidden">
          {half.map((brand, i) => card(brand, `${brand.id}-copy-${i}`, true))}
        </ul>
      </div>
    </div>
  );
}

/** The count under the row: the exact number below 20, otherwise rounded down to tens with a
 * "+" ("40+ brands available"), from the same brand list. */
export function brandCountLabel(total: number): { count: number; over: boolean } {
  return total < 20 ? { count: total, over: false } : { count: Math.floor(total / 10) * 10, over: true };
}
