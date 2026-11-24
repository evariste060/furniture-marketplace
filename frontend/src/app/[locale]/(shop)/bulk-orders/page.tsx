import { ClipboardList, FileText, Truck } from "lucide-react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { CardsFallback, ContactCards } from "@/features/contact/contact-cards";
import { SideCard } from "@/features/contact/side-card";
import { QuoteForm } from "@/features/contact/quote-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("store.bulk");
  return { title: t("metaTitle") };
}

/** /bulk-orders: business and bulk quote requests (POST /quote-requests, module 19), kept apart
 * from customer support on /contact. How a quote works on the side, with the store's contacts. */
export default async function BulkOrdersPage() {
  const t = await getTranslations("store.bulk");
  const steps = [
    { Icon: ClipboardList, title: t("step1"), text: t("step1Text") },
    { Icon: FileText, title: t("step2"), text: t("step2Text") },
    { Icon: Truck, title: t("step3"), text: t("step3Text") },
  ];
  return (
    <main id="main">
      {/* No hero: the form starts right under the store header. The title stays for screen readers. */}
      <h1 className="sr-only">{t("title")}</h1>
      <div className="bg-page">
        <div className="wrap flex flex-wrap items-start gap-6 pt-6 pb-16 max-sm:pt-4 max-sm:pb-10">
          <div className="flex min-w-0 flex-[999_1_560px] flex-col">
            <QuoteForm />
          </div>
          <aside aria-label={t("sideLabel")} className="flex w-full flex-col gap-4 sm:flex-[1_1_320px] lg:max-w-[380px]">
            <SideCard id="bulk-how" title={t("howTitle")}>
              <ol className="m-0 flex list-none flex-col p-0">
                {steps.map(({ Icon, title, text }, i) => (
                  <li key={title} className="relative flex items-start gap-3.5 pb-5 last:pb-0">
                    {/* The line joining each step to the next. */}
                    {i < steps.length - 1 && <span aria-hidden="true" className="absolute top-11 bottom-1 left-5 w-0.5 -translate-x-1/2 rounded-full bg-bd" />}
                    <span aria-hidden="true" className="relative flex size-10 flex-none items-center justify-center rounded-full bg-light text-pri-fg">
                      <Icon size={20} />
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="text-cap font-semibold text-pri-h">{t("stepLabel", { step: i + 1 })}</span>
                      <b className="font-semibold">{title}</b>
                      <span className="text-sm text-tx2">{text}</span>
                    </span>
                  </li>
                ))}
              </ol>
            </SideCard>
            <Suspense fallback={<CardsFallback compact />}>
              <ContactCards card={{ id: "bulk-talk", title: t("talkTitle") }} />
            </Suspense>
          </aside>
        </div>
      </div>
    </main>
  );
}
