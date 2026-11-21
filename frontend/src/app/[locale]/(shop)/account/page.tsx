import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { AccountOverview } from "@/features/account/account-orders";

export async function generateMetadata({ params }: PageProps<"/[locale]/account">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.account" });
  return { title: t("overviewMeta"), robots: { index: false } };
}

/** /account (Account.dc.html). */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <AccountOverview />
    </Suspense>
  );
}
