import { ArrowRight, Building2, PackageSearch, RotateCcw, ShieldCheck, Truck } from "lucide-react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { CardsFallback, ContactCards } from "@/features/contact/contact-cards";
import { SideCard } from "@/features/contact/side-card";
import { SupportWizard } from "@/features/support/support-wizard";
import { Link } from "@/i18n/navigation";
import { INFO_PAGES } from "@/lib/info-pages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("store.contact");
  return { title: t("metaTitle") };
}

/** /contact: Contact.dc.html, for customer support. The store's WhatsApp, phone, email, address
 * and opening hours come from GET /settings (module 19), each left out while unset. The support
 * wizard sends POST /support-messages (answered from the admin's Support page). The side
 * column has the other ways to reach the store, quick help links and the way to Business & bulk
 * orders (/bulk-orders, its own form). The design's map is not shown (no map service is chosen). */
export default async function ContactPage() {
  const t = await getTranslations("store.contact");
  const tf = await getTranslations("store.footer");
  const help = [
    { Icon: PackageSearch, label: tf("trackOrder"), href: "/track" },
    { Icon: Truck, label: tf("delivery"), href: INFO_PAGES.delivery },
    { Icon: RotateCcw, label: tf("returns"), href: INFO_PAGES.returns },
    { Icon: ShieldCheck, label: tf("warranty"), href: INFO_PAGES.warranty },
  ];
  return (
    <main id="main">
      {/* No hero: the form starts right under the store header. The title stays for screen readers. */}
      <h1 className="sr-only">{t("title")}</h1>
      <div className="bg-page">
        <div className="wrap flex flex-wrap items-start gap-6 pt-6 pb-16 max-sm:pt-4 max-sm:pb-10">
          <SupportWizard />
          <aside aria-label={t("sideLabel")} className="flex w-full flex-col gap-4 sm:flex-[1_1_320px] lg:max-w-[380px]">
            <Suspense fallback={<CardsFallback compact />}>
              <ContactCards card={{ id: "contact-reach", title: t("reachTitle") }} />
            </Suspense>
            <SideCard id="contact-help" title={t("helpTitle")}>
              <ul className="-mx-2 my-0 flex list-none flex-col p-0">
                {help.map(({ Icon, label, href }) => (
                  <li key={href}>
                    <Link href={href} className="group flex items-center gap-3 rounded-lg px-2 py-2.5 text-tx no-underline hover:bg-page hover:text-tx">
                      <Icon size={18} aria-hidden="true" className="flex-none text-pri-fg" />
                      <span className="min-w-0 flex-1 font-medium">{label}</span>
                      <ArrowRight size={16} aria-hidden="true" className="flex-none text-mut transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-pri-fg motion-reduce:transition-none" />
                    </Link>
                  </li>
                ))}
              </ul>
            </SideCard>
            {/* Bulk buying is not support: it has its own page and form. */}
            <Link href="/bulk-orders" className="group relative flex items-center gap-3.5 overflow-hidden rounded-xl bg-deep p-5 text-white no-underline hover:text-white">
              <span aria-hidden="true" className="pointer-events-none absolute -top-16 -right-12 size-40 rounded-full bg-pri/40 blur-2xl" />
              <span aria-hidden="true" className="relative flex size-11 flex-none items-center justify-center rounded-[10px] bg-white/15">
                <Building2 size={22} />
              </span>
              <span className="relative flex min-w-0 flex-1 flex-col">
                <b className="font-semibold">{t("bulkTitle")}</b>
                <span className="text-sm text-odm">{t("bulkText")}</span>
              </span>
              <ArrowRight size={18} aria-hidden="true" className="relative flex-none transition-transform duration-150 group-hover:translate-x-0.5 motion-reduce:transition-none" />
            </Link>
          </aside>
        </div>
      </div>
    </main>
  );
}
