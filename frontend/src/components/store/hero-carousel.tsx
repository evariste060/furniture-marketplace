"use client";

import { ArrowRight } from "lucide-react";
import Image from "next/image";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { buttonClasses } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { IMAGE_SIZES } from "@/lib/images";
import { AddToCartButton, type CartTarget } from "./product-actions";

export type HeroLink = { href: string; external: boolean };
export type HeroSlide = {
  id: string;
  overline: string | null;
  title: string;
  subtitle: string | null;
  cta: HeroLink | null;
  ctaLabel: string;
  image: { url: string; alt: string } | null;
  /** The product the banner links to (/product/<slug>), for Add to Cart; null for other links. */
  cart: CartTarget | null;
};

/** How long each banner stays, and how long it takes to leave. */
const SHOW_MS = 5_000;
const EXIT_MS = 450;

/** The home hero: the admin's active banners in their order, each shown for 5 seconds, then it
 * leaves (hero-exit) and the next comes in with the entrance (hero-pop, hero-rise; globals.css),
 * looping back to the first. The rotation pauses while the pointer or focus is on the hero, and
 * the dots jump to a banner. With one banner (or none: the copy from messages) nothing rotates.
 * With reduced motion banners change without animation. */
export function HeroCarousel({
  slides,
  viewDeals,
  points,
  labels,
}: {
  slides: HeroSlide[];
  viewDeals: string;
  /** The trust points under the desktop buttons, rendered on the server. */
  points: ReactNode;
  /** The carousel's name and each dot's "Show banner n of N", translated on the server. */
  labels: { banners: string; show: string[] };
}) {
  const [index, setIndex] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const rotating = slides.length > 1 && !hovered && !focused;
  const ref = useRef<HTMLElement>(null);

  // Pause while the pointer is on the hero or keyboard focus is inside it (reading, about to
  // click). A mouse click on a dot leaves focus there but is not keyboard focus, so rotation goes
  // on once the pointer leaves.
  useEffect(() => {
    const section = ref.current;
    if (!section || slides.length < 2) return;
    const enter = () => setHovered(true);
    const leave = () => setHovered(false);
    const focusIn = (event: FocusEvent) => {
      if (event.target instanceof Element && event.target.matches(":focus-visible")) setFocused(true);
    };
    const focusOut = (event: FocusEvent) => {
      if (!section.contains(event.relatedTarget as Node | null)) setFocused(false);
    };
    // A press means a pointer user, whatever focus that left behind.
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
  }, [slides.length]);

  useEffect(() => {
    if (!rotating) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let next: number | undefined;
    const show = window.setTimeout(() => {
      setLeaving(true);
      next = window.setTimeout(
        () => {
          setIndex((i) => (i + 1) % slides.length);
          setLeaving(false);
        },
        reduce ? 0 : EXIT_MS,
      );
    }, SHOW_MS);
    return () => {
      window.clearTimeout(show);
      window.clearTimeout(next);
      setLeaving(false);
    };
  }, [rotating, index, slides.length]);

  const slide = slides[index] ?? slides[0];
  if (!slide) return null;
  // key: a new banner's copy mounts afresh, so its entrance animation plays again; it leaves first.
  const copyClass = cx(leaving && "motion-safe:animate-hero-exit");

  return (
    <section
      ref={ref}
      aria-roledescription={slides.length > 1 ? "carousel" : undefined}
      aria-label={slides.length > 1 ? labels.banners : undefined}
      className="relative overflow-hidden bg-light"
    >
      <div className="wrap pt-4 pb-7 sm:pt-8 sm:pb-11">
        {/* One card holds the banner. It stays while banners change: the copy leaves and comes in,
         * and the banner images turn round the orbit. It lifts a little onto a deeper shadow while
         * hovered (not with reduced motion). */}
        <div
          className={cx(
            "overflow-hidden rounded-2xl border border-bd bg-white shadow-sh",
            "transition-[translate,box-shadow] duration-300 ease-soft hover:-translate-y-1 hover:shadow-sh2 motion-reduce:translate-y-0!",
          )}
        >
          {/* Desktop (Main.dc.html). The min height keeps the card the same size between banners. */}
          <div className="hidden min-h-[420px] flex-wrap items-center gap-10 p-8 sm:flex lg:px-12">
            <div key={slide.id} className={cx("flex max-w-[600px] flex-[1_1_440px] flex-col gap-5", copyClass)}>
              <Copy slide={slide} viewDeals={viewDeals} points={points} />
            </div>
            <div className="flex min-w-[280px] flex-[1_1_380px] flex-col items-center gap-5">
              <Orbit slides={slides} index={index} sizes={IMAGE_SIZES.hero} className="w-full max-w-[440px]" />
              {slide.cart && (
                <span key={slide.id} className={cx("flex motion-safe:animate-hero-pop motion-safe:[animation-delay:600ms]", copyClass)}>
                  <AddToCartButton target={slide.cart} size="lg" className="min-w-[220px]" />
                </span>
              )}
            </div>
          </div>
          {/* Mobile (MobileHome.dc.html). The min height fits a four-line title, so the page does not jump between banners. */}
          <div className="flex min-h-[236px] items-center gap-3 p-4 sm:hidden">
            <div key={slide.id} className={cx("flex min-w-0 flex-1 flex-col gap-2.5", copyClass)}>
              <MobileCopy slide={slide} />
            </div>
            <div className="flex w-[150px] flex-none flex-col items-center gap-2.5">
              <Orbit slides={slides} index={index} sizes="150px" className="w-full" />
              {slide.cart && (
                <span key={slide.id} className={cx("flex w-full motion-safe:animate-hero-pop motion-safe:[animation-delay:400ms]", copyClass)}>
                  <AddToCartButton target={slide.cart} className="w-full px-2" />
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
      {slides.length > 1 && (
        <div className="absolute inset-x-0 bottom-2 flex justify-center gap-2 sm:bottom-4">
          {slides.map((s, i) => (
            <button
              key={s.id}
              type="button"
              aria-label={labels.show[i]}
              aria-current={i === index ? "true" : undefined}
              onClick={() => {
                setLeaving(false);
                setIndex(i);
              }}
              className={cx(
                "h-2 cursor-pointer rounded-full border-0 p-0 transition-[width,background-color] duration-300",
                i === index ? "w-6 bg-pri" : "w-2 bg-pri/25 hover:bg-pri/50",
              )}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function Cta({ url, className, children }: { url: HeroLink; className: string; children: ReactNode }) {
  return url.external ? (
    <a href={url.href} className={className}>
      {children}
    </a>
  ) : (
    <Link href={url.href} className={className}>
      {children}
    </Link>
  );
}

/** A banner's copy on desktop: it pops in one piece after another. */
function Copy({ slide, viewDeals, points }: { slide: HeroSlide; viewDeals: string; points: ReactNode }) {
  const { overline, title, subtitle, cta, ctaLabel } = slide;
  return (
    <>
      {overline && <span className="t-over origin-left text-pri-h motion-safe:animate-hero-pop motion-safe:[animation-delay:80ms]">{overline}</span>}
      <h1 className="t-display origin-left text-navy motion-safe:animate-hero-pop motion-safe:[animation-delay:180ms]">{title}</h1>
      {subtitle && (
        <p className="max-w-[520px] origin-left text-lg text-tx2 motion-safe:animate-hero-pop motion-safe:[animation-delay:300ms]">{subtitle}</p>
      )}
      <div className="flex origin-left flex-wrap gap-3 motion-safe:animate-hero-pop motion-safe:[animation-delay:420ms]">
        {cta && (
          <Cta url={cta} className={buttonClasses({ size: "lg" })}>
            {ctaLabel}
            <ArrowRight size={18} aria-hidden="true" />
          </Cta>
        )}
        <Link href="/deals" className={buttonClasses({ variant: "outline", size: "lg" })}>
          {viewDeals}
        </Link>
      </div>
      <div className="flex origin-left flex-wrap gap-7 pt-3 motion-safe:animate-hero-pop motion-safe:[animation-delay:520ms]">{points}</div>
    </>
  );
}

/** A banner's copy on phones: overline, title and its link. */
function MobileCopy({ slide }: { slide: HeroSlide }) {
  const { overline, title, cta, ctaLabel } = slide;
  return (
    <>
      {overline && <span className="t-over origin-left text-xs text-pri-h motion-safe:animate-hero-pop motion-safe:[animation-delay:80ms]">{overline}</span>}
      <h1 className="m-0 origin-left text-[22px] leading-7 font-extrabold text-navy motion-safe:animate-hero-pop motion-safe:[animation-delay:180ms]">
        {title}
      </h1>
      {cta && (
        <span className="flex origin-left motion-safe:animate-hero-pop motion-safe:[animation-delay:300ms]">
          <Cta url={cta} className={buttonClasses({ size: "sm" })}>
            {ctaLabel}
            <ArrowRight size={16} aria-hidden="true" />
          </Cta>
        </span>
      )}
    </>
  );
}

/** The orbit's places, by how many images it holds: where each image box's left edge and vertical
 * centre sit (as % of the orbit) and its scale. The first place is the large one on the left; the
 * small ones follow clockwise in an arc round its right side (top, right, bottom). */
const SLOTS: Record<number, { left: string; top: string; scale: number }[]> = {
  1: [{ left: "22%", top: "50%", scale: 1 }],
  2: [
    { left: "0%", top: "50%", scale: 1 },
    { left: "52%", top: "50%", scale: 0.45 },
  ],
  3: [
    { left: "0%", top: "50%", scale: 1 },
    { left: "54%", top: "22%", scale: 0.45 },
    { left: "54%", top: "78%", scale: 0.45 },
  ],
  4: [
    { left: "0%", top: "50%", scale: 1 },
    { left: "42%", top: "17%", scale: 0.38 },
    { left: "62%", top: "50%", scale: 0.38 },
    { left: "42%", top: "83%", scale: 0.38 },
  ],
  5: [
    { left: "0%", top: "50%", scale: 1 },
    { left: "38%", top: "16%", scale: 0.38 },
    { left: "60%", top: "38%", scale: 0.38 },
    { left: "60%", top: "65%", scale: 0.38 },
    { left: "38%", top: "86%", scale: 0.38 },
  ],
};
const ORBIT_MAX = 5;

/** The banner images in an orbit of up to five: the shown banner's image is large on the left, the
 * others small in an arc on its right. When the banner changes they all move one place clockwise
 * (left → top → … → bottom → left): the large one shrinks away as the next, waiting at the bottom,
 * grows into its place, and each keeps floating gently. With more than five, the orbit shows the
 * one before, the shown one and the next three; at each change the one before leaves at the top
 * and the next new one comes in, and after the last banner it starts again from the first.
 * Banners without an image are left out and an image used twice appears once. With reduced motion
 * the images change places without moving. */
function Orbit({ slides, index, sizes, className }: { slides: HeroSlide[]; index: number; sizes: string; className: string }) {
  const seen = new Set<string>();
  const items = slides.flatMap((s, i) => {
    if (!s.image || seen.has(s.image.url)) return [];
    seen.add(s.image.url);
    return [{ id: s.id, image: s.image, banner: i }];
  });
  // The shown banner's image, or (a banner without one) the last image before it.
  const shown = items.filter((item) => item.banner <= index).at(-1) ?? items[0];
  if (!shown) return null;
  const count = items.length;
  const places = Math.min(count, ORBIT_MAX);
  const slots = SLOTS[places];
  const focus = items.indexOf(shown);
  // Which image (as an offset from the shown one) sits in each place. The next one waits in the
  // last place (bottom), so each change moves every image one place clockwise.
  const offsets = count > ORBIT_MAX ? [0, -1, 3, 2, 1] : slots.map((_, place) => -place);
  const placed = offsets.map((offset, place) => ({ item: items[(((focus + offset) % count) + count) % count], slot: slots[place] }));

  return (
    <div className={cx("relative aspect-[5/4] motion-safe:animate-hero-rise motion-safe:[animation-delay:600ms]", className)}>
      {placed.map(({ item, slot }) => {
        const big = slot.scale === 1;
        return (
          <div
            key={item.id}
            aria-hidden={big ? undefined : true}
            style={{ left: slot.left, top: slot.top, scale: slot.scale, opacity: big ? 1 : 0.75, zIndex: big ? 2 : 1 }}
            className="absolute aspect-square w-[56%] -translate-y-1/2 transition-[left,top,scale,opacity] duration-1000 ease-soft motion-reduce:transition-none"
          >
            {/* An image joining the orbit pops in where it appears. */}
            <div className="size-full motion-safe:animate-hero-pop">
              <div className="relative size-full motion-safe:animate-hero-float" style={{ animationDelay: `${1600 + item.banner * 700}ms` }}>
                <Image src={item.image.url} alt={big ? item.image.alt : ""} fill sizes={sizes} preload={big && index === 0} className="object-contain" />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
