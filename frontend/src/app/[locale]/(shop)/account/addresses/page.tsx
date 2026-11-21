import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { AddressesView } from "@/features/account/account-settings";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/addresses">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.account" });
  return { title: t("addressesTitle"), robots: { index: false } };
}

/** /account/addresses (Addresses.dc.html). */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <AddressesView />
    </Suspense>
  );
}
