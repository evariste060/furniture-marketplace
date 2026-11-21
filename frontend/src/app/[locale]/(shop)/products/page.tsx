import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { ListingHeader } from "@/features/listing/listing-header";
import { ListingFallback, ListingResults } from "@/features/listing/listing-results";

export async function generateMetadata({ params }: PageProps<"/[locale]/products">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.allProducts" });
  return { title: t("title") };
}

/** /products ("All Categories" in the header): every public product, in the listing template with
 * the compact header. The API pages the catalogue; further pages load while scrolling. */
export default async function AllProductsPage({ searchParams }: PageProps<"/[locale]/products">) {
  const t = await getTranslations("store.allProducts");
  return (
    <main id="main">
      <ListingHeader title={t("title")} />
      <Suspense fallback={<ListingFallback />}>
        <ListingResults searchParams={searchParams} base={{}} path="/products" infinite />
      </Suspense>
    </main>
  );
}
