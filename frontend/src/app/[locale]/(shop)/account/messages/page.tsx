import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { MessagesView } from "@/features/account/account-messages";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/messages">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.support" });
  return { title: t("mineTitle"), robots: { index: false } };
}

/** /account/messages: the signed-in customer's support conversations. */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <MessagesView />
    </Suspense>
  );
}
