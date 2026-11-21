import { ArrowRight, Building2, ChevronDown, ChevronRight, CreditCard, RotateCcw, ShieldCheck, Truck } from "lucide-react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense, type ReactNode } from "react";
import { ProductCard } from "@/components/store/product-card";
import { RatingStars } from "@/components/store/rating-stars";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import {
  MobileBuyBar,
  MobileWishlist,
  ProductGallery,
  ProductProvider,
  PurchasePanel,
  VariantSku,
} from "@/features/product/product-view";
import { WhatsAppFab, WhatsAppLink } from "@/features/contact/whatsapp-link";
import { ReviewList } from "@/features/product/review-list";
import { getPathname, Link } from "@/i18n/navigation";
import { getCategories, getDeliveryInfo, getProduct, getProductReviews, getProducts } from "@/lib/api/catalogue";
import type { components } from "@/lib/api/schema";
import { categoryTrail, REVIEW_PAGE_SIZE } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { primaryImage } from "@/lib/images";

type Props = PageProps<"/[locale]/product/[slug]">;
type Product = components["schemas"]["CatalogProductDetail"];

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const product = await getProduct(slug).catch(() => undefined);
  if (product === null) notFound();
  if (!product) return {};
  const image = primaryImage(product.images);
  return {
    title: product.brand && !product.name.startsWith(product.brand.name) ? `${product.brand.name} ${product.name}` : product.name,
    description: product.description?.slice(0, 160) ?? undefined,
    openGraph: image ? { images: [{ url: image.url, width: image.width ?? undefined, height: image.height ?? undefined }] } : undefined,
  };
}

/** /product/[slug]: Product.dc.html (desktop) and MobileProduct.dc.html (phone). */
export default function ProductPage({ params }: Props) {
  return (
    <main id="main">
      <Suspense fallback={<ProductFallback />}>
        <ProductContent params={params} />
      </Suspense>
    </main>
  );
}

async function ProductContent({ params }: Pick<Props, "params">) {
  const { slug } = await params;
  const t = await getTranslations("store.productPage");
  let product: Product | null;
  try {
    product = await getProduct(slug);
  } catch {
    return (
      <div className="wrap py-8">
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("error")}
        </p>
      </div>
    );
  }
  if (!product) notFound();
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const locale = await getLocale();
  const path = (href: string) => getPathname({ href, locale });
  // Main category, then subcategory (category hierarchy, 2026-11-16), from the menu's tree.
  const trail = categoryTrail(await getCategories().catch(() => []), product.category.slug) ?? [product.category];
  const crumbs = [
    { label: th("home"), href: path("/") },
    ...trail.map((c) => ({ label: c.name, href: path(`/category/${c.slug}`) })),
    ...(product.brand ? [{ label: product.brand.name, href: path(`/brand/${product.brand.slug}`) }] : []),
    { label: product.name },
  ];
  const { rating } = product;

  return (
    <ProductProvider product={product}>
      <div className="wrap pt-5 max-sm:hidden">
        <Breadcrumb label={tu("breadcrumb")} items={crumbs} />
      </div>
      <section className="wrap flex flex-wrap items-start gap-10 pt-0 pb-8 sm:pt-6 sm:pb-12 max-sm:gap-4">
        {/* The photos, with the specifications under them on larger screens (owner, 2026-11-18:
            no empty space under the gallery, and no tabs repeating what is beside it). */}
        <div className="flex max-w-[600px] min-w-0 flex-[1_1_420px] flex-col gap-8 max-sm:max-w-none">
          <ProductGallery />
          <section aria-labelledby="specs-title" className="flex flex-col gap-4 max-sm:hidden">
            <h2 id="specs-title" className="t-h3">
              {t("specifications")}
            </h2>
            <Specs product={product} />
          </section>
        </div>
        <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-5 max-sm:gap-3.5">
          <div className="flex items-center justify-between gap-3">
            {product.brand ? (
              <Link href={`/brand/${product.brand.slug}`} className="t-over text-pri-h">
                {product.brand.name}
              </Link>
            ) : (
              <span />
            )}
            <span className="sm:hidden">
              <MobileWishlist />
            </span>
          </div>
          <h1 className="t-h1 max-sm:text-[22px] max-sm:leading-7">{product.name}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {rating.count > 0 ? (
              <>
                <RatingStars rating={rating} size={16} />
                <span className="text-mut" aria-hidden="true">
                  ·
                </span>
                <a href="#reviews" className="font-medium">
                  {t("reviews", { count: rating.count })}
                </a>
              </>
            ) : (
              <a href="#reviews" className="font-medium">
                {t("noReviews")}
              </a>
            )}
            <span className="text-mut max-sm:hidden" aria-hidden="true">
              ·
            </span>
            <span className="max-sm:hidden">
              <VariantSku />
            </span>
          </div>
          <PurchasePanel description={product.description} />
          <WhatsAppLink label={t("askWhatsapp")} message={t("whatsappMessage", { name: product.name })} className="self-start max-sm:hidden" />
          <Suspense fallback={<Skeleton className="h-[240px] rounded-xl" />}>
            <InfoCard warranty={product.warranty_text} />
          </Suspense>
          <WhatsAppLink label={t("askWhatsappShort")} message={t("whatsappMessage", { name: product.name })} block className="sm:hidden" />
          <Link href="/contact" className="flex items-center gap-2.5 rounded-xl bg-light px-4 py-3 text-navy hover:text-navy max-sm:hidden">
            <Building2 size={18} aria-hidden="true" className="text-pri" />
            <span className="flex-1 text-sm font-medium">{t("businessQuote")}</span>
            <ArrowRight size={16} aria-hidden="true" className="text-pri" />
          </Link>
        </div>
      </section>

      {/* Phones: the description is not beside the price, so it is here with the specifications. */}
      <section className="wrap pb-10 sm:hidden">
        <div className="flex flex-col border-t border-bd">
          <Accordion title={t("specifications")} open>
            <Specs product={product} />
          </Accordion>
          <Accordion title={t("description")}>
            <Description product={product} />
          </Accordion>
          <a href="#reviews" className="flex items-center justify-between border-b border-bd py-3.5 font-semibold text-tx">
            {t("reviewsTab", { count: rating.count })}
            <ChevronRight size={18} className="text-mut" aria-hidden="true" />
          </a>
        </div>
      </section>

      <Reviews product={product} />

      <Suspense fallback={null}>
        <Related product={product} />
      </Suspense>
      <MobileBuyBar />
      <WhatsAppFab className="max-sm:hidden" />
    </ProductProvider>
  );
}

function Accordion({ title, open = false, children }: { title: string; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group border-b border-bd">
      <summary className="flex cursor-pointer list-none items-center justify-between py-3.5 font-semibold [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown size={18} className="text-mut transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="pb-3">{children}</div>
    </details>
  );
}

function specText(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    const parts = value.map(specText).filter((v): v is string => v !== null);
    return parts.length ? parts.join(", ") : null;
  }
  return null;
}

async function Specs({ product }: { product: Product }) {
  const t = await getTranslations("store.productPage");
  const rows = Object.entries(product.specifications)
    .map(([key, value]) => [key, specText(value)] as const)
    .filter((row): row is readonly [string, string] => row[1] !== null);
  if (!rows.length) return <p className="text-tx2">{t("noSpecs")}</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-bd max-sm:rounded-none max-sm:border-0">
      <table className="w-full border-collapse text-sm">
        <tbody>
          {rows.map(([key, value]) => (
            <tr key={key} className="border-b border-bd last:border-b-0">
              <th scope="row" className="w-[240px] bg-page px-4 py-3 text-left align-top text-[13px] font-medium text-tx2 max-sm:w-[40%] max-sm:bg-transparent max-sm:px-0 max-sm:py-2">
                {key}
              </th>
              <td className="px-4 py-3 max-sm:px-0 max-sm:py-2">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

async function Description({ product }: { product: Product }) {
  const t = await getTranslations("store.productPage");
  return <p className="max-w-[760px] whitespace-pre-line text-tx2">{product.description || t("noDescription")}</p>;
}

/** Delivery, warranty, payment and returns (Product.dc.html's info card). Delivery fees and the
 * free-delivery threshold come from GET /delivery/zones; the exact fee is quoted at checkout. */
async function InfoCard({ warranty }: { warranty: string | null }) {
  const t = await getTranslations("store.productPage");
  const delivery = await getDeliveryInfo().catch(() => null);
  const zones = delivery?.items ?? [];
  const fees = zones.map((z) => z.fee);
  const names = zones.map((z) => z.name).join(", ");
  const rows: { icon: ReactNode; title: string; text?: string; link?: { href: string; label: string } }[] = [];
  if (zones.length) {
    const min = Math.min(...fees);
    const max = Math.max(...fees);
    const threshold = delivery?.free_delivery_threshold;
    rows.push({
      icon: <Truck size={22} />,
      title: threshold !== null && threshold !== undefined ? t("deliveryFree", { amount: formatMoney(threshold) }) : t("deliveryTitle", { zones: names }),
      text:
        min === max
          ? t("deliveryFee", { zones: names, fee: formatMoney(min) })
          : t("deliveryFees", { zones: names, min: formatMoney(min), max: formatMoney(max) }),
      link: { href: "/pages/delivery-information", label: t("deliveryInfo") },
    });
  }
  rows.push(
    {
      icon: <ShieldCheck size={22} />,
      title: warranty || t("warrantyTitle"),
      text: t("warrantyText"),
      link: { href: "/pages/warranty", label: t("warrantyLink") },
    },
    { icon: <CreditCard size={22} />, title: t("payTitle"), text: t("payText") },
    {
      icon: <RotateCcw size={22} />,
      title: t("returnsTitle"),
      text: t("returnsText"),
      link: { href: "/pages/returns-and-refunds", label: t("returnsLink") },
    },
  );
  return (
    <ul className="m-0 list-none overflow-hidden rounded-xl border border-bd bg-white p-0">
      {rows.map((row) => (
        <li key={row.title} className="flex items-start gap-3 border-b border-bd px-4 py-3.5 last:border-b-0 max-sm:gap-2.5 max-sm:px-3.5 max-sm:py-3">
          <span className="text-pri" aria-hidden="true">
            {row.icon}
          </span>
          <span className="flex flex-1 flex-col gap-0.5">
            <b className="text-sm font-medium">{row.title}</b>
            {row.text && <span className="text-cap text-tx2">{row.text}</span>}
          </span>
          {row.link && (
            <Link href={row.link.href} className="text-cap font-semibold whitespace-nowrap max-sm:hidden">
              {row.link.label}
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}

async function Reviews({ product }: { product: Product }) {
  const t = await getTranslations("store.productPage");
  const { rating } = product;
  const first = rating.count ? await getProductReviews(product.slug, 1, REVIEW_PAGE_SIZE).catch(() => null) : null;
  return (
    <section id="reviews" aria-labelledby="reviews-title" className="wrap flex scroll-mt-4 flex-wrap items-start gap-10 pb-12 max-sm:gap-5">
      <div className={cx("flex flex-col gap-3.5 rounded-xl bg-page p-6", rating.count > 0 ? "max-w-[340px] flex-[1_1_280px] max-sm:max-w-none" : "w-full")}>
        <h2 id="reviews-title" className="t-h3">
          {t("reviewsTitle")}
        </h2>
        {rating.count > 0 && rating.average !== null ? (
          <>
            <div className="flex items-center gap-3">
              <span className="t-price-l">{rating.average.toFixed(1)}</span>
              <span className="flex flex-col gap-0.5">
                <RatingStars rating={rating} size={18} showText={false} />
                <span className="text-cap text-tx2">{t("basedOn", { count: rating.count })}</span>
              </span>
            </div>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {rating.distribution.map((bucket) => (
                <li key={bucket.stars} className="flex items-center gap-2.5 text-[13px] text-tx2">
                  <span className="sr-only">{t("barLabel", { stars: bucket.stars, count: bucket.count })}</span>
                  <span className="w-7" aria-hidden="true">
                    {t("bar", { stars: bucket.stars })}
                  </span>
                  <span className="h-2 flex-1 overflow-hidden rounded-full bg-bd" aria-hidden="true">
                    <span className="block h-full rounded-full bg-star" style={{ width: `${Math.round((bucket.count / rating.count) * 100)}%` }} />
                  </span>
                  <span className="w-[18px] text-right" aria-hidden="true">
                    {bucket.count}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-tx2">{t("noReviewsText")}</p>
        )}
        <p className="text-cap text-tx2">{t("reviewsNote")}</p>
      </div>
      {rating.count > 0 &&
        (first ? (
          <ReviewList slug={product.slug} first={first} />
        ) : (
          <p role="alert" className="flex-[999_1_520px] rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
            {t("reviewsError")}
          </p>
        ))}
    </section>
  );
}

/** "You may also like": the category's bestsellers, without this product. */
async function Related({ product }: { product: Product }) {
  const t = await getTranslations("store.productPage");
  const page = await getProducts({ category: product.category.slug, sort_by: "bestselling", sort_direction: "desc", size: 6 }).catch(
    () => null,
  );
  const items = (page?.items ?? []).filter((p) => p.id !== product.id).slice(0, 5);
  if (!items.length) return null;
  return (
    <section aria-labelledby="related-title" className="bg-page py-8 sm:py-14">
      <div className="wrap flex flex-col gap-4 sm:gap-6">
        <div className="flex items-center justify-between gap-3">
          <h2 id="related-title" className="t-h2 max-sm:text-lg">
            {t("related")}
          </h2>
          <Link href={`/category/${product.category.slug}`} className="flex items-center gap-1.5 text-sm font-medium">
            {t("viewAll", { category: product.category.name.toLowerCase() })}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-3 sm:gap-5 lg:grid-cols-5">
          {items.map((item, i) => (
            <li key={item.id} className={cx(i >= 2 && "hidden sm:block", i >= 3 && "sm:hidden lg:block")}>
              <ProductCard product={item} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function ProductFallback() {
  return (
    <div className="wrap flex flex-wrap gap-10 py-6">
      <Skeleton className="h-[340px] max-w-[600px] flex-[1_1_420px] rounded-2xl sm:h-[480px]" />
      <div className="flex flex-[1_1_420px] flex-col gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-3/4" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-11 w-full" />
      </div>
    </div>
  );
}
