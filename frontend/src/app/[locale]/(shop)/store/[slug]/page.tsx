import { MapPin, Store } from "lucide-react";
import type { Metadata } from "next";
import Image from "next/image";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { ListingFallback, ListingResults, ShowingCount } from "@/features/listing/listing-results";
import { getPathname } from "@/i18n/navigation";
import { getStore } from "@/lib/api/catalogue";
import { IMAGE_SIZES } from "@/lib/images";

type Props = PageProps<"/[locale]/store/[slug]">;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const found = await getStore(slug).catch(() => null);
  if (!found) return {};
  return { title: found.name, description: found.description?.slice(0, 160) || undefined };
}

/** /store/[slug] (ADR-014 phase 5): one approved store's public page, its profile and its
 * products as the Category.dc.html listing filtered by the store. Any store that is not approved
 * is 404, like an unknown one; the page never shows contact details or the owner. */
export default function StorePage({ params, searchParams }: Props) {
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
  const found = await getStore(slug);
  if (!found) notFound();
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const t = await getTranslations("store.storePage");
  const locale = await getLocale();
  return (
    <section className="overflow-hidden bg-light">
      {found.cover && (
        <div className="relative h-32 w-full bg-white sm:h-48">
          <Image src={found.cover.url} alt="" fill sizes="100vw" preload className="object-cover" />
        </div>
      )}
      <div className="wrap flex flex-wrap items-center gap-5 py-5 sm:py-8">
        <div className="flex size-20 flex-none items-center justify-center overflow-hidden rounded-xl border border-bd bg-white sm:size-[120px]">
          {found.logo ? (
            <ProductImage image={found.logo} alt="" sizes={IMAGE_SIZES.thumb} className="size-full" preload />
          ) : (
            <Store size={36} className="text-mut" aria-hidden="true" />
          )}
        </div>
        <div className="flex max-w-[760px] min-w-0 flex-[1_1_320px] flex-col gap-2.5">
          <Breadcrumb
            label={tu("breadcrumb")}
            items={[{ label: th("home"), href: getPathname({ href: "/", locale }) }, { label: found.name }]}
          />
          <h1 className="t-h1 text-navy">{found.name}</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-tx2">
            <span className="inline-flex items-center gap-1.5">
              <MapPin size={16} aria-hidden="true" />
              <span className="sr-only">{t("location")} </span>
              {found.district}
            </span>
            <Suspense fallback={<span className="h-5" />}>
              <ShowingCount searchParams={searchParams} base={{ store: found.slug }} />
            </Suspense>
          </div>
          {found.description && <p className="m-0 whitespace-pre-line text-tx2">{found.description}</p>}
        </div>
      </div>
    </section>
  );
}

async function Body({ params, searchParams }: Props) {
  const { slug } = await params;
  const found = await getStore(slug);
  if (!found) return null;
  return <ListingResults searchParams={searchParams} base={{ store: found.slug }} path={`/store/${found.slug}`} />;
}

function HeroFallback() {
  return (
    <section className="bg-light">
      <div className="wrap flex items-center gap-5 py-5 sm:py-8">
        <Skeleton className="size-20 rounded-xl sm:size-[120px]" />
        <div className="flex flex-col gap-2.5">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-10 w-64" />
        </div>
      </div>
    </section>
  );
}
