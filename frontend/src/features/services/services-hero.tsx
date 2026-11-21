import { ArrowDown, MessageCircle, PhoneCall, Wrench } from "lucide-react";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";
import { buttonClasses } from "@/components/ui/button";
import { cx } from "@/lib/cx";
import type { ServiceSummary } from "./card-layout";
import { ServiceIcon } from "./service-icon";
import { ServiceImage } from "./service-image";

/** The services page hero (owner, 2026-11-17): the heading, intro and two calls to action on the
 * left; on the right a collage of the services themselves (their photos, or their icon
 * placeholders until staff upload one), so the picture always shows what is offered and nothing
 * is hard-coded. Services with a photo come first. On phones the collage sits under the text. */
export async function ServicesHero({ services, breadcrumb }: { services: ServiceSummary[]; breadcrumb: ReactNode }) {
  const t = await getTranslations("store.services");
  const shown = [...services].sort((a, b) => Number(!!b.image) - Number(!!a.image)).slice(0, 3);
  return (
    <div className="relative overflow-hidden bg-linear-to-br from-light via-light to-white">
      <span aria-hidden="true" className="pointer-events-none absolute -top-40 -right-32 size-[520px] rounded-full bg-pri/6 blur-3xl" />
      <div className="wrap relative flex flex-col gap-5 pt-5 pb-14 max-sm:pb-9">
        {breadcrumb}
        <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] max-lg:gap-9">
          <div className="flex flex-col gap-5 motion-safe:animate-hero-rise">
            <span className="t-over flex items-center gap-2 text-pri-h">
              <Wrench size={16} aria-hidden="true" />
              {t("hero.overline")}
            </span>
            <h1 className="t-h1 m-0 text-[44px] leading-[52px] text-navy max-sm:text-[30px] max-sm:leading-9">{t("title")}</h1>
            <p className="m-0 max-w-xl text-lg text-tx2 max-sm:text-base">{t("intro")}</p>
            <div className="flex flex-wrap gap-3 pt-1">
              <a
                href="#services-list"
                className={buttonClasses({
                  size: "lg",
                  className: "shadow-sh2",
                })}
              >
                {t("hero.explore")}
                <ArrowDown size={18} aria-hidden="true" />
              </a>
              <a
                href="#services-promo"
                className={buttonClasses({
                  variant: "outline",
                  size: "lg",
                  className: "bg-white",
                })}
              >
                <MessageCircle size={18} aria-hidden="true" />
                {t("hero.talk")}
              </a>
            </div>
            <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-2 p-0 pt-2 text-sm text-tx2">
              <li className="flex items-center gap-2">
                <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-full bg-white text-pri shadow-sh">
                  <Wrench size={14} />
                </span>
                {t("hero.count", { count: services.length })}
              </li>
              <li className="flex items-center gap-2">
                <span aria-hidden="true" className="flex size-7 items-center justify-center rounded-full bg-white text-pri shadow-sh">
                  <PhoneCall size={14} />
                </span>
                {t("replyTime")}
              </li>
            </ul>
          </div>
          {shown.length > 0 && <Collage services={shown} />}
        </div>
      </div>
    </div>
  );
}

/** One large tile and two smaller ones beside it, each labelled with its service; decorative,
 * since the same services are listed (and linked) right below. */
function Collage({ services }: { services: ServiceSummary[] }) {
  const [main, ...rest] = services;
  return (
    <div aria-hidden="true" className="relative motion-safe:animate-hero-pop">
      <div className={cx("grid gap-4 max-sm:gap-3", rest.length > 0 && "grid-cols-[1.35fr_1fr] grid-rows-2")}>
        <Tile
          service={main!}
          sizes="(max-width: 1024px) 60vw, 380px"
          className={cx("aspect-[4/3]", rest.length > 0 && "row-span-2 aspect-auto h-full min-h-[300px] max-sm:min-h-[220px]")}
          large
        />
        {rest.map((service) => (
          <Tile key={service.slug} service={service} sizes="(max-width: 1024px) 40vw, 280px" className="aspect-[4/3] h-full" />
        ))}
      </div>
      <span className="absolute -bottom-5 left-6 flex items-center gap-2.5 rounded-xl border border-bd bg-white py-2.5 pr-4 pl-2.5 shadow-lift motion-safe:animate-hero-float max-sm:hidden">
        <span className="flex size-9 items-center justify-center rounded-lg bg-light text-pri">
          <ServiceIcon icon={main!.icon} size={18} />
        </span>
        <b className="text-sm font-semibold text-navy">{main!.name}</b>
      </span>
    </div>
  );
}

function Tile({ service, sizes, className, large = false }: { service: ServiceSummary; sizes: string; className?: string; large?: boolean }) {
  return (
    <span className={cx("relative block overflow-hidden rounded-2xl border border-white bg-white shadow-lift", className)}>
      <ServiceImage image={service.image} icon={service.icon} sizes={sizes} iconSize={large ? 72 : 40} preload={large} className="absolute! inset-0 size-full" />
      {!large && (
        <span className="absolute right-2.5 bottom-2.5 left-2.5 truncate rounded-lg bg-white/90 px-2.5 py-1.5 text-cap font-semibold text-navy backdrop-blur">
          {service.name}
        </span>
      )}
    </span>
  );
}
