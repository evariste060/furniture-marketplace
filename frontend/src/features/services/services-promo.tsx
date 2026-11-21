import { ArrowRight, Headset, Mail, Phone } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { CARD_HOVER } from "@/components/store/product-card";
import { buttonClasses } from "@/components/ui/button";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";
import { Link } from "@/i18n/navigation";
import { getStoreContact } from "@/lib/api/catalogue";
import { telHref, whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import type { ServiceSummary } from "./card-layout";
import { ServiceIcon } from "./service-icon";

/** Where the promotional card goes in the services grid. It is two places wide, so it takes the
 * last two places of the 2nd row on desktop (index 6, columns 3 and 4), or comes right after the
 * last service when there are fewer. */
export const PROMO_INDEX = 6;
export function promoIndex(serviceCount: number): number {
  return Math.min(PROMO_INDEX, serviceCount);
}

/** The promotional card in the services grid (owner, 2026-11-17): two grid places wide (a full
 * row on tablets), white with the same border and hover as the service cards, the services' icons
 * as its picture. It replaces the page's closing "Talk to our team" band, so it offers the
 * store's contact channels as three equal buttons: WhatsApp (prefilled), Call and Email (owner,
 * 2026-11-18), each left out while unset, and the contact page when none is set. It is on the
 * Services page and the home page's Our Services. A request for one service is made from its card. */
export async function ServicesPromo({ services }: { services: ServiceSummary[] }) {
  const t = await getTranslations("store.services");
  const tl = await getTranslations("store.contactLinks");
  const contact = await getStoreContact().catch(() => null);
  const icons = services.slice(0, 6);
  // The same size for each button, side by side with the icon over the label so the names fit: WhatsApp (prefilled), Call and Email, each one
  // only when the store has set it.
  const button = (variant: "whatsapp" | "outline" | "neutral") => buttonClasses({ variant, className: "h-auto! min-h-14 min-w-0 flex-col gap-1! px-1! py-2 text-[13px]! leading-4!" });
  const ways = [
    contact?.whatsapp && (
      <a key="whatsapp" href={whatsappHref(contact.whatsapp, t("whatsappText"))} target="_blank" rel="noopener noreferrer" className={button("whatsapp")}>
        <WhatsAppIcon size={17} aria-hidden="true" className="flex-none" />
        <span className="truncate">{t("promo.whatsapp")}</span>
        <span className="sr-only"> {tl("newTab")}</span>
      </a>
    ),
    contact?.phone && (
      <a key="phone" href={telHref(contact.phone)} className={button("outline")}>
        <Phone size={17} aria-hidden="true" className="flex-none" />
        <span className="truncate">{t("promo.call")}</span>
      </a>
    ),
    contact?.email && (
      <a key="email" href={`mailto:${contact.email}?subject=${encodeURIComponent(t("promo.emailSubject"))}`} className={button("outline")}>
        <Mail size={17} aria-hidden="true" className="flex-none" />
        <span className="truncate">{t("promo.email")}</span>
      </a>
    ),
  ].filter(Boolean);
  return (
    <aside
      id="services-promo"
      aria-labelledby="services-promo-title"
      className={cx("@container relative flex w-full min-w-0 scroll-mt-28 overflow-hidden rounded-xl border border-bd bg-white text-tx", CARD_HOVER)}
    >
      <div className="flex w-full flex-col @min-[520px]:flex-row">
        <div className="px-2 pt-2 sm:px-3 sm:pt-3 @min-[520px]:w-[42%] @min-[520px]:flex-none @min-[520px]:py-3 @min-[520px]:pr-0">
          <div
            aria-hidden="true"
            className="relative flex aspect-[16/10] h-full w-full items-center justify-center overflow-hidden rounded-lg bg-linear-to-br from-light to-white @min-[520px]:aspect-auto @min-[520px]:min-h-[220px]"
          >
            <span className="flex size-16 items-center justify-center rounded-2xl bg-pri text-white shadow-sh2 motion-safe:animate-hero-float">
              <Headset size={30} />
            </span>
            {icons.map((service, i) => {
              const angle = (i / icons.length) * 2 * Math.PI - Math.PI / 2;
              return (
                <span
                  key={service.slug}
                  className="absolute flex size-9 items-center justify-center rounded-lg bg-white text-pri shadow-sh ring-1 ring-bd"
                  style={{
                    left: `${50 + 36 * Math.cos(angle)}%`,
                    top: `${50 + 34 * Math.sin(angle)}%`,
                    translate: "-50% -50%",
                  }}
                >
                  <ServiceIcon icon={service.icon} size={16} />
                </span>
              );
            })}
          </div>
        </div>
        <div className="flex flex-1 flex-col gap-2 px-3.5 pt-3 pb-3.5 @min-[520px]:justify-center @min-[520px]:px-7 @min-[520px]:py-6">
          <span className="t-over text-pri-h">{t("promo.overline")}</span>
          <h2 id="services-promo-title" className="m-0 text-2xl leading-8 font-bold text-navy max-sm:text-xl max-sm:leading-7">
            {t("promo.title")}
          </h2>
          <p className="m-0 mb-2 text-tx2">{t("promo.text")}</p>
          <p className="m-0 mb-2 text-sm text-tx2">{t("replyTime")}</p>
          {ways.length > 0 ? (
            <div className={cx("mt-auto grid gap-2 @min-[520px]:mt-0", ways.length === 3 ? "grid-cols-3" : ways.length === 2 ? "grid-cols-2" : "grid-cols-1")}>
              {ways}
            </div>
          ) : (
            <Link href="/contact" className={buttonClasses({ size: "lg", className: "mt-auto self-start @min-[520px]:mt-0" })}>
              {t("promo.contact")}
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          )}
        </div>
      </div>
    </aside>
  );
}
