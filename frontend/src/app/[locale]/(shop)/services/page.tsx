import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import { SERVICE_GRID as GRID, type ServiceSummary } from "@/features/services/card-layout";
import { ServiceGrid } from "@/features/services/service-grid";
import { ServicesHero } from "@/features/services/services-hero";
import { getPathname } from "@/i18n/navigation";
import { getServices } from "@/lib/api/catalogue";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("store.services");
  const locale = (await getLocale()) === "rw" ? "rw" : "en";
  const services = await getServices(locale).catch(() => []);
  const image = services.find((s) => s.image)?.image;
  return {
    title: t("metaTitle"),
    description: t("metaDescription"),
    openGraph: {
      title: t("metaTitle"),
      description: t("metaDescription"),
      images: image
        ? [
            {
              url: image.url,
              width: image.width ?? undefined,
              height: image.height ?? undefined,
            },
          ]
        : undefined,
    },
  };
}

/** The grid: one column on small phones, two from 520px (large phones, tablets), four on desktop. */

/** /services: the technical services (ADR-013, SC-02; layout owner 2026-11-17): a split hero
 * (text and calls to action, with a collage of the services), the service cards four to a row
 * with a promotional card two places wide closing the 2nd row (it replaces the former
 * "Talk to our team" band). */
export default function ServicesPage() {
  return (
    <main id="main">
      <Suspense fallback={<PageFallback />}>
        <ServicesContent />
      </Suspense>
    </main>
  );
}

async function ServicesContent() {
  const t = await getTranslations("store.services");
  const tt = await getTranslations("store.tabs");
  const tu = await getTranslations("ui");
  const locale = (await getLocale()) === "rw" ? "rw" : "en";
  const services: ServiceSummary[] | null = await getServices(locale).catch(() => null);
  const breadcrumb = (
    <Breadcrumb
      label={tu("breadcrumb")}
      items={[{ label: tt("home"), href: getPathname({ href: "/", locale }) }, { label: t("breadcrumbServices") }]}
      className="max-sm:hidden"
    />
  );
  return (
    <>
      <ServicesHero services={services ?? []} breadcrumb={breadcrumb} />
      <div className="wrap flex flex-col gap-12 py-12 max-sm:gap-8 max-sm:py-8">
        <section id="services-list" aria-labelledby="services-list-title" className="flex scroll-mt-28 flex-col gap-6">
          <div className="flex flex-col gap-1.5">
            <h2 id="services-list-title" className="t-h2 m-0">
              {t("listTitle")}
            </h2>
            <p className="m-0 text-tx2">{t("listText")}</p>
          </div>
          {services === null ? (
            <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
              {t("error")}
            </p>
          ) : services.length === 0 ? (
            <p className="rounded-xl border border-dashed border-bd2 px-4 py-6 text-center text-tx2">{t("empty")}</p>
          ) : (
            <ServiceGrid services={services} label={t("listLabel")} />
          )}
        </section>
      </div>
    </>
  );
}


function PageFallback() {
  return (
    <div aria-hidden="true">
      <div className="bg-light">
        <div className="wrap grid items-center gap-12 pt-12 pb-14 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-12 w-4/5" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-12 w-72" />
          </div>
          <Skeleton className="h-[320px] w-full rounded-2xl" />
        </div>
      </div>
      <div className={`wrap py-12 ${GRID}`}>
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-[340px] w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}
