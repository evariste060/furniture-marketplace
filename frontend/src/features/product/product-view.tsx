"use client";

import { Minus, Plus, ShoppingCart, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { WishlistButton } from "@/components/store/product-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProductImage } from "@/components/ui/product-image";
import { useToast } from "@/components/ui/toast";
import { useMiniCart } from "@/features/cart/mini-cart";
import { MAX_LINE_QUANTITY, useAddToCart } from "@/features/cart/use-cart";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { discountPercent, type CatalogVariant } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES, type ApiImage } from "@/lib/images";
import { initialVariant, optionGroups, optionValue, pickVariant, VARIANT_GROUP, type OptionGroup } from "@/lib/variant-options";

type Product = components["schemas"]["CatalogProductDetail"];

type ProductState = {
  product: Product;
  groups: OptionGroup[];
  variant: CatalogVariant | null;
  setVariant: (variant: CatalogVariant) => void;
  quantity: number;
  setQuantity: (quantity: number) => void;
};

const ProductContext = createContext<ProductState | null>(null);

function useProduct(): ProductState {
  const state = useContext(ProductContext);
  if (!state) throw new Error("useProduct needs <ProductProvider>");
  return state;
}

/** The chosen variant and quantity, shared by the gallery, the purchase panel and the mobile bar.
 * Prices and stock come from the API; the cart and the order are priced by the backend. */
export function ProductProvider({ product, children }: { product: Product; children: ReactNode }) {
  const [variant, setVariant] = useState(() => initialVariant(product.variants));
  const [quantity, setQuantity] = useState(1);
  const groups = useMemo(() => optionGroups(product.variants), [product.variants]);
  const value = useMemo(
    () => ({
      product,
      groups,
      variant,
      setVariant: (next: CatalogVariant) => {
        setVariant(next);
        setQuantity(1);
      },
      quantity,
      setQuantity,
    }),
    [product, groups, variant, quantity],
  );
  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}

// ---- gallery -------------------------------------------------------------------------------

/** Product.dc.html: the large image and five thumbnails; MobileProduct.dc.html: the full-width
 * image with dots. The chosen variant's own images come first. */
export function ProductGallery() {
  const t = useTranslations("store.productPage");
  const { product, variant } = useProduct();
  const images: ApiImage[] = useMemo(() => {
    const own = variant?.images ?? [];
    const urls = new Set(own.map((i) => i.url));
    return [...own, ...product.images.filter((i) => !urls.has(i.url))];
  }, [product.images, variant]);
  const [chosen, setChosen] = useState(0);
  const index = chosen < images.length ? chosen : 0;
  const current = images[index] ?? null;

  return (
    <div className="flex min-w-0 flex-col gap-4 max-sm:-mx-4">
      <ProductImage
        image={current}
        alt={current?.alt || product.name}
        sizes={IMAGE_SIZES.gallery}
        iconSize={64}
        preload
        className="h-[340px] w-full rounded-none bg-white sm:h-[480px] sm:rounded-2xl sm:border sm:border-bd"
      />
      {images.length > 1 && (
        <>
          <div role="group" aria-label={t("images")} className="hidden grid-cols-5 gap-3 sm:grid">
            {images.slice(0, 5).map((image, i) => (
              <button
                key={image.url}
                type="button"
                aria-label={t("image", { n: i + 1 })}
                aria-pressed={i === index}
                onClick={() => setChosen(i)}
                className={cx(
                  "cursor-pointer overflow-hidden rounded-img bg-white p-0",
                  i === index ? "border-2 border-pri" : "border border-bd",
                )}
              >
                <ProductImage image={image} alt="" sizes={IMAGE_SIZES.thumb} className="h-[92px] w-full" />
              </button>
            ))}
          </div>
          <div role="group" aria-label={t("images")} className="flex justify-center gap-1.5 sm:hidden">
            {images.slice(0, 8).map((image, i) => (
              <button
                key={image.url}
                type="button"
                aria-label={t("image", { n: i + 1 })}
                aria-pressed={i === index}
                onClick={() => setChosen(i)}
                className="flex h-6 cursor-pointer items-center border-0 bg-transparent px-0.5"
              >
                <span className={cx("block h-1.5 rounded-full", i === index ? "w-[18px] bg-pri" : "w-1.5 bg-bd2")} />
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---- purchase ------------------------------------------------------------------------------

/** "SKU: …" for the chosen variant, in the rating row. */
export function VariantSku() {
  const t = useTranslations("store.productPage");
  const { variant } = useProduct();
  return variant ? <span className="text-mut">{t("sku", { sku: variant.sku })}</span> : null;
}

function StockBadge({ variant }: { variant: CatalogVariant | null }) {
  const t = useTranslations("store.productPage");
  if (!variant || !variant.in_stock) return <Badge tone="soft-err">{t("outOfStock")}</Badge>;
  if (variant.stock_status === "low_stock") return <Badge tone="soft-warn">{t("lowStock")}</Badge>;
  return <Badge tone="soft-ok">{t("inStock")}</Badge>;
}

const GROUP_LABELS = {
  colour: "optionColour",
  color: "optionColour",
  storage: "optionStorage",
  ram: "optionRam",
  size: "optionSize",
  [VARIANT_GROUP]: "optionVariant",
} as const;

function groupLabel(key: string, t: ReturnType<typeof useTranslations<"store.productPage">>): string {
  const known = GROUP_LABELS[key.toLowerCase() as keyof typeof GROUP_LABELS];
  return known ? t(known) : key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, " ");
}

/** The options: a choice per group; a combination that is out of stock stays choosable (its
 * badge and disabled buttons say so). The price under a choice is what picking it would cost. */
function Options() {
  const t = useTranslations("store.productPage");
  const { product, groups, variant, setVariant } = useProduct();
  if (!variant || !groups.length) return null;
  return (
    <>
      {groups.map((group) => {
        const label = groupLabel(group.key, t);
        const chosen = optionValue(variant, group.key);
        return (
          <fieldset key={group.key} className="m-0 flex flex-col gap-2.5 border-0 p-0">
            <legend className="mb-2.5 p-0 text-sm font-medium text-tx2">
              {t("optionValue", { name: label })}
              <span className="text-tx">{chosen}</span>
            </legend>
            <div className="flex flex-wrap gap-2.5">
              {group.values.map((value) => {
                const target = pickVariant(product.variants, groups, variant, group.key, value);
                const on = value === chosen;
                const out = !target?.in_stock;
                return (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={on}
                    onClick={() => target && setVariant(target)}
                    className={cx(
                      "flex cursor-pointer flex-col items-start gap-0.5 rounded-[10px] text-left",
                      on ? "border-2 border-pri bg-light px-4 py-2.5" : "border border-bd bg-white px-[17px] py-[11px]",
                      out && !on && "bg-subtle",
                    )}
                  >
                    <b className={cx("font-semibold", out && !on && "text-mut")}>{value}</b>
                    {target && (
                      <span className={cx("text-cap", out ? "text-err-tx" : on ? "text-tx2" : "text-mut")}>
                        {out ? t("optionOut") : formatMoney(target.price)}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </fieldset>
        );
      })}
    </>
  );
}

function useBuy() {
  const t = useTranslations("store.product");
  const toast = useToast();
  const router = useRouter();
  const add = useAddToCart();
  const miniCart = useMiniCart();
  const { variant, quantity } = useProduct();
  const run = (then: "toast" | "checkout") => {
    if (!variant) return;
    add.mutate(
      { variantId: variant.id, quantity },
      {
        onSuccess: () => {
          if (then === "checkout") {
            router.push("/checkout");
            return;
          }
          if (miniCart) {
            miniCart.show(variant.id);
            return;
          }
          toast.show(
            <>
              {t("added")}.{" "}
              <Link href="/cart" className="font-semibold text-current underline">
                {t("viewCart")}
              </Link>
            </>,
          );
        },
        onError: (error) =>
          toast.show(t(error instanceof ApiError && /stock/.test(error.code) ? "notEnoughStock" : "addFailed"), "error"),
      },
    );
  };
  return { run, pending: add.isPending, can: Boolean(variant?.in_stock) };
}

function Quantity() {
  const t = useTranslations("store.productPage");
  const { quantity, setQuantity, variant } = useProduct();
  const disabled = !variant?.in_stock;
  const step = "flex h-full w-10 cursor-pointer items-center justify-center border-0 bg-white text-tx2 disabled:cursor-not-allowed disabled:text-bd2";
  return (
    <div role="group" aria-label={t("quantity")} className="flex h-11 overflow-hidden rounded-lg border border-bd">
      <button type="button" aria-label={t("decrease")} className={step} disabled={disabled || quantity <= 1} onClick={() => setQuantity(quantity - 1)}>
        <Minus size={16} aria-hidden="true" />
      </button>
      <span aria-live="polite" className="w-10 border-x border-bd text-center leading-[42px] font-semibold">
        {quantity}
      </span>
      <button
        type="button"
        aria-label={t("increase")}
        className={step}
        disabled={disabled || quantity >= MAX_LINE_QUANTITY}
        onClick={() => setQuantity(quantity + 1)}
      >
        <Plus size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

/** Price, stock, description, options and the buttons (Product.dc.html right column). */
export function PurchasePanel({ description }: { description: string | null }) {
  const t = useTranslations("store.productPage");
  const tp = useTranslations("store.product");
  const { product, variant } = useProduct();
  const buy = useBuy();
  const discount = variant ? discountPercent(variant) : null;
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        {variant && (
          <span className={cx("t-price-l max-sm:text-2xl", discount ? "text-err" : "text-navy")}>{formatMoney(variant.price)}</span>
        )}
        {variant && discount && (
          <>
            <span className="text-mut line-through">
              <span className="sr-only">{tp("was")} </span>
              {formatMoney(variant.compare_at_price ?? 0)}
            </span>
            <Badge tone="err">{tp("discountOff", { percent: discount })}</Badge>
          </>
        )}
        <StockBadge variant={variant} />
      </div>
      {description && <p className="text-tx2 max-sm:hidden">{description}</p>}
      <Options />
      <div className="flex flex-wrap items-center gap-3">
        <Quantity />
        <div className="hidden flex-[1_1_320px] flex-wrap gap-3 sm:flex">
          <Button className="flex-[1_1_160px]" disabled={!buy.can || buy.pending} onClick={() => buy.run("toast")}>
            <ShoppingCart size={18} aria-hidden="true" />
            {buy.can ? tp("addToCart") : t("outOfStock")}
          </Button>
          <Button variant="dark" className="flex-[1_1_160px]" disabled={!buy.can || buy.pending} onClick={() => buy.run("checkout")}>
            <Zap size={18} aria-hidden="true" />
            {t("buyNow")}
          </Button>
        </div>
        <span className="hidden sm:block">
          <WishlistButton productId={product.id} productName={product.name} placement="inline" />
        </span>
      </div>
    </>
  );
}

/** MobileProduct.dc.html: the wishlist heart in the page's top row on phones. */
export function MobileWishlist() {
  const { product } = useProduct();
  return <WishlistButton productId={product.id} productName={product.name} placement="bare" />;
}

/** MobileProduct.dc.html: Add to Cart and Buy Now fixed at the bottom on phones. */
export function MobileBuyBar() {
  const t = useTranslations("store.productPage");
  const tp = useTranslations("store.product");
  const buy = useBuy();
  return (
    <div className="fixed inset-x-0 bottom-0 z-20 flex h-16 items-center gap-2.5 border-t border-bd bg-white px-4 shadow-[0_-4px_16px_rgba(13,31,64,.06)] sm:hidden">
      <Button variant="outline" className="flex-1" disabled={!buy.can || buy.pending} onClick={() => buy.run("toast")}>
        <ShoppingCart size={18} aria-hidden="true" />
        {buy.can ? tp("addToCart") : t("outOfStock")}
      </Button>
      <Button className="flex-1" disabled={!buy.can || buy.pending} onClick={() => buy.run("checkout")}>
        {t("buyNow")}
      </Button>
    </div>
  );
}
