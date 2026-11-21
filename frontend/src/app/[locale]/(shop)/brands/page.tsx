import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import { getBrands } from "@/lib/api/catalogue";
import { IMAGE_SIZES } from "@/lib/images";

export async function generateMetadata({ params }: PageProps<"/[locale]/brands">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.brands" });
  return { title: t("title") };
}

const GRID = "m-0 grid list-none grid-cols-2 gap-2.5 p-0 sm:grid-cols-3 sm:gap-4 lg:grid-cols-6";

/** /brands: the active brands from GET /catalog/brands as a logo grid in the home page's
 * category-tile pattern, each linking to /brand/[slug] (owner decision 2026-10-27; no design). */
export default async function BrandsPage() {
  const t = await getTranslations("store.brands");
  return (
    <main id="main" className="bg-page">
      <section className="bg-light">
        <div className="wrap flex flex-col gap-2.5 py-8">
          <h1 className="t-h1 text-navy">{t("title")}</h1>
          <p className="text-tx2">{t("text")}</p>
        </div>
      </section>
      <div className="wrap py-8 sm:pb-14">
        <Suspense
          fallback={
            <div className={GRID}>
              {Array.from({ length: 12 }, (_, i) => (
                <Skeleton key={i} className="h-[170px] rounded-xl" />
              ))}
            </div>
          }
        >
          <BrandGrid />
        </Suspense>
      </div>
    </main>
  );
}

async function BrandGrid() {
  const t = await getTranslations("store.brands");
  let brands;
  try {
    brands = await getBrands();
  } catch {
    return (
      <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
        {t("error")}
      </p>
    );
  }
  if (!brands.length) return <p className="text-tx2">{t("empty")}</p>;
  return (
    <ul className={GRID}>
      {brands.map((b) => (
        <li key={b.id}>
          <Link
            href={`/brand/${b.slug}`}
            className="flex h-full flex-col gap-2.5 rounded-xl border border-bd bg-white p-4 text-tx hover:border-pri hover:text-tx"
          >
            <span className="flex h-24 items-center justify-center">
              <ProductImage image={b.logo ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-22 bg-white" />
            </span>
            <span className="font-semibold">{b.name}</span>
            <span className="text-cap text-mut">{t("products", { count: b.product_count })}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
