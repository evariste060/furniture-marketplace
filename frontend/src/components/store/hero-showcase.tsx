"use client";

import { ArrowRight, Wrench } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { createElement, useEffect, useRef, useState, type ReactNode } from "react";
import { buttonClasses } from "@/components/ui/button";
import { ProductImage } from "@/components/ui/product-image";
import type { ServiceIconKey } from "@/features/services/service-icon";
import { ServiceImage } from "@/features/services/service-image";
import { Link } from "@/i18n/navigation";
import { categoryIcon } from "@/lib/category-icon";
import { ORBIT_MAX, RELATED_MAX, type MenuProduct } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import type { ApiImage } from "@/lib/images";
import heroBackground from "../../../public/brand/hero-background.jpg";
import { HoverProductCard } from "./hover-product-card";
import type { CartTarget } from "./product-actions";

/** One category in the showcase: its best seller turns round the orbit, the next best sellers are
 * shown beside it while it is in the spotlight. */
export type ShowcaseCategory = {
  id: string;
  name: string;
  slug: string;
  /** How many products the category has (for "View all (n)"). */
  total: number;
  featured: MenuProduct;
  /** With the variant each one's Add to Cart adds (the one its price is from). */
  related: (MenuProduct & { cart: CartTarget })[];
};

/** A technical service shown in the Services place: its card's photo (or icon placeholder) and name. */
export type ShowcaseService = { slug: string; name: string; icon: ServiceIconKey; image: ApiImage | null };

/** The technical services as one place on the orbit, like a main category (owner, 2026-11-17):
 * one image stands for them on the orbit, and four services come in beside the spotlight. */
export type ShowcaseServices = {
  kind: "services";
  id: "services";
  /** "Services", for the place's button. */
  name: string;
  services: ShowcaseService[];
};

type ShowcaseItem = ShowcaseCategory | ShowcaseServices;
const isServices = (item: ShowcaseItem): item is ShowcaseServices => "kind" in item && item.kind === "services";

/** The orbit turns every TURN_MS (owner, 2026-11-18: every 3 seconds): the category is shown for
 * SHOW_MS, then its copy and products leave (EXIT_MS) and the orbit turns to the next. */
export const TURN_MS = 3_000;
const EXIT_MS = 400;
const SHOW_MS = TURN_MS - EXIT_MS;

/** The orbit: its centre and radius as % of the stage's width, the spotlight's width, and the scale
 * of the other places. */
const CENTRE_X = 58;
const RADIUS = 36;
const BIG = 44;
const SMALL = 0.36;

/** The home hero as a product showcase (frontend phase "ui refinement"), full width over the store
 * photo (owner, 2026-11-18). The best seller of each top category sits on an orbit (no circle is
 * drawn: the products turn over the photo). The one at the left is the spotlight: large, with its
 * name, price and Shop Now beside it, and its category's next four best sellers on the right in a
 * straight 2×2. Every three seconds (TURN_MS) the orbit turns one place clockwise: the spotlight
 * moves on up and shrinks, the next category's product comes up from the bottom into the
 * spotlight and grows, and the copy and the four products change to that category. Rotation
 * pauses while the pointer or keyboard focus is on the hero; the dots under it jump to a category
 * (always moving clockwise). With reduced motion nothing moves: the places change without
 * animation. After the categories comes Services, one place like a main category: one image for
 * all services on the orbit, and in the spotlight "Explore services" with four services on the
 * right (owner, 2026-11-17). */
export function HeroShowcase({ categories, services = null, title }: { categories: ShowcaseCategory[]; services?: ShowcaseServices | null; title: string }) {
  const t = useTranslations("hero");
  const ts = useTranslations("store");
  const items: ShowcaseItem[] = [...categories.slice(0, ORBIT_MAX), ...(services?.services.length ? [services] : [])];
  const count = items.length;
  /** How many places the orbit has turned since the page opened; it only grows, so every move is
   * clockwise along the circle (also from the last category back to the first). */
  const [turn, setTurn] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const rotating = count > 1 && !hovered && !focused;
  const ref = useRef<HTMLElement>(null);
  const active = count ? turn % count : 0;

  // Pause while the pointer is on the hero or keyboard focus is inside it (as the banner carousel).
  useEffect(() => {
    const section = ref.current;
    if (!section || count < 2) return;
    const enter = () => setHovered(true);
    const leave = () => setHovered(false);
    const focusIn = (event: FocusEvent) => {
      if (event.target instanceof Element && event.target.matches(":focus-visible")) setFocused(true);
    };
    const focusOut = (event: FocusEvent) => {
      if (!section.contains(event.relatedTarget as Node | null)) setFocused(false);
    };
    const press = () => setFocused(false);
    section.addEventListener("pointerenter", enter);
    section.addEventListener("pointerleave", leave);
    section.addEventListener("focusin", focusIn);
    section.addEventListener("focusout", focusOut);
    section.addEventListener("pointerdown", press);
    return () => {
      section.removeEventListener("pointerenter", enter);
      section.removeEventListener("pointerleave", leave);
      section.removeEventListener("focusin", focusIn);
      section.removeEventListener("focusout", focusOut);
      section.removeEventListener("pointerdown", press);
    };
  }, [count]);

  // How long it still has before the next turn (null: all of it). A pause (hover, focus) keeps what
  // is left, so the turn and the active dot's progress (paused with it) pick up where they stopped.
  const remaining = useRef<number | null>(null);
  useEffect(() => {
    remaining.current = null;
  }, [turn]);

  useEffect(() => {
    if (!rotating) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const started = Date.now();
    const left = remaining.current ?? SHOW_MS;
    let next: number | undefined;
    const show = window.setTimeout(() => {
      setLeaving(true);
      next = window.setTimeout(
        () => {
          setTurn((n) => n + 1);
          setLeaving(false);
        },
        reduce ? 0 : EXIT_MS,
      );
    }, left);
    return () => {
      remaining.current = Math.max(0, left - (Date.now() - started));
      window.clearTimeout(show);
      window.clearTimeout(next);
      setLeaving(false);
    };
  }, [rotating, turn]);

  const current = items[active];
  if (!current) return null;
  const goTo = (index: number) => {
    setLeaving(false);
    setTurn((n) => n + ((index - (n % count) + count) % count));
  };
  const out = cx(leaving && "motion-safe:animate-hero-exit");
  // The four related tiles (owner, 2026-11-18) in a straight grid, the same size and spacing: they
  // come in together, fading and rising into place (tiles-in), and leave together before the next
  // category's (tile-out; both in globals.css).
  const tile = (key: string, children: ReactNode) => (
    <li key={key} className="flex">
      <div className={cx("flex w-full *:w-full", leaving ? "motion-safe:animate-tile-out" : "motion-safe:animate-tiles-in")}>{children}</div>
    </li>
  );
  // Phones and laptops: two by two; tablets: one row of four.
  const grid = "m-0 grid list-none auto-rows-fr grid-cols-2 gap-3 p-0 sm:grid-cols-4 lg:grid-cols-2";
  const service = isServices(current) ? current : null;
  const category = isServices(current) ? null : current;
  const price = category?.featured.price ?? null;

  return (
    <section ref={ref} aria-roledescription={count > 1 ? "carousel" : undefined} aria-label={t("showcase")} className="relative isolate overflow-hidden bg-light">
      <HeroBackdrop />
      <div className="wrap relative flex flex-col gap-5 pt-5 pb-3 sm:gap-6 sm:pt-10 lg:min-h-[440px] lg:flex-row lg:items-center lg:gap-10 lg:pt-12">
        {/* The spotlight: copy and orbit. */}
        <div className="flex min-w-0 flex-[1_1_0] items-center gap-3 sm:gap-6">
          {/* The copy. The page's heading stays; the spotlight's name, category, price and buttons
           * leave and come in with each category. */}
          <div className="flex min-w-0 flex-[1.25_1_0] flex-col gap-3 sm:max-w-[420px] sm:gap-5">
            <h1 className="t-over m-0 text-xs text-balance text-pri-h motion-safe:animate-hero-fade max-sm:tracking-[0.06em] sm:text-sm">{title}</h1>
            <div key={current.id} className={cx("flex flex-col gap-1.5 sm:gap-3", out)}>
              <p className="t-display m-0 line-clamp-2 origin-left text-balance text-navy motion-safe:animate-hero-fade motion-safe:[animation-delay:70ms] max-sm:text-[22px] max-sm:leading-7">
                {service ? t("servicesHeadline") : category?.featured.name}
              </p>
              {service ? (
                <Link
                  href="/services"
                  className="flex origin-left items-center gap-1.5 self-start text-cap font-medium text-tx2 hover:text-pri-h motion-safe:animate-hero-fade motion-safe:[animation-delay:140ms] sm:text-sm"
                >
                  <span aria-hidden="true" className="flex text-pri">
                    <Wrench size={14} />
                  </span>
                  {t("ourService")}
                </Link>
              ) : (
                <Link
                  href={`/category/${category?.slug}`}
                  className="flex origin-left items-center gap-1.5 self-start text-cap font-medium text-tx2 hover:text-pri-h motion-safe:animate-hero-fade motion-safe:[animation-delay:140ms] sm:text-sm"
                >
                  <span aria-hidden="true" className="flex text-pri">
                    {category && <CategoryIcon category={category} />}
                  </span>
                  {t("bestIn", { category: current.name })}
                </Link>
              )}
              {service && (
                <p className="m-0 line-clamp-2 origin-left text-sm text-tx2 motion-safe:animate-hero-fade motion-safe:[animation-delay:210ms] max-sm:hidden sm:text-base">
                  {ts("home.servicesText")}
                </p>
              )}
              {price !== null && (
                <p className="t-price-l m-0 origin-left text-pri-h motion-safe:animate-hero-fade motion-safe:[animation-delay:210ms] max-sm:text-lg sm:pt-1">{formatMoney(price)}</p>
              )}
            </div>
            <div key={`${current.id}-actions`} className={cx("flex origin-left flex-wrap gap-3 motion-safe:animate-hero-fade motion-safe:[animation-delay:280ms]", out)}>
              {service ? (
                <Link href="/services" className={cx(buttonClasses({ size: "md" }), "max-sm:h-9 max-sm:px-3.5 max-sm:text-sm")}>
                  {t("exploreServices")}
                  <ArrowRight size={16} aria-hidden="true" />
                </Link>
              ) : (
                <>
                  <Link href={`/product/${category?.featured.slug}`} className={cx(buttonClasses({ size: "md" }), "max-sm:h-9 max-sm:px-3.5 max-sm:text-sm")}>
                    {t("shopNow")}
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                  <Link href={`/category/${category?.slug}`} className={cx(buttonClasses({ variant: "outline", size: "md" }), "max-sm:hidden")}>
                    {t("explore", { category: current.name })}
                  </Link>
                </>
              )}
            </div>
          </div>
          <Orbit items={items} turn={turn} className="w-[150px] flex-none sm:w-auto sm:max-w-[420px] sm:flex-[1_1_0]" />
        </div>

        {/* The spotlight category's next four best sellers, straight over the photo. */}
        <div key={current.id} className="flex flex-col gap-3 lg:w-[310px] lg:flex-none xl:w-[330px]">
          <div className={cx("flex items-baseline justify-between gap-3 rounded-lg bg-white/80 px-3 py-2 backdrop-blur-sm motion-safe:animate-hero-fade motion-safe:[animation-delay:140ms]", out)}>
            <p className="m-0 text-sm font-semibold text-navy sm:text-base">{service ? ts("home.servicesTitle") : t("moreIn", { category: current.name })}</p>
            <Link href={service ? "/services" : `/category/${category?.slug}`} className="text-cap font-semibold whitespace-nowrap text-pri-h hover:text-pri">
              {t("viewAll", { count: service ? service.services.length : (category?.total ?? 0) })}
            </Link>
          </div>
          {service && <ul className={grid}>{service.services.slice(0, RELATED_MAX).map((s) => tile(s.slug, <ServiceTile service={s} />))}</ul>}
          {category && category.related.length > 0 && (
            <ul className={grid}>{category.related.slice(0, RELATED_MAX).map((product) => tile(product.id, <HoverProductCard product={product} />))}</ul>
          )}
        </div>
      </div>

      {count > 1 && (
        <div className="wrap relative flex justify-center gap-2 pb-4 sm:pb-6">
          {items.map((c, i) => (
            <button
              key={c.id}
              type="button"
              aria-label={t("showCategory", { category: c.name })}
              aria-current={i === active ? "true" : undefined}
              onClick={() => goTo(i)}
              className={cx(
                "relative h-2 cursor-pointer overflow-hidden rounded-full border-0 p-0 transition-[width,background-color] duration-300",
                i === active ? "w-8 bg-pri/25" : "w-2 bg-pri/25 hover:bg-pri/50",
              )}
            >
              {/* The active dot fills while its category is shown (solid with reduced motion). */}
              {i === active && (
                <span
                  key={turn}
                  className="absolute inset-0 origin-left rounded-full bg-pri motion-safe:animate-hero-progress"
                  style={{ animationDuration: `${SHOW_MS}ms`, animationPlayState: rotating ? "running" : "paused" }}
                />
              )}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** The category's icon (from its slug and name), drawn without declaring a component during render. */
function CategoryIcon({ category }: { category: { slug: string; name: string } }) {
  return createElement(categoryIcon(category), { size: 14, "aria-hidden": true });
}

/** A service beside the Services spotlight: its photo (or icon placeholder) and name, linking to its page. */
function ServiceTile({ service }: { service: ShowcaseService }) {
  return (
    <Link
      href={`/services/${service.slug}`}
      className="group flex h-full flex-col overflow-hidden rounded-xl border border-bd bg-white text-tx shadow-sh transition-shadow duration-200 hover:shadow-sh2 hover:text-tx"
    >
      <ServiceImage image={service.image} icon={service.icon} sizes="(max-width: 700px) 30vw, 130px" iconSize={26} className="aspect-[4/3] w-full" />
      <span className="p-2">
        <span className="line-clamp-2 text-cap font-medium group-hover:text-pri">{service.name}</span>
      </span>
    </Link>
  );
}

/** The one image standing for the services on the orbit: the brand's light tint with the
 * services' wrench (as on the Services entry of the All Categories menu). */
function ServicesImage({ big }: { big: boolean }) {
  return (
    <span className={cx("flex size-full items-center justify-center rounded-2xl border border-bd bg-linear-to-br from-light to-white text-pri", big ? "shadow-sh2" : "shadow-sh")}>
      <Wrench strokeWidth={1.5} className="size-[42%]" />
    </span>
  );
}

/** The hero's background (owner, 2026-11-18): public/brand/hero-background.jpg across the full
 * width. Since ADR-014 phase 6 it is a drawn living room, a placeholder until a FurniHub photo is
 * approved (the file name and size stay, so replacing it needs no code change). It is served
 * resized by next/image and loaded first with the hero, with a blurred preview while it comes. A
 * light white wash only where the copy is (the left; on phones the top, where the copy runs the
 * full width), so the room stays clearly visible behind the orbit and the products. */
function HeroBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      <Image src={heroBackground} alt="" fill preload placeholder="blur" sizes="100vw" className="object-cover object-center" />
      <div className="absolute inset-0 bg-linear-to-b from-white/85 via-white/55 to-white/10 sm:bg-linear-to-r sm:from-white/90 sm:from-10% sm:via-white/50 sm:via-35% sm:to-transparent sm:to-60%" />
    </div>
  );
}

/** The best sellers on an orbit (owner, 2026-11-18: no circle drawn, they turn over the photo).
 * Each sits at an angle that grows by one place per turn, so a move is a turn along the arc (the
 * transition interpolates the angles), clockwise: from the spotlight at the left (180°) up over the
 * top, down the right and back in from the bottom. The one at the left is large and in front; the
 * others are small and a little faded. */
function Orbit({ items, turn, className }: { items: ShowcaseItem[]; turn: number; className: string }) {
  const count = items.length;
  const step = 360 / count;
  const active = turn % count;
  return (
    <div aria-hidden="true" className={cx("@container relative aspect-square motion-safe:animate-hero-rise motion-safe:[animation-delay:300ms]", className)}>
      {items.map((c, i) => {
        const big = i === active;
        // At turn 0 the first one is at the left and the second waits at the last place, below it.
        const angle = 180 + step * (turn - i);
        return (
          <div
            key={c.id}
            data-orbit-item
            className="absolute transition-transform duration-[1100ms] ease-soft motion-reduce:transition-none"
            style={{
              left: `${CENTRE_X - BIG / 2}%`,
              top: `${50 - BIG / 2}%`,
              width: `${BIG}%`,
              height: `${BIG}%`,
              transform: `rotate(${angle}deg) translateX(${RADIUS}cqw) rotate(${-angle}deg)`,
              zIndex: big ? 2 : 1,
            }}
          >
            <div className="size-full transition-[scale,opacity] duration-[1100ms] ease-soft motion-reduce:transition-none" style={{ scale: big ? 1 : SMALL, opacity: big ? 1 : 0.9 }}>
              <div className="size-full motion-safe:animate-hero-float" style={{ animationDelay: `${i * 700}ms` }}>
                {isServices(c) ? (
                  <ServicesImage big={big} />
                ) : (
                  <ProductImage
                    image={c.featured.image}
                    alt=""
                    sizes="(max-width: 700px) 150px, 220px"
                    preload={i === 0}
                    iconSize={40}
                    className={cx("size-full rounded-2xl border border-bd bg-white", big ? "p-[6%] shadow-sh2" : "shadow-sh")}
                  />
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
