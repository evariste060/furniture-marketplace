import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import type { CatalogProduct } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import { AddToCartButton } from "./product-actions";
import { CARD_HOVER, CARD_IMAGE_ZOOM, CARD_TITLE_HOVER, cardData, STOCK } from "./product-card";
import { RatingStars } from "./rating-stars";
import { SoldBy } from "./sold-by";


/** The photo is sized by the card's inner width (a container query). Below 300px (the 3-column
 * desktop grid) a photo beside the text would squeeze the price onto two lines, so the photo sits
 * above the text at 160px. From 300px (phones, tablets) it sits beside the text at 144px, and from
 * 360px (2-column laptops) at 160px. */
const BODY = "flex flex-1 flex-col gap-3 @min-[300px]:flex-row @min-[300px]:items-center";
const PHOTO = "size-40 @min-[300px]:size-36 @min-[360px]:size-40";

/** ListingCard.dc.html: category, brand and deals listings. */
export function ListingCard({ product, preload = false }: { product: CatalogProduct; preload?: boolean }) {
  const t = useTranslations("store.product");
  const { variant, image, discount, stock, cart } = cardData(product);
  const href = `/product/${product.slug}`;
  return (
    <article className={cx("@container relative flex h-full flex-col gap-3 rounded-xl border border-bd bg-card px-3.5 pt-9 pb-3.5 text-tx", CARD_HOVER)}>
      <div className="absolute top-2.5 left-3 flex gap-1.5">
        {discount ? <Badge tone="err">{t("discountOff", { percent: discount })}</Badge> : null}
        <Badge tone={STOCK[stock].tone}>{t(STOCK[stock].key)}</Badge>
      </div>
      <div className={BODY}>
        <Link href={href} tabIndex={-1} aria-hidden="true" className="flex flex-none items-center justify-center">
          <ProductImage image={image} alt="" sizes={IMAGE_SIZES.listing} preload={preload} className={cx(PHOTO, "bg-card", CARD_IMAGE_ZOOM)} />
        </Link>
        <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
          {product.brand && <span className="t-over text-pri-fg">{product.brand.name}</span>}
          <Link href={href} className={cx("t-h4 text-tx hover:text-pri-fg", CARD_TITLE_HOVER)}>
            {product.name}
          </Link>
          {variant?.name && <span className="text-cap text-mut">{variant.name}</span>}
          <SoldBy store={product.store} />
          {product.rating.count > 0 && <RatingStars rating={product.rating} />}
          {variant && (
            <>
              <span className={cx("t-price mt-0.5", discount ? "text-err-fg" : "text-tx")}>{formatMoney(variant.price)}</span>
              {discount && variant.compare_at_price ? (
                <span className="text-cap text-mut line-through">
                  <span className="sr-only">{t("was")} </span>
                  {formatMoney(variant.compare_at_price)}
                </span>
              ) : null}
            </>
          )}
        </div>
      </div>
      <div className="flex gap-2">
        <Link href={href} className={buttonClasses({ size: "sm", className: "flex-1" })}>
          {t("viewDetails")}
          <span className="sr-only">: {product.name}</span>
        </Link>
        <AddToCartButton target={cart} variant="outline" className="flex-1" />
      </div>
    </article>
  );
}
