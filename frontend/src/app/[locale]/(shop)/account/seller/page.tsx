import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { SellerApplicationView } from "@/features/account/seller-application";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/seller">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.account.seller" });
  return { title: t("title"), robots: { index: false } };
}

/** /account/seller: apply to sell and follow the application (ADR-014 phase 4). */
export default function Page() {
  return <SellerApplicationView />;
}
