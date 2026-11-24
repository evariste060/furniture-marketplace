"use client";

import { useTranslations } from "next-intl";
import { buttonClasses } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import type { MenuProduct } from "@/lib/catalogue";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import { AddToCartButton, type CartTarget } from "./product-actions";
import { RatingStars } from "./rating-stars";

type Rating = components["schemas"]["CatalogRating"];

/** What the hover card shows: the photo, name and price, the variant Add to Cart adds, and (the
 * spotlight's larger card) the shown variant's name, the rating and the discount. */
export type HoverProduct = MenuProduct & {
  cart: CartTarget;
  detail?: string | null;
  rating?: Rating | null;
  discount?: number | null;
};

const SIZES = {
  // The home hero's related products: a thumbnail, one line of name and a small button.
  sm: {
    card: "duration-300 hover:-translate-y-0.5 hover:border-pri/50 hover:shadow-sh2 focus-within:border-pri/50",
    slide: "duration-300",
    zoom: "duration-500 group-hover:scale-[1.04]",
    reveal: "duration-300",
    photo: "h-16 w-full sm:aspect-square sm:h-auto",
    frame: "",
    sizes: IMAGE_SIZES.thumb,
    icon: 20,
    text: "gap-0.5 px-2.5 pt-2 pb-2.5",
    lift: "group-hover:-translate-y-8 [@media(hover:hover)]:group-focus-within:-translate-y-8",
    name: "line-clamp-1 text-cap font-semibold",
    price: "text-xs font-bold whitespace-nowrap text-pri-h sm:text-cap lg:max-xl:text-xs",
    panel: "px-2.5 pb-2.5",
    button: "h-6! w-full gap-1 rounded-md px-2! text-xs! [&_svg]:size-3 [&_svg]:flex-none",
  },
  // The category spotlights: a card-sized photo, two lines of name, and the details over it.
  md: {
    card: "duration-500 hover:-translate-y-2 hover:border-transparent hover:shadow-lift focus-within:-translate-y-2 focus-within:border-transparent focus-within:shadow-lift",
    slide: "duration-500",
    zoom: "duration-700 group-hover:scale-[1.08]",
    // The details follow the lift: they come in 100ms later and leave at once.
    reveal: "duration-500 group-hover:delay-100 group-focus-within:delay-100",
    // From laptops up the row is as tall as the showcase beside it: the photo takes the room.
    photo: "h-24 w-full sm:h-28 lg:h-auto lg:min-h-28 lg:flex-1",
    frame: "lg:min-h-0 lg:flex-1",
    sizes: IMAGE_SIZES.listing,
    icon: 24,
    text: "gap-0.5 px-2.5 pt-1.5 pb-2.5",
    lift: "group-hover:-translate-y-[60px] [@media(hover:hover)]:group-focus-within:-translate-y-[60px]",
    name: "line-clamp-2 text-cap leading-4 font-semibold",
    price: "text-sm font-bold whitespace-nowrap",
    panel: "flex-col gap-1 bg-card px-2.5 pb-2.5",
  },
} as const;

/** A small product card with only its photo, name and price. Hovered (or with keyboard focus
 * inside) the card lifts onto a shadow (the spotlight's higher, slower, and without its border), the photo grows a little, the name and price slide up over
 * the photo's bottom edge and Add to Cart (with the variant and rating on the larger card) slides
 * in beneath them (on the spotlight card: View Details and an icon-only Add to Cart), inside the card, so nothing around it moves. Touch screens cannot hover: there
 * the details and button sit under the price all the time. */
export function HoverProductCard({ product, size = "sm" }: { product: HoverProduct; size?: keyof typeof SIZES }) {
  const t = useTranslations("store.product");
  const s = SIZES[size];
  const md = size === "md";
  const discounted = md && !!product.discount;
  return (
    <div className={cx("group relative flex h-full flex-col overflow-hidden rounded-xl border border-bd bg-card transition-[translate,box-shadow,border-color] ease-soft motion-reduce:translate-y-0!", s.card)}>
      <Link href={`/product/${product.slug}`} className="flex flex-1 flex-col text-tx hover:text-tx">
        <span className={cx("flex p-2 pb-0", s.frame)}>
          <ProductImage
            image={product.image}
            alt=""
            sizes={s.sizes}
            iconSize={s.icon}
            className={cx(s.photo, "bg-card transition-[scale] ease-soft motion-reduce:scale-100!", s.zoom)}
          />
        </span>
        <span
          className={cx(
            "relative z-10 flex flex-col bg-card",
            s.text,
            "transition-transform ease-soft motion-reduce:transition-none",
            s.slide,
            s.lift,
          )}
        >
          <span className={s.name}>{product.name}</span>
          {product.price !== null && (
            <span className={cx(s.price, md && (discounted ? "text-err-fg" : "text-tx"))}>
              {discounted && <span className="sr-only">{t("discount", { percent: product.discount ?? 0 })} </span>}
              {formatMoney(product.price)}
            </span>
          )}
        </span>
      </Link>
      {discounted && (
        <Badge tone="err" className="absolute top-2 left-2 z-20" aria-hidden="true">
          {t("discount", { percent: product.discount ?? 0 })}
        </Badge>
      )}
      <div
        className={cx(
          "z-20 flex",
          s.panel,
          "transition-[opacity,translate] ease-soft motion-reduce:transition-none",
          s.reveal,
          "[@media(hover:hover)]:pointer-events-none [@media(hover:hover)]:absolute [@media(hover:hover)]:inset-x-0 [@media(hover:hover)]:bottom-0 [@media(hover:hover)]:translate-y-full [@media(hover:hover)]:opacity-0",
          // Important: these must win over the hidden state above whatever order the build puts
          // the media-query rules in.
          "group-hover:pointer-events-auto! group-hover:translate-y-0! group-hover:opacity-100!",
          "group-focus-within:pointer-events-auto! group-focus-within:translate-y-0! group-focus-within:opacity-100!",
        )}
      >
        {md && (
          // One line, always there, so the slide is the same height on every card.
          <span className="flex h-4 items-center gap-2 overflow-hidden text-cap text-mut">
            {product.rating?.count ? (
              <span className="flex-none whitespace-nowrap">
                <RatingStars rating={product.rating} size={11} />
              </span>
            ) : null}
            {product.detail && <span className="min-w-0 truncate">{product.detail}</span>}
          </span>
        )}
        {md ? (
          <span className="flex gap-1.5">
            <Link
              href={`/product/${product.slug}`}
              aria-label={`${t("viewDetails")}: ${product.name}`}
              className={buttonClasses({ variant: "outline", size: "sm", className: "h-8! min-w-0 flex-1 px-2! text-xs!" })}
            >
              <span className="truncate">{t("viewDetails")}</span>
            </Link>
            <AddToCartButton target={product.cart} iconOnly className="size-8! flex-none px-0! [&_svg]:size-4" />
          </span>
        ) : (
          <AddToCartButton target={product.cart} className={SIZES.sm.button} />
        )}
      </div>
    </div>
  );
}
