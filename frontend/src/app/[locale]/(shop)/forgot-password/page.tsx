import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { ForgotView } from "@/features/auth/auth-forms";

export async function generateMetadata({ params }: PageProps<"/[locale]/forgot-password">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.auth" });
  return { title: t("forgotMeta"), robots: { index: false } };
}

/** /forgot-password (Forgot.dc.html). */
export default function Page() {
  return (
    <main id="main" className="bg-page">
      <div className="wrap pt-14 max-sm:pt-6 sm:pb-[72px] pb-16">
        <Suspense fallback={null}>
          <ForgotView />
        </Suspense>
      </div>
    </main>
  );
}
