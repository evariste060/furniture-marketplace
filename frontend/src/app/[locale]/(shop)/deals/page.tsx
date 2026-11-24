import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { getPathname } from "@/i18n/navigation";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { ListingFallback, ListingResults, ShowingCount } from "@/features/listing/listing-results";

export async function generateMetadata({ params }: PageProps<"/[locale]/deals">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.deals" });
  return { title: t("title") };
}

const BASE = { on_sale: true } as const;

/** /deals: the listing template (Category.dc.html) for products on sale (`on_sale=true`; owner
 * decision 2026-10-27), titled "Deals". */
export default async function DealsPage({ searchParams }: PageProps<"/[locale]/deals">) {
  const t = await getTranslations("store.deals");
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const home = getPathname({ href: "/", locale: await getLocale() });
  return (
    <main id="main">
      <section className="bg-light">
        <div className="wrap flex flex-col gap-2.5 py-5 sm:py-8">
          <Breadcrumb label={tu("breadcrumb")} items={[{ label: th("home"), href: home }, { label: t("title") }]} />
          <h1 className="t-h1 text-head">{t("title")}</h1>
          <p className="max-w-[560px] text-tx2">{t("text")}</p>
          <Suspense fallback={<span className="h-5" />}>
            <ShowingCount searchParams={searchParams} base={BASE} />
          </Suspense>
        </div>
      </section>
      <Suspense fallback={<ListingFallback />}>
        <ListingResults searchParams={searchParams} base={BASE} path="/deals" />
      </Suspense>
    </main>
  );
}
