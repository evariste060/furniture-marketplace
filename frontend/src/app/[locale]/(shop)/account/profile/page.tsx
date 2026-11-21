import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { ProfileView } from "@/features/account/account-settings";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/profile">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.account" });
  return { title: t("profileTitle"), robots: { index: false } };
}

/** /account/profile (Profile.dc.html). */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <ProfileView />
    </Suspense>
  );
}
