import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import { ServiceRequestWizard } from "@/features/services/request-form";
import { ServiceContactButtons } from "@/features/services/talk-to-us";
import { getPathname } from "@/i18n/navigation";
import { getService } from "@/lib/api/catalogue";
import type { components } from "@/lib/api/schema";

type Props = PageProps<"/[locale]/services/[slug]/request">;
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
  return {
    title: `${t("wizard.title", { service: service.name })} | ${t("metaTitle")}`,
    robots: { index: false },
  };
}

/** /services/[slug]/request: "Request this service" as a step-by-step wizard (owner, 2026-11-17;
 * ADR-013) for the service from GET /services/{slug}. A hidden or unknown service is 404, as its
 * page. Call and WhatsApp stay beside it for customers who would rather talk. */
export default function ServiceRequestPage({ params }: Props) {
  return (
    <main id="main" className="bg-page">
      <Suspense fallback={<RequestFallback />}>
        <RequestContent params={params} />
      </Suspense>
    </main>
  );
}

async function RequestContent({ params }: Pick<Props, "params">) {
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
  return (
    <div className="wrap flex flex-col gap-6 py-6 max-sm:gap-5 max-sm:py-5">
      <Breadcrumb
        label={tu("breadcrumb")}
        items={[
          { label: tt("home"), href: path("/") },
          { label: t("breadcrumbServices"), href: path("/services") },
          { label: service.name, href: path(`/services/${service.slug}`) },
          { label: t("requestThis") },
        ]}
        className="max-sm:hidden"
      />
      <h1 className="t-h1 text-navy max-sm:text-[26px] max-sm:leading-8">{t("wizard.title", { service: service.name })}</h1>
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col">
          <ServiceRequestWizard
            service={{
              slug: service.slug,
              name: service.name,
              short_description: service.short_description,
              icon: service.icon,
              image: service.image ?? null,
              items: service.items.map((i) => i.title),
            }}
          />
        </div>
        <aside
          aria-labelledby="talk-side-title"
          className="flex w-full flex-col gap-3 rounded-xl border border-bd bg-white p-6 shadow-sh sm:flex-[1_1_300px] lg:max-w-[340px]"
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
    </div>
  );
}

function RequestFallback() {
  return (
    <div aria-hidden="true" className="wrap flex flex-col gap-6 py-6">
      <Skeleton className="h-10 w-2/3" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-[420px] w-full rounded-xl" />
    </div>
  );
}
