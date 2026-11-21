import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { RegisterView } from "@/features/auth/auth-forms";

export async function generateMetadata({ params }: PageProps<"/[locale]/register">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.auth" });
  return { title: t("registerMeta"), robots: { index: false } };
}

/** /register (Register.dc.html). */
export default function Page() {
  return (
    <main id="main" className="bg-page">
      <div className="wrap pt-12 max-sm:pt-6 pb-16">
        <Suspense fallback={null}>
          <RegisterView />
        </Suspense>
      </div>
    </main>
  );
}
