import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import { discountPercent, displayVariant, productStock, type CatalogProduct } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES, primaryImage } from "@/lib/images";
import { AddToCartButton, WishlistButton } from "./product-actions";
import { RatingStars } from "./rating-stars";
import { SoldBy } from "./sold-by";

/** The cards' hover and keyboard-focus lift: the card rises 6px onto a deep shadow with a faint
 * brand glow, its border tints blue, and it presses back down a little when clicked. Hover styles
 * apply only on devices that can hover (phones stay flat). With prefers-reduced-motion the card
 * does not move, but the shadow and border still fade in. `group` drives the image zoom and the
 * title colour inside. */
export const CARD_HOVER = [
  "group transition-[translate,box-shadow,border-color] duration-300 ease-soft",
  "hover:-translate-y-1.5 hover:border-pri/45 hover:shadow-lift active:-translate-y-0.5 active:duration-100",
  "has-[:focus-visible]:-translate-y-1.5 has-[:focus-visible]:border-pri has-[:focus-visible]:shadow-lift",
  "motion-reduce:translate-y-0! motion-reduce:transition-[box-shadow,border-color]",
].join(" ");
/** The product photo eases up to 108% while the card is hovered. */
export const CARD_IMAGE_ZOOM = "transition-transform duration-500 ease-soft group-hover:scale-[1.08] motion-reduce:scale-100!";
export const CARD_TITLE_HOVER = "transition-colors duration-300 group-hover:text-pri-fg";

/** The stock badge of the cards: tone and message key per stock level. */
export const STOCK = {
  in_stock: { tone: "ok", key: "inStock" },
  low_stock: { tone: "warn", key: "lowStock" },
  out_of_stock: { tone: "err", key: "outOfStock" },
} as const;

/** Everything the two cards need from a catalogue product. */
export function cardData(product: CatalogProduct) {
  const variant = displayVariant(product);
  return {
    variant,
    image: primaryImage(variant?.images.length ? variant.images : product.images),
    discount: variant ? discountPercent(variant) : null,
    stock: productStock(product),
    cart: {
      productName: product.name,
      variantId: variant?.id ?? null,
      variantName: variant?.name ?? null,
      variantCount: product.variants.length,
      // The shown variant is the cheapest in stock when any is (displayVariant).
      inStock: variant?.in_stock ?? false,
    },
  };
}

/** ProductCard.dc.html: home sections, search and related products. `isNew` shows the "New"
 * badge (New Arrivals); a discount badge takes precedence. `showButton` false hides Add to Cart
 * (the design's Bestselling and New Arrivals rows; the home page now shows it on every row).
 * `dense` (home page) tightens the space around the photo and between the lines, and keeps the
 * price right under the details: only Add to Cart is pinned to the bottom of the row.
 * `showStock` adds the stock badge (In Stock, Low Stock, Out of Stock) beside the discount or New
 * badge (the home page sections; owner, 2026-11-17). */
export function ProductCard({
  product,
  isNew = false,
  showButton = true,
  preload = false,
  dense = false,
  showStock = false,
}: {
  product: CatalogProduct;
  isNew?: boolean;
  showButton?: boolean;
  preload?: boolean;
  dense?: boolean;
  showStock?: boolean;
}) {
  const t = useTranslations("store.product");
  const { variant, image, discount, stock, cart } = cardData(product);
  const href = `/product/${product.slug}`;
  return (
    <article className={cx("relative flex h-full flex-col overflow-hidden rounded-xl border border-bd bg-card text-tx", CARD_HOVER)}>
      {/* A square photo as wide as the card allows, up to 176px (phones ~155px, 5-column desktop 176px). */}
      <Link href={href} tabIndex={-1} aria-hidden="true" className={cx("flex items-center justify-center bg-card px-2 pt-2", !dense && "sm:px-3 sm:pt-3")}>
        <ProductImage image={image} alt="" sizes={IMAGE_SIZES.card} preload={preload} className={cx("aspect-square w-full max-w-44 bg-card", CARD_IMAGE_ZOOM)} />
      </Link>
      {(discount || isNew || showStock) && (
        <span className="pointer-events-none absolute top-2.5 right-11 left-2.5 flex flex-wrap items-start gap-1">
          {discount ? <Badge tone="err">{t("discount", { percent: discount })}</Badge> : isNew ? <Badge tone="ok">{t("new")}</Badge> : null}
          {showStock && <Badge tone={STOCK[stock].tone}>{t(STOCK[stock].key)}</Badge>}
        </span>
      )}
      <WishlistButton productId={product.id} productName={product.name} />
      <div className={cx("flex flex-1 flex-col", dense ? "gap-1 px-3 pt-2 pb-3" : "gap-1.5 px-3.5 pt-3 pb-3.5")}>
        <Link href={href} className={cx("line-clamp-2 text-base leading-5 font-semibold text-tx hover:text-pri-fg", !dense && "min-h-10", CARD_TITLE_HOVER)}>
          {product.name}
        </Link>
        {variant?.name && <span className="text-cap text-mut">{variant.name}</span>}
        <SoldBy store={product.store} className="truncate" />
        {/* The empty no-rating row keeps the other cards' lines level; dense cards skip it so the
            price follows the details. */}
        {(!dense || product.rating.count > 0) && <RatingStars rating={product.rating} />}
        {variant && (
          <span className={cx("flex flex-wrap items-baseline gap-2", !dense && "mt-auto")}>
            <span className={cx("t-price", discount ? "text-err-fg" : "text-tx")}>{formatMoney(variant.price)}</span>
            {discount && variant.compare_at_price ? (
              <span className="text-cap text-mut line-through">
                <span className="sr-only">{t("was")} </span>
                {formatMoney(variant.compare_at_price)}
              </span>
            ) : null}
          </span>
        )}
        {showButton && <AddToCartButton target={cart} className={cx("w-full", dense ? "mt-auto" : "mt-1")} />}
      </div>
    </article>
  );
}
