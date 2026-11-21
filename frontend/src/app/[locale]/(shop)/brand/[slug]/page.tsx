import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { ListingFallback, ListingResults, ShowingCount } from "@/features/listing/listing-results";
import { getPathname } from "@/i18n/navigation";
import { getBrands } from "@/lib/api/catalogue";
import { IMAGE_SIZES } from "@/lib/images";

type Props = PageProps<"/[locale]/brand/[slug]">;

async function brand(slug: string) {
  return (await getBrands()).find((b) => b.slug === slug) ?? null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const found = await brand(slug).catch(() => null);
  return found ? { title: found.name } : {};
}

/** /brand/[slug]: the Category.dc.html listing filtered by one brand; the filter panel's first
 * group is Category instead of Brand. */
export default function BrandPage({ params, searchParams }: Props) {
  return (
    <main id="main">
      <Suspense fallback={<HeroFallback />}>
        <Hero params={params} searchParams={searchParams} />
      </Suspense>
      <Suspense fallback={<ListingFallback />}>
        <Body params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Hero({ params, searchParams }: Props) {
  const { slug } = await params;
  const found = await brand(slug);
  if (!found) notFound();
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const tb = await getTranslations("store.brands");
  const locale = await getLocale();
  return (
    <section className="overflow-hidden bg-light">
      <div className="wrap flex flex-wrap items-center justify-between gap-6 py-5 sm:py-8">
        <div className="flex max-w-[640px] flex-[1_1_420px] flex-col gap-2.5">
          <Breadcrumb
            label={tu("breadcrumb")}
            items={[
              { label: th("home"), href: getPathname({ href: "/", locale }) },
              { label: tb("title"), href: getPathname({ href: "/brands", locale }) },
              { label: found.name },
            ]}
          />
          <h1 className="t-h1 text-navy">{found.name}</h1>
          <Suspense fallback={<span className="h-5" />}>
            <ShowingCount searchParams={searchParams} base={{ brand: [found.slug] }} first="category" />
          </Suspense>
        </div>
        {found.logo && (
          <div className="hidden sm:block">
            <ProductImage image={found.logo} alt="" sizes={IMAGE_SIZES.thumb} className="size-[120px] rounded-xl bg-white" preload />
          </div>
        )}
      </div>
    </section>
  );
}

async function Body({ params, searchParams }: Props) {
  const { slug } = await params;
  const found = await brand(slug);
  if (!found) return null;
  return (
    <ListingResults searchParams={searchParams} base={{ brand: [found.slug] }} path={`/brand/${found.slug}`} first="category" />
  );
}

function HeroFallback() {
  return (
    <section className="bg-light">
      <div className="wrap flex flex-col gap-2.5 py-5 sm:py-8">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-10 w-64" />
      </div>
    </section>
  );
}
