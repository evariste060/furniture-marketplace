import { ArrowRight, Building2, CircleCheck, ClipboardList, House, School, Store } from "lucide-react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SERVICE_GRID, SERVICE_IMAGE_SIZES } from "@/features/services/card-layout";
import { ServiceCard } from "@/features/services/service-card";
import { ServiceIcon } from "@/features/services/service-icon";
import { ServiceImage } from "@/features/services/service-image";
import { ServiceContactButtons } from "@/features/services/talk-to-us";
import { getPathname, Link } from "@/i18n/navigation";
import { getService, getServices } from "@/lib/api/catalogue";
import { cx } from "@/lib/cx";
import type { components } from "@/lib/api/schema";

type Props = PageProps<"/[locale]/services/[slug]">;
type Service = components["schemas"]["PublicService"];

async function pageLocale(): Promise<"en" | "rw"> {
  return (await getLocale()) === "rw" ? "rw" : "en";
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const service = await getService(slug, await pageLocale()).catch(() => undefined);
  if (service === null) notFound();
  if (!service) return {};
  const t = await getTranslations("store.services");
  const title = `${service.name} | ${t("metaTitle")}`;
  return {
    title,
    description: service.short_description,
    openGraph: {
      title,
      description: service.short_description,
      images: service.image
        ? [
            {
              url: service.image.url,
              width: service.image.width ?? undefined,
              height: service.image.height ?? undefined,
            },
          ]
        : undefined,
    },
  };
}

/** /services/[slug]: one technical service (ADR-013, SC-02): breadcrumb, hero with "Request this
 * service", "What we offer" (its items), "Who it's for", a "Request this service" panel beside
 * Call/WhatsApp, and the other services. Both "Request this service" buttons open the request
 * wizard (/services/[slug]/request, owner 2026-11-17). A hidden or unknown service is 404. */
export default function ServicePage({ params }: Props) {
  return (
    <main id="main">
      <Suspense fallback={<ServiceFallback />}>
        <ServiceContent params={params} />
      </Suspense>
    </main>
  );
}

async function ServiceContent({ params }: Pick<Props, "params">) {
  const { slug } = await params;
  const locale = await pageLocale();
  const t = await getTranslations("store.services");
  let service: Service | null;
  try {
    service = await getService(slug, locale);
  } catch {
    return (
      <div className="wrap py-8">
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("error")}
        </p>
      </div>
    );
  }
  if (!service) notFound();
  const tt = await getTranslations("store.tabs");
  const tu = await getTranslations("ui");
  const path = (href: string) => getPathname({ href, locale });
  const others = (await getServices(locale).catch(() => [])).filter((s) => s.slug !== service.slug);
  const audiences = [
    { Icon: House, label: t("who.homes") },
    { Icon: Building2, label: t("who.offices") },
    { Icon: Store, label: t("who.shops") },
    { Icon: School, label: t("who.institutions") },
  ];

  return (
    <>
      <section className="bg-light">
        <div className="wrap flex flex-col gap-6 pt-5 pb-10 max-sm:pb-7">
          <Breadcrumb
            label={tu("breadcrumb")}
            items={[{ label: tt("home"), href: path("/") }, { label: t("breadcrumbServices"), href: path("/services") }, { label: service.name }]}
            className="max-sm:hidden"
          />
          <div className="flex flex-wrap items-center gap-10 max-sm:gap-6">
            <div className="flex min-w-0 flex-[1_1_420px] flex-col gap-4">
              <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-xl bg-white text-pri shadow-sh">
                <ServiceIcon icon={service.icon} size={24} />
              </span>
              <h1 className="t-h1 text-navy">{service.name}</h1>
              {service.intro.split(/\n{2,}/).map((paragraph, i) => (
                <p key={i} className="m-0 text-lg whitespace-pre-line text-tx2 max-sm:text-base">
                  {paragraph}
                </p>
              ))}
              <div className="flex flex-wrap gap-3 pt-1">
                <Link
                  href={`/services/${service.slug}/request`}
                  className={buttonClasses({
                    size: "lg",
                    className: "shadow-sh2",
                  })}
                >
                  {t("requestThis")}
                  <ArrowRight size={18} aria-hidden="true" />
                </Link>
              </div>
            </div>
            <ServiceImage
              image={service.image}
              icon={service.icon}
              sizes={SERVICE_IMAGE_SIZES.hero}
              preload
              iconSize={72}
              className="aspect-[4/3] w-full flex-[1_1_380px] rounded-2xl shadow-sh"
            />
          </div>
        </div>
      </section>

      <div className="wrap flex flex-col gap-12 py-10 max-sm:gap-8 max-sm:py-7">
        <div className="flex flex-wrap items-start gap-8">
          <section aria-labelledby="offer-title" className="flex min-w-0 flex-[2_1_480px] flex-col gap-4">
            <h2 id="offer-title" className="t-h2">
              {t("offerTitle")}
            </h2>
            <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2">
              {service.items.map((item) => (
                <li key={item.id} className="flex items-start gap-2.5 rounded-lg border border-bd bg-white px-4 py-3">
                  <CircleCheck size={20} aria-hidden="true" className="mt-px flex-none text-ok" />
                  <span>{item.title}</span>
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="who-title" className="flex min-w-0 flex-[1_1_280px] flex-col gap-4">
            <h2 id="who-title" className="t-h2">
              {t("whoTitle")}
            </h2>
            <ul className="m-0 grid list-none grid-cols-2 gap-3 p-0">
              {audiences.map(({ Icon, label }) => (
                <li key={label} className="flex flex-col items-center gap-2 rounded-xl bg-page px-3 py-4 text-center font-medium">
                  <Icon size={24} aria-hidden="true" className="text-pri" />
                  {label}
                </li>
              ))}
            </ul>
            <p className="m-0 text-sm text-tx2">{t("whoText")}</p>
          </section>
        </div>

        <div id="request" className="flex scroll-mt-28 flex-wrap items-start gap-6">
          <section
            aria-labelledby="request-title"
            className="relative flex min-w-0 flex-[999_1_560px] flex-col gap-5 overflow-hidden rounded-xl border border-bd bg-linear-to-br from-light to-white p-8 shadow-sh max-sm:p-5"
          >
            <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-xl bg-white text-pri shadow-sh ring-1 ring-bd">
              <ClipboardList size={24} />
            </span>
            <div className="flex flex-col gap-1.5">
              <h2 id="request-title" className="t-h2">
                {t("formTitle")}
              </h2>
              <p className="m-0 max-w-xl text-tx2">{t("formText", { service: service.name })}</p>
            </div>
            <ol className="m-0 flex list-none flex-wrap gap-2 p-0">
              {(["service", "date", "details", "review"] as const).map((step, i) => (
                <li key={step} className="flex items-center gap-2 rounded-full border border-bd bg-white py-1 pr-3 pl-1 text-sm text-tx">
                  <span aria-hidden="true" className="flex size-6 items-center justify-center rounded-full bg-light text-cap font-semibold text-pri-h">
                    {i + 1}
                  </span>
                  {t(`wizard.steps.${step}`)}
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap items-center gap-4">
              <Link
                href={`/services/${service.slug}/request`}
                className={buttonClasses({
                  size: "lg",
                  className: "shadow-sh2",
                })}
              >
                {t("requestThis")}
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
              <span className="text-sm text-tx2">{t("replyTime")}</span>
            </div>
          </section>
          <aside
            aria-labelledby="talk-side-title"
            className="flex w-full flex-col gap-3 rounded-xl border border-bd bg-white p-6 shadow-sh sm:flex-[1_1_320px] lg:max-w-[380px]"
          >
            <h2 id="talk-side-title" className="t-h4">
              {t("ctaTitle")}
            </h2>
            <p className="m-0 text-sm text-tx2">{t("ctaText")}</p>
            <Suspense>
              <ServiceContactButtons message={t("whatsappServiceText", { service: service.name })} className="flex-col [&>a]:w-full" />
            </Suspense>
          </aside>
        </div>

        {others.length > 0 && (
          <section aria-labelledby="other-title" className="flex flex-col gap-5">
            <h2 id="other-title" className="t-h2">
              {t("otherTitle")}
            </h2>
            <ul className={cx("m-0 list-none p-0", SERVICE_GRID)}>
              {others.map((other) => (
                <li key={other.slug} className="flex">
                  <ServiceCard service={other} headingLevel={3} />
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </>
  );
}

function ServiceFallback() {
  return (
    <div aria-hidden="true">
      <div className="bg-light">
        <div className="wrap flex flex-wrap items-center gap-10 py-10">
          <div className="flex flex-[1_1_420px] flex-col gap-4">
            <Skeleton className="size-12 rounded-xl" />
            <Skeleton className="h-10 w-3/4" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-11 w-52" />
          </div>
          <Skeleton className="aspect-[4/3] flex-[1_1_380px] rounded-2xl" />
        </div>
      </div>
      <div className="wrap grid gap-3 py-10 sm:grid-cols-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    </div>
  );
}
