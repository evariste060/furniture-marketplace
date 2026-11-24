import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { TrackOrder } from "@/features/orders/track-order";
import { getPathname } from "@/i18n/navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/track">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.track" });
  return { title: t("metaTitle"), robots: { index: false } };
}

/** /track (Track.dc.html). */
export default async function TrackPage() {
  const t = await getTranslations("store.track");
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const locale = await getLocale();
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex max-w-[1040px] flex-col gap-6 pt-10 pb-16 max-sm:pt-5">
        <div className="flex flex-col gap-1.5">
          <Breadcrumb label={tu("breadcrumb")} items={[{ label: th("home"), href: getPathname({ href: "/", locale }) }, { label: t("crumb") }]} />
          <h1 className="t-h1 text-head">{t("title")}</h1>
          <p className="text-tx2">{t("text")}</p>
        </div>
        <Suspense fallback={null}>
          <TrackOrder />
        </Suspense>
      </div>
    </main>
  );
}
