import { ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { buttonClasses } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { getCategories, getProduct, getProducts } from "@/lib/api/catalogue";
import {
  discountPercent,
  menuProduct,
  menuProductQuery,
  SPOTLIGHT_PRODUCTS,
  topCategories,
  type CatalogCategory,
  type CatalogProduct,
} from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import type { ApiImage } from "@/lib/images";
import { HoverProductCard, type HoverProduct } from "./hover-product-card";
import { cardData } from "./product-card";
import { SpotlightShowcase, type ShowcaseProduct } from "./spotlight-showcase";

/** The small cards beside the showcase: two rows of four from tablets up, two of two on phones. */
const PHONE_PRODUCTS = 4;

type Spotlight = { category: CatalogCategory; total: number; showcase: ShowcaseProduct; products: HoverProduct[] };

/** One spotlight per top-level category (in merchandising order) under New Arrivals: the
 * category's name and a link to its page, then a large showcase of one product (the one staff
 * chose in Admin › Categories, else the category's best seller) beside more of its best sellers
 * as hover cards. The products come from the same request as the header's mega menu and the home
 * hero (menuProductQuery), so the catalogue cache answers it. A category without products, or whose
 * products could not be loaded, is left out. */
export async function CategorySpotlights() {
  const categories = topCategories(await getCategories().catch(() => []));
  const spotlights = (await Promise.all(categories.map(loadSpotlight))).filter((s) => s !== null);
  if (!spotlights.length) return null;
  return (
    <>
      {spotlights.map((s, i) => (
        <SpotlightSection key={s.category.id} spotlight={s} tinted={i % 2 === 1} />
      ))}
    </>
  );
}

async function loadSpotlight(category: CatalogCategory): Promise<Spotlight | null> {
  const page = await getProducts(menuProductQuery(category.slug)).catch(() => null);
  if (!page?.items.length) return null;
  const slug = category.spotlight_product_slug;
  const picked = slug ? (page.items.find((p) => p.slug === slug) ?? (await getProduct(slug).catch(() => null))) : null;
  const star = picked ?? page.items[0];
  const products = page.items
    .filter((p) => p.id !== star.id)
    .slice(0, SPOTLIGHT_PRODUCTS)
    .map((product): HoverProduct => {
      const { variant, discount, cart } = cardData(product);
      return { ...menuProduct(product), cart, detail: variant?.name ?? null, rating: product.rating, discount };
    });
  return { category, total: page.total, showcase: showcaseProduct(star), products };
}

/** The showcase's data: every photo (the product's, then each variant's, without repeats) and
 * the shown variant's price. */
export function showcaseProduct(product: CatalogProduct): ShowcaseProduct {
  const { variant, discount, cart } = cardData(product);
  const seen = new Set<string>();
  const images: ApiImage[] = [];
  const byPosition = (list: readonly ApiImage[]) => [...list].sort((a, b) => a.position - b.position);
  for (const image of [...byPosition(product.images), ...product.variants.flatMap((v) => byPosition(v.images))]) {
    if (seen.has(image.url)) continue;
    seen.add(image.url);
    images.push(image);
  }
  return {
    name: product.name,
    slug: product.slug,
    images,
    price: variant?.price ?? null,
    compareAtPrice: variant && discountPercent(variant) ? (variant.compare_at_price ?? null) : null,
    discount,
    detail: product.variants.length > 1 ? (variant?.name ?? null) : null,
    rating: product.rating,
    cart,
  };
}

async function SpotlightSection({ spotlight, tinted }: { spotlight: Spotlight; tinted: boolean }) {
  const t = await getTranslations("store.home");
  const tHero = await getTranslations("hero");
  const { category, total, showcase, products } = spotlight;
  const titleId = `spotlight-${category.slug}`;
  return (
    <section aria-labelledby={titleId} className={cx("px-4 py-3 sm:px-0 sm:py-4", tinted && "sm:bg-page")}>
      <div className="flex flex-col gap-3 sm:wrap sm:gap-4">
        <div className="flex items-end justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id={titleId} className="t-h3 text-navy sm:t-h2">
              {t("spotlightTitle", { category: category.name })}
            </h2>
            <p className="line-clamp-1 text-sm text-tx2 max-sm:hidden">{category.description || t("spotlightText", { category: category.name })}</p>
          </div>
          <Link href={`/category/${category.slug}`} className={buttonClasses({ variant: "outline", size: "sm", className: "flex-none gap-1.5" })}>
            {tHero("viewAll", { count: total })}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        <div className="grid gap-3 sm:gap-4 lg:grid-cols-[minmax(0,32fr)_minmax(0,68fr)]">
          <article aria-label={showcase.name} className="overflow-hidden rounded-2xl border border-bd bg-white shadow-sh">
            <SpotlightShowcase product={showcase} />
          </article>
          {products.length > 0 && (
            <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-4 lg:grid-rows-2">
              {products.map((product, i) => (
                <li key={product.id} className={i >= PHONE_PRODUCTS ? "hidden sm:block" : undefined}>
                  <HoverProductCard product={product} size="md" />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
