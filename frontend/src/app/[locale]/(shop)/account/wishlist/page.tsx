import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { WishlistView } from "@/features/wishlist/wishlist-view";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/wishlist">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.account" });
  return { title: t("wishlistTitle"), robots: { index: false } };
}

/** /account/wishlist (module 21; no design: the account layout and a ListingCard grid). */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <WishlistView />
    </Suspense>
  );
}
