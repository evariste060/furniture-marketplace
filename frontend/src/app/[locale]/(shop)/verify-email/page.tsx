import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { VerifyEmailView } from "@/features/auth/email-verification";

export async function generateMetadata({ params }: PageProps<"/[locale]/verify-email">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.auth.verify" });
  return { title: t("pageMeta"), robots: { index: false } };
}

/** /verify-email: the page the verification email links to (#token=…). The owner's Screen 2
 * (2026-11-13): the branded card, on the storefront's light page background like the other
 * sign-in pages (the storefront has no dark theme). */
export default function Page() {
  return (
    <main id="main" className="bg-page">
      <div className="wrap pt-14 max-sm:pt-6 sm:pb-[72px] pb-16">
        <Suspense fallback={null}>
          <VerifyEmailView />
        </Suspense>
      </div>
    </main>
  );
}
