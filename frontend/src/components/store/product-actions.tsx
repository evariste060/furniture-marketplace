"use client";

import { Heart, ShoppingCart } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonClasses } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useMiniCart } from "@/features/cart/mini-cart";
import { useAddToCart } from "@/features/cart/use-cart";
import { useSession } from "@/features/session/use-session";
import { loginForWishlist, useToggleWishlist, useWishlistIds } from "@/features/wishlist/use-wishlist";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api/errors";
import { cx } from "@/lib/cx";

/** The heart on ProductCard (`card`: on the image) and the product page (`inline`: beside the
 * buttons, or `bare` in the mobile header). Customers save and remove; a guest goes to sign in and
 * the product is saved afterwards; staff accounts have no wishlist. */
export function WishlistButton({
  productId,
  productName,
  placement = "card",
}: {
  productId: string;
  productName: string;
  placement?: "card" | "inline" | "bare";
}) {
  const t = useTranslations("store.product");
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { data: user } = useSession();
  const { data: ids } = useWishlistIds();
  const toggle = useToggleWishlist();
  const saved = ids?.product_ids.includes(productId) ?? false;

  function onClick() {
    if (!user) {
      router.push(loginForWishlist(`${pathname}${window.location.search}`, productId));
      return;
    }
    if (!user.is_customer) {
      toast.show(t("wishlistStaff"), "info");
      return;
    }
    toggle.mutate(
      { productId, save: !saved },
      {
        onSuccess: (data) => toast.show(t(data.in_wishlist ? "saved" : "removed")),
        onError: (error) =>
          toast.show(t(error instanceof ApiError && error.code === "wishlist_full" ? "wishlistFull" : "wishlistFailed"), "error"),
      },
    );
  }

  return (
    <button
      type="button"
      aria-label={`${t(saved ? "removeFromWishlist" : "addToWishlist")}: ${productName}`}
      aria-pressed={saved}
      onClick={onClick}
      className={cx(
        "flex flex-none cursor-pointer items-center justify-center bg-white",
        placement === "card" && "absolute top-2.5 right-2.5 size-8 rounded-full border border-bd",
        placement === "inline" && "size-11 rounded-lg border border-bd",
        placement === "bare" && "size-10 rounded-lg border-0",
        saved ? "text-err" : placement === "card" ? "text-mut" : "text-tx2",
      )}
    >
      <Heart size={placement === "card" ? 16 : placement === "inline" ? 18 : 22} aria-hidden="true" fill={saved ? "currentColor" : "none"} />
    </button>
  );
}

export type CartTarget = {
  productName: string;
  /** The variant the card shows (its name and price), which this button adds. */
  variantId: string | null;
  variantName: string | null;
  variantCount: number;
  inStock: boolean;
};

/** "Add to Cart" on the cards: adds the variant the card shows (the cheapest in stock) at once,
 * also for a product with several variants; its page offers the other colours and sizes. Out of
 * stock is a disabled button. The backend prices the line, and the mini cart drawer shows it. */
export function AddToCartButton({
  target,
  variant = "primary",
  size = "sm",
  iconOnly = false,
  className,
}: {
  target: CartTarget;
  variant?: "primary" | "outline";
  /** sm on the cards; the home hero uses lg beside its other buttons. */
  size?: "sm" | "lg";
  /** Only the cart icon (the home page's category spotlight cards); the label stays as its name. */
  iconOnly?: boolean;
  className?: string;
}) {
  const t = useTranslations("store.product");
  const toast = useToast();
  const add = useAddToCart();
  const miniCart = useMiniCart();
  const classes = buttonClasses({ variant, size, square: iconOnly, className });
  // With several variants the label names the one added, e.g. "Add to Cart: iPhone 15 (128GB · Black)".
  const name = target.variantCount > 1 && target.variantName ? `${target.productName} (${target.variantName})` : target.productName;
  const label = `${t("addToCart")}: ${name}`;

  if (!target.inStock || !target.variantId) {
    return (
      <button type="button" disabled className={classes} aria-label={iconOnly ? `${t("outOfStock")}: ${name}` : undefined} title={iconOnly ? t("outOfStock") : undefined}>
        {iconOnly ? <ShoppingCart size={16} aria-hidden="true" /> : t("outOfStock")}
      </button>
    );
  }
  const variantId = target.variantId;
  return (
    <button
      type="button"
      className={classes}
      aria-label={label}
      title={iconOnly ? t("addToCart") : undefined}
      disabled={add.isPending}
      onClick={() =>
        add.mutate(variantId, {
          onSuccess: () => {
            if (miniCart) miniCart.show(variantId);
            else
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
        })
      }
    >
      <ShoppingCart size={size === "lg" ? 18 : 16} aria-hidden="true" />
      {!iconOnly && t("addToCart")}
    </button>
  );
}

/** "Buy Now" (the home page's category spotlight): adds the shown variant, like Add to Cart, then
 * goes straight to checkout. Out of stock is a disabled button. */
export function BuyNowButton({ target, size = "lg", className }: { target: CartTarget; size?: "sm" | "lg"; className?: string }) {
  const t = useTranslations("store.product");
  const tPage = useTranslations("store.productPage");
  const toast = useToast();
  const router = useRouter();
  const add = useAddToCart();
  const name = target.variantCount > 1 && target.variantName ? `${target.productName} (${target.variantName})` : target.productName;
  const classes = buttonClasses({ size, className });
  if (!target.inStock || !target.variantId) {
    return (
      <button type="button" disabled className={classes}>
        {t("outOfStock")}
      </button>
    );
  }
  const variantId = target.variantId;
  return (
    <button
      type="button"
      className={classes}
      aria-label={`${tPage("buyNow")}: ${name}`}
      disabled={add.isPending}
      onClick={() =>
        add.mutate(variantId, {
          onSuccess: () => router.push("/checkout"),
          onError: (error) =>
            toast.show(t(error instanceof ApiError && /stock/.test(error.code) ? "notEnoughStock" : "addFailed"), "error"),
        })
      }
    >
      {tPage("buyNow")}
    </button>
  );
}
