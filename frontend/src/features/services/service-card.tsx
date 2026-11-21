"use client";

import { CalendarCheck, CircleCheck, ListChecks, RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { buttonClasses } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { BACK_ITEMS, SERVICE_IMAGE_SIZES, type ServiceSummary } from "./card-layout";
import { ServiceIcon } from "./service-icon";
import { ServiceImage } from "./service-image";


/** The front sets the card's height (so all cards in a row match); the back covers the same box
 * and scrolls its list when a service has many items. */
const FACE = "flex min-w-0 flex-col overflow-hidden rounded-xl border bg-white text-tx [backface-visibility:hidden]";

const FLIP_BUTTON =
  "flex size-9 flex-none cursor-pointer items-center justify-center rounded-full border-0 bg-white text-pri-h shadow-sh ring-1 ring-bd transition-colors hover:bg-light focus-visible:outline-2";

/** A service card that flips (owner, 2026-11-17), used on the home page, /services and "Other
 * services". The front: photo (or placeholder), name, card text, and two actions like the product
 * cards: Details (the service page) and Book Now (its request wizard). The back: "What's
 * included", the service's own items from the API, and the same two actions. A mouse flips it on
 * hover and back on leave; touch and keyboard users press "See what's included" (and "Back to
 * overview", or Esc). The action buttons only navigate, they never flip the card. The hidden face
 * is inert, so it is neither read out nor tabbed to. With reduced motion the faces swap without
 * turning. No price is shown: services have none. */
export function ServiceCard({ service, headingLevel = 2 }: { service: ServiceSummary; headingLevel?: 2 | 3 }) {
  const t = useTranslations("store.services.card");
  const [flipped, setFlipped] = useState(false);
  const toFront = useRef<HTMLButtonElement>(null);
  const toBack = useRef<HTMLButtonElement>(null);
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const href = `/services/${service.slug}`;
  const shown = service.items.slice(0, BACK_ITEMS);
  const more = service.items.length - shown.length;

  /** A button flip moves focus to the other face's flip button (the pressed one turns inert). */
  function flip(next: boolean) {
    setFlipped(next);
    requestAnimationFrame(() => (next ? toFront : toBack).current?.focus());
  }
  // A mouse flips the card on hover (touch and keyboard use the flip buttons); Esc turns it back.
  // Listened for on the card itself, as an addition to the buttons, not as its only control.
  const card = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = card.current;
    if (!el) return;
    const enter = (e: PointerEvent) => e.pointerType === "mouse" && setFlipped(true);
    const leave = (e: PointerEvent) => e.pointerType === "mouse" && setFlipped(false);
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const onBack = el.querySelector("[data-face=back]")?.contains(document.activeElement);
      setFlipped(false);
      if (onBack) requestAnimationFrame(() => toBack.current?.focus());
    };
    el.addEventListener("pointerenter", enter);
    el.addEventListener("pointerleave", leave);
    el.addEventListener("keydown", key);
    return () => {
      el.removeEventListener("pointerenter", enter);
      el.removeEventListener("pointerleave", leave);
      el.removeEventListener("keydown", key);
    };
  }, []);

  const actions = (
    <div className="flex gap-2">
      <Link
        href={href}
        className={buttonClasses({
          variant: "outline",
          size: "sm",
          className: "flex-1 px-2",
        })}
      >
        {t("details")}
        <span className="sr-only">: {service.name}</span>
      </Link>
      <Link href={`${href}/request`} className={buttonClasses({ size: "sm", className: "flex-1 px-2" })}>
        <CalendarCheck size={16} aria-hidden="true" />
        {t("book")}
        <span className="sr-only">: {service.name}</span>
      </Link>
    </div>
  );

  return (
    <article aria-label={service.name} ref={card} className="relative flex w-full min-w-0 [perspective:1400px]">
      <div
        data-flipped={flipped || undefined}
        className={cx(
          "relative flex w-full transition-transform duration-700 ease-soft [transform-style:preserve-3d] motion-reduce:transition-none",
          flipped && "[transform:rotateY(180deg)]",
        )}
      >
        <div data-face="front" inert={flipped} className={cx(FACE, "w-full border-bd")}>
          <div className="relative px-2 pt-2 sm:px-3 sm:pt-3">
            <Link href={href} tabIndex={-1} aria-hidden="true" className="block overflow-hidden rounded-lg">
              <ServiceImage image={service.image} icon={service.icon} sizes={SERVICE_IMAGE_SIZES.card} className="aspect-[16/10] w-full" />
            </Link>
            {service.image && (
              <span
                aria-hidden="true"
                className="pointer-events-none absolute top-4 left-4 flex size-9 items-center justify-center rounded-lg bg-white text-pri shadow-sh ring-1 ring-bd sm:top-5 sm:left-5"
              >
                <ServiceIcon icon={service.icon} size={18} />
              </span>
            )}
            <button
              ref={toBack}
              type="button"
              onClick={() => flip(true)}
              aria-label={`${t("showIncluded")}: ${service.name}`}
              title={t("showIncluded")}
              className={cx(FLIP_BUTTON, "absolute top-4 right-4 sm:top-5 sm:right-5")}
            >
              <ListChecks size={18} aria-hidden="true" />
            </button>
          </div>
          <div className="flex flex-1 flex-col gap-1.5 px-3.5 pt-3 pb-3.5">
            <Heading className="m-0 text-base leading-5 font-semibold">
              <Link href={href} className="line-clamp-2 text-tx hover:text-pri">
                {service.name}
              </Link>
            </Heading>
            <p className="m-0 mb-2 line-clamp-3 text-sm text-tx2">{service.short_description}</p>
            <div className="mt-auto">{actions}</div>
          </div>
        </div>

        <div data-face="back" inert={!flipped} className={cx(FACE, "absolute inset-0 border-pri/45 bg-linear-to-b from-light to-white shadow-lift [transform:rotateY(180deg)]")}>
          <div className="flex min-h-0 flex-1 flex-col gap-3 p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span aria-hidden="true" className="flex size-9 flex-none items-center justify-center rounded-lg bg-white text-pri shadow-sh ring-1 ring-bd">
                  <ServiceIcon icon={service.icon} size={18} />
                </span>
                <div className="flex min-w-0 flex-col">
                  <span className="text-base leading-5 font-bold text-navy">{t("included")}</span>
                  <span className="truncate text-cap text-tx2">{service.name}</span>
                </div>
              </div>
              <button
                ref={toFront}
                type="button"
                onClick={() => flip(false)}
                aria-label={`${t("showFront")}: ${service.name}`}
                title={t("showFront")}
                className={FLIP_BUTTON}
              >
                <RotateCcw size={16} aria-hidden="true" />
              </button>
            </div>
            {shown.length > 0 ? (
              <ul className="m-0 -mr-2 flex min-h-0 flex-1 list-none flex-col gap-2 overflow-y-auto p-0 pr-2 [scrollbar-width:thin]">
                {shown.map((item) => (
                  <li key={item.id} className="flex items-start gap-2 text-sm leading-5 text-tx">
                    <CircleCheck size={16} aria-hidden="true" className="mt-0.5 flex-none text-ok" />
                    {item.title}
                  </li>
                ))}
                {more > 0 && <li className="pl-6 text-cap font-medium text-pri-h">{t("more", { count: more })}</li>}
              </ul>
            ) : (
              <p className="m-0 text-sm text-tx2">{t("noItems")}</p>
            )}
            <div className="mt-auto pt-1">{actions}</div>
          </div>
        </div>
      </div>
    </article>
  );
}
