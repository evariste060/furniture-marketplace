"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import type { ApiImage } from "@/lib/images";
import { AddToCartButton, BuyNowButton, type CartTarget } from "./product-actions";
import { RatingStars } from "./rating-stars";

/** How long each photo stays before the next one fades in. */
export const SHOWCASE_INTERVAL_MS = 3500;

export type ShowcaseProduct = {
  name: string;
  slug: string;
  /** Every photo of the product (its own, then its variants'), in order; may be empty. */
  images: ApiImage[];
  price: number | null;
  compareAtPrice: number | null;
  discount: number | null;
  detail: string | null;
  rating: components["schemas"]["CatalogRating"] | null;
  cart: CartTarget;
};

/** The large product on the left of a category spotlight: the one staff picked for the category
 * (else its best seller). Its photos fade in one after the other, pausing while the pointer or
 * keyboard focus is on the card, while the tab is hidden, and not at all with reduced motion
 * (the dots still switch photos). Under the photo: the name, the price and Buy Now, the most
 * prominent action, with Add to Cart beside it. */
export function SpotlightShowcase({ product }: { product: ShowcaseProduct }) {
  const t = useTranslations("store.home");
  const tp = useTranslations("store.product");
  const [shown, setShown] = useState(0);
  const [paused, setPaused] = useState(false);
  const count = product.images.length;
  const href = `/product/${product.slug}`;
  const root = useRef<HTMLDivElement>(null);

  // Pause while the pointer or keyboard focus is on the card (the rotation only, not a control).
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const pause = () => setPaused(true);
    const resume = () => setPaused(false);
    const blur = (e: FocusEvent) => {
      if (!el.contains(e.relatedTarget as Node | null)) setPaused(false);
    };
    el.addEventListener("pointerenter", pause);
    el.addEventListener("pointerleave", resume);
    el.addEventListener("focusin", pause);
    el.addEventListener("focusout", blur);
    return () => {
      el.removeEventListener("pointerenter", pause);
      el.removeEventListener("pointerleave", resume);
      el.removeEventListener("focusin", pause);
      el.removeEventListener("focusout", blur);
    };
  }, []);

  useEffect(() => {
    if (count < 2 || paused) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setShown((i) => (i + 1) % count);
    }, SHOWCASE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [count, paused]);

  const discounted = !!product.discount;
  return (
    <div ref={root} className="flex flex-col">
      <div className="relative">
        <Link href={href} tabIndex={-1} aria-hidden="true" className="group/photo relative block h-72 overflow-hidden bg-card sm:h-80 lg:h-[360px]">
          {count === 0 ? (
            <ProductImage image={null} alt="" sizes="1px" iconSize={64} className="absolute! inset-0 size-full bg-card" />
          ) : (
            product.images.map((image, i) => (
              <ProductImage
                key={image.url}
                image={image}
                alt=""
                sizes="(max-width: 700px) 100vw, 520px"
                preload={i === 0}
                iconSize={64}
                className={cx(
                  "absolute! inset-3 size-auto! bg-card transition-[opacity,scale] duration-700 ease-soft motion-reduce:transition-none sm:inset-4",
                  i === shown ? "scale-100 opacity-100" : "scale-[1.04] opacity-0",
                  "group-hover/photo:scale-[1.03] motion-reduce:scale-100!",
                )}
              />
            ))
          )}
        </Link>
        {discounted && (
          <Badge tone="err" className="absolute top-3 left-3" aria-hidden="true">
            {tp("discount", { percent: product.discount ?? 0 })}
          </Badge>
        )}
        {count > 1 && (
          <div className="absolute inset-x-0 bottom-3 flex justify-center gap-1.5">
            {product.images.map((image, i) => (
              <button
                key={image.url}
                type="button"
                aria-label={t("spotlightPhoto", { n: i + 1, count })}
                aria-current={i === shown ? "true" : undefined}
                onClick={() => setShown(i)}
                className={cx(
                  "h-2 cursor-pointer rounded-full border-0 p-0 transition-[width,background-color] duration-300 ease-soft",
                  i === shown ? "w-6 bg-pri" : "w-2 bg-bd2 hover:bg-mut",
                )}
              />
            ))}
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2 border-t border-bd p-4 sm:p-5">
        <Link href={href} className="line-clamp-2 text-h3 font-bold text-head hover:text-pri-h sm:text-h2">
          {product.name}
        </Link>
        {(!!product.detail || !!product.rating?.count) && (
          <span className="flex min-w-0 items-center gap-2 text-sm text-mut">
            {product.rating?.count ? (
              <span className="flex-none whitespace-nowrap">
                <RatingStars rating={product.rating} size={13} />
              </span>
            ) : null}
            {product.detail && <span className="min-w-0 truncate">{product.detail}</span>}
          </span>
        )}
        {product.price !== null && (
          <p className="m-0 flex flex-wrap items-baseline gap-x-2">
            <span className={cx("text-h2 font-extrabold sm:text-price-l", discounted ? "text-err-fg" : "text-pri-h")}>
              {discounted && <span className="sr-only">{tp("discount", { percent: product.discount ?? 0 })} </span>}
              {formatMoney(product.price)}
            </span>
            {discounted && product.compareAtPrice !== null && (
              <span className="text-sm text-mut line-through">
                <span className="sr-only">{tp("was")} </span>
                {formatMoney(product.compareAtPrice)}
              </span>
            )}
          </p>
        )}
        <div className="flex gap-2 pt-1">
          <BuyNowButton target={product.cart} className="min-w-0 flex-1 shadow-sh transition-[translate,box-shadow,background-color] duration-200 ease-soft hover:-translate-y-0.5 hover:shadow-sh2 motion-reduce:translate-y-0!" />
          <AddToCartButton target={product.cart} variant="outline" size="lg" iconOnly className="flex-none px-0! [&_svg]:size-5" />
        </div>
      </div>
    </div>
  );
}
