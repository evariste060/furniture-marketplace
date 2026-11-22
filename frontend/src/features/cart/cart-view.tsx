"use client";

import { SoldBy } from "@/components/store/sold-by";
import { ArrowLeft, ArrowRight, Heart, Lock, Minus, Plus, ShoppingCart, Tag, Trash2, TriangleAlert, Truck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { freeDelivery, useZones } from "@/features/checkout/use-zones";
import { useSession } from "@/features/session/use-session";
import { loginForWishlist, useToggleWishlist } from "@/features/wishlist/use-wishlist";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { ApiError, detailReason } from "@/lib/api/errors";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import {
  MAX_LINE_QUANTITY,
  splitLines,
  useAcceptPrices,
  useApplyCode,
  useCart,
  useRemoveCode,
  useRemoveLine,
  useSetQuantity,
  type Cart,
  type CartLine,
} from "./use-cart";

/** Cart.dc.html and MobileCart.dc.html. The backend prices every line; this page only shows what
 * it returns. Flagged lines (no longer sold, not enough stock) block checkout until fixed.
 * "Frequently bought together" is left out: recommendations are outside the MVP (ADR-002). */
export function CartView() {
  const t = useTranslations("store.cart");
  const { data: cart, isPending, isError, refetch } = useCart();

  if (isPending) return <CartSkeleton />;
  if (isError || !cart)
    return (
      <Card padding={24} className="flex flex-col items-start gap-3">
        <p className="text-tx2">{t("loadFailed")}</p>
        <Button variant="neutral" onClick={() => refetch()}>
          {t("retry")}
        </Button>
      </Card>
    );
  if (cart.lines.length === 0) return <EmptyCart />;
  return <FilledCart cart={cart} />;
}

function Heading({ count }: { count: number | null }) {
  const t = useTranslations("store.cart");
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-1.5">
        <h1 className="t-h1 text-navy">{t("title")}</h1>
        {count !== null && <p className="text-tx2">{t("count", { count })}</p>}
      </div>
      <Link href="/" className="flex items-center gap-1.5 text-sm font-medium">
        <ArrowLeft size={16} aria-hidden="true" />
        {t("continueShopping")}
      </Link>
    </div>
  );
}

function EmptyCart() {
  const t = useTranslations("store.cart");
  return (
    <>
      <Heading count={null} />
      <Card padding={32} className="flex flex-col items-center gap-3 text-center">
        <ShoppingCart size={40} strokeWidth={1.5} className="text-bd2" aria-hidden="true" />
        <h2 className="t-h3">{t("emptyTitle")}</h2>
        <p className="text-tx2">{t("emptyText")}</p>
        <Link href="/" className={buttonClasses()}>
          {t("startShopping")}
        </Link>
      </Card>
    </>
  );
}

function CartSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-5">
      <Skeleton className="h-9 w-64" />
      <div className="flex flex-wrap items-start gap-6">
        <Card padding={24} className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          {[0, 1].map((i) => (
            <div key={i} className="flex gap-5">
              <Skeleton className="size-24 flex-none" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-1/3" />
              </div>
            </div>
          ))}
        </Card>
        <Card padding={24} className="flex-[1_1_320px] sm:max-w-[400px]">
          <Skeleton className="h-40 w-full" />
        </Card>
      </div>
    </div>
  );
}

function FilledCart({ cart }: { cart: Cart }) {
  const t = useTranslations("store.cart");
  const { data: zones } = useZones();
  const { blocked } = splitLines(cart);
  const units = cart.lines.reduce((sum, line) => sum + line.quantity, 0);
  const free = freeDelivery(cart.subtotal_after_discount, zones);
  const canCheckout = blocked.length === 0 && cart.item_count > 0;

  return (
    <>
      <Heading count={units} />
      {(cart.has_price_changes || blocked.length > 0) && <ChangesBanner cart={cart} />}
      <div className="flex flex-wrap items-start gap-6">
        <section aria-label={t("itemsLabel")} className="flex min-w-0 flex-[999_1_560px] flex-col gap-3 sm:gap-0 sm:rounded-xl sm:border sm:border-bd sm:bg-white sm:p-6">
          <div className="hidden gap-5 border-b border-bd pb-3 text-cap font-semibold text-mut sm:flex">
            <span className="flex-1">{t("product")}</span>
            <span className="w-[120px]">{t("price")}</span>
            <span className="w-[120px]">{t("quantity")}</span>
            <span className="w-[120px] text-right">{t("total")}</span>
          </div>
          {cart.lines.map((line) => (
            <LineRow key={line.id} line={line} />
          ))}
          <DiscountCode cart={cart} />
        </section>
        <aside className="flex w-full flex-[1_1_320px] flex-col gap-3.5 sm:max-w-[400px]">
          <Card padding={24} className="flex flex-col gap-3.5 max-sm:p-4">
            <h2 className="t-h3 max-sm:sr-only">{t("summary")}</h2>
            <div className="kv">
              <span>{t("subtotal", { count: cart.item_count })}</span>
              <b className="font-medium">{formatMoney(cart.merchandise_subtotal)}</b>
            </div>
            {cart.discount?.applied && (
              <div className="kv">
                <span>{t("discount", { code: cart.discount.code })}</span>
                <b className="font-medium text-err">−{formatMoney(cart.discount_total)}</b>
              </div>
            )}
            <div className="kv">
              <span>{t("delivery")}</span>
              <span className="text-sm text-mut">{t("deliveryLater")}</span>
            </div>
            {free && (
              <div className="flex items-center gap-2 rounded-lg bg-ok-bg px-3 py-2.5 text-sm text-ok-tx">
                <Truck size={16} aria-hidden="true" />
                {t("freeDelivery")}
              </div>
            )}
            <hr className="hr" />
            <div className="flex items-center justify-between">
              <span className="t-h4">{t("total")}</span>
              <span className="t-price text-navy">{formatMoney(cart.subtotal_after_discount)}</span>
            </div>
            <p className="text-cap text-mut">{t("vatNote")}</p>
          </Card>
          <div className="max-sm:hidden">
            <CheckoutLink enabled={canCheckout} size="lg" />
          </div>
          {!canCheckout && <p className="text-cap text-err-tx">{t("fixFirst")}</p>}
          <p className="flex items-center justify-center gap-1.5 text-cap text-tx2 max-sm:hidden">
            <Lock size={14} className="text-ok" aria-hidden="true" />
            {t("secure")}
          </p>
          <SignInHint />
        </aside>
      </div>
      {/* MobileCart.dc.html: the total and the checkout button stay at the bottom of the screen. */}
      <div className="fixed inset-x-0 bottom-0 z-20 flex flex-col gap-1.5 border-t border-bd bg-white px-4 pt-3 pb-4 sm:hidden">
        <div className="flex items-center justify-between text-sm">
          <span className="text-tx2">{t("total")}</span>
          <b className="font-bold">{formatMoney(cart.subtotal_after_discount)}</b>
        </div>
        <CheckoutLink enabled={canCheckout} size="md" />
      </div>
    </>
  );
}

function CheckoutLink({ enabled, size }: { enabled: boolean; size: "md" | "lg" }) {
  const t = useTranslations("store.cart");
  const classes = buttonClasses({ size, block: true });
  const content = (
    <>
      {t("checkout")}
      <ArrowRight size={size === "lg" ? 18 : 16} aria-hidden="true" />
    </>
  );
  return enabled ? (
    <Link href="/checkout" className={classes}>
      {content}
    </Link>
  ) : (
    <button type="button" disabled className={classes}>
      {content}
    </button>
  );
}

function SignInHint() {
  const t = useTranslations("store.cart");
  const { data: user, isPending } = useSession();
  if (isPending || user) return null;
  return (
    <Card padding={16} className="flex flex-col gap-1">
      <b className="text-sm font-medium">{t("haveAccount")}</b>
      <span className="text-cap text-mut">{t("haveAccountText")}</span>
      <Link href={`/login?${new URLSearchParams({ returnTo: "/cart" })}`} className="text-sm font-medium">
        {t("signIn")}
      </Link>
    </Card>
  );
}

/** "Some items changed since you added them": what changed, line by line, from the backend's
 * previous prices and line statuses. */
function ChangesBanner({ cart }: { cart: Cart }) {
  const t = useTranslations("store.cart");
  const toast = useToast();
  const accept = useAcceptPrices();
  const sentences = cart.lines.flatMap((line) => {
    if (line.status === "available" && line.previous_unit_price != null && line.unit_price != null)
      return [t("changedPrice", { name: line.product_name, from: formatMoney(line.previous_unit_price), to: formatMoney(line.unit_price) })];
    if (line.status === "unavailable") return [t("changedGone", { name: line.product_name })];
    if (line.status === "insufficient_stock") return [t("changedStock", { name: line.product_name })];
    if (line.status === "amount_out_of_range") return [t("changedAmount", { name: line.product_name })];
    return [];
  });
  return (
    <div role="status" className="flex flex-wrap items-start gap-3.5 rounded-xl border border-warn bg-warn-bg p-4 text-warn-tx">
      <TriangleAlert size={22} className="flex-none" aria-hidden="true" />
      <div className="flex min-w-[200px] flex-1 flex-col gap-1">
        <b className="font-semibold">{t("changedTitle")}</b>
        <span className="text-sm">{sentences.join(" ")}</span>
      </div>
      {cart.has_price_changes && (
        <Button
          variant="dark"
          size="sm"
          disabled={accept.isPending}
          onClick={() => accept.mutate(undefined, { onError: () => toast.show(t("updateFailed"), "error") })}
        >
          {t("accept")}
        </Button>
      )}
    </div>
  );
}

function LineBadge({ line }: { line: CartLine }) {
  const t = useTranslations("store.cart");
  if (line.status === "unavailable") return <Badge tone="soft-err">{t("badgeGone")}</Badge>;
  if (line.status === "insufficient_stock") return <Badge tone="soft-err">{t("badgeStock")}</Badge>;
  if (line.status === "amount_out_of_range") return <Badge tone="soft-err">{t("badgeAmount")}</Badge>;
  if (line.previous_unit_price != null)
    return <Badge tone="soft-warn">{t("badgePrice", { price: formatMoney(line.previous_unit_price) })}</Badge>;
  return <Badge tone="soft-ok">{t("badgeInStock")}</Badge>;
}

function LineRow({ line }: { line: CartLine }) {
  const t = useTranslations("store.cart");
  const toast = useToast();
  const setQuantity = useSetQuantity();
  const remove = useRemoveLine();
  const save = useSaveForLater();
  const gone = line.status === "unavailable";
  const href = `/product/${line.product_slug}`;
  const busy = setQuantity.isPending || remove.isPending || save.pending;

  const change = (quantity: number) =>
    setQuantity.mutate(
      { lineId: line.id, quantity },
      {
        onError: (error) =>
          toast.show(t(error instanceof ApiError && error.code === "insufficient_stock" ? "notEnoughStock" : "updateFailed"), "error"),
      },
    );
  const onRemove = () => remove.mutate(line.id, { onError: () => toast.show(t("updateFailed"), "error") });

  return (
    <div
      className={cx(
        "flex items-start gap-3 rounded-xl border border-bd bg-white p-3",
        "sm:flex-wrap sm:items-center sm:gap-5 sm:rounded-none sm:border-0 sm:border-b sm:p-0 sm:py-5",
        gone && "opacity-60",
      )}
    >
      <Link href={href} aria-label={line.product_name} className="flex-none">
        <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-20 sm:size-24" iconSize={28} />
      </Link>
      <div className="flex min-w-0 flex-1 flex-col gap-1 sm:min-w-[200px]">
        <Link href={href} className="text-sm font-semibold text-tx sm:text-base">
          {line.product_name}
        </Link>
        <span className="text-cap text-mut sm:text-sm">{line.variant_name}</span>
        <SoldBy store={line.store} className="sm:text-sm" />
        <span>
          <LineBadge line={line} />
        </span>
        {line.unit_price !== null && <b className="font-semibold sm:hidden">{formatMoney(line.unit_price)}</b>}
        <div className="flex items-center justify-between gap-4 pt-1">
          <div className="flex items-center gap-4">
            <button
              type="button"
              disabled={busy}
              onClick={() => save.run(line)}
              className="hidden cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-cap font-medium text-mut sm:flex"
            >
              <Heart size={14} aria-hidden="true" />
              {t("saveForLater")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onRemove}
              aria-label={`${t("remove")}: ${line.product_name}`}
              className="hidden cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-cap font-medium text-err sm:flex"
            >
              <Trash2 size={14} aria-hidden="true" />
              {t("remove")}
            </button>
          </div>
          <div className="flex items-center gap-1 sm:hidden">
            {!gone && <Stepper line={line} disabled={busy} onChange={change} compact />}
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={onRemove}
            aria-label={`${t("remove")}: ${line.product_name}`}
            className="flex size-10 cursor-pointer items-center justify-center border-0 bg-transparent text-err sm:hidden"
          >
            <Trash2 size={18} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="hidden w-[120px] flex-col sm:flex">
        <span className="font-medium">{line.unit_price !== null ? formatMoney(line.unit_price) : "—"}</span>
        <span className="text-cap text-mut">{t("perItem")}</span>
      </div>
      <div className="hidden w-[120px] sm:block">{!gone && <Stepper line={line} disabled={busy} onChange={change} />}</div>
      <span className="hidden w-[120px] text-right font-semibold sm:block">
        {line.line_subtotal !== null ? formatMoney(line.line_subtotal) : "—"}
      </span>
    </div>
  );
}

function Stepper({
  line,
  disabled,
  onChange,
  compact = false,
}: {
  line: CartLine;
  disabled: boolean;
  onChange: (quantity: number) => void;
  compact?: boolean;
}) {
  const t = useTranslations("store.cart");
  const size = compact ? "w-[34px]" : "w-[38px]";
  return (
    <div
      role="group"
      aria-label={`${t("quantity")}: ${line.product_name}`}
      className={cx("flex items-center overflow-hidden rounded-lg border border-bd", compact ? "h-[34px]" : "h-[38px] w-[120px]")}
    >
      <button
        type="button"
        aria-label={t("decrease")}
        disabled={disabled || line.quantity <= 1}
        onClick={() => onChange(line.quantity - 1)}
        className={cx("flex h-full cursor-pointer items-center justify-center border-0 bg-white text-tx2 disabled:cursor-not-allowed disabled:opacity-45", size)}
      >
        <Minus size={14} aria-hidden="true" />
      </button>
      <span aria-live="polite" className={cx("text-center font-semibold", compact ? "w-8" : "flex-1 border-x border-bd leading-9")}>
        {line.quantity}
      </span>
      <button
        type="button"
        aria-label={t("increase")}
        disabled={disabled || line.quantity >= MAX_LINE_QUANTITY}
        onClick={() => onChange(line.quantity + 1)}
        className={cx("flex h-full cursor-pointer items-center justify-center border-0 bg-white text-tx2 disabled:cursor-not-allowed disabled:opacity-45", size)}
      >
        <Plus size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

/** "Save for later": a customer's line moves to the wishlist; a guest signs in first (the login
 * page then saves the product); staff accounts have no wishlist. */
function useSaveForLater() {
  const t = useTranslations("store.cart");
  const tp = useTranslations("store.product");
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { data: user } = useSession();
  const wishlist = useToggleWishlist();
  const remove = useRemoveLine();
  const run = (line: CartLine) => {
    if (!user) {
      router.push(loginForWishlist(pathname, line.product_id));
      return;
    }
    if (!user.is_customer) {
      toast.show(tp("wishlistStaff"), "info");
      return;
    }
    wishlist.mutate(
      { productId: line.product_id, save: true },
      {
        onSuccess: () => remove.mutate(line.id, { onSuccess: () => toast.show(t("savedForLater")) }),
        onError: (error) =>
          toast.show(tp(error instanceof ApiError && error.code === "wishlist_full" ? "wishlistFull" : "wishlistFailed"), "error"),
      },
    );
  };
  return { run, pending: wishlist.isPending || remove.isPending };
}

const REASONS = [
  "not_active",
  "not_started",
  "expired",
  "no_eligible_items",
  "minimum_not_met",
  "usage_limit_reached",
  "customer_limit_reached",
] as const;
type Reason = (typeof REASONS)[number];

function DiscountCode({ cart }: { cart: Cart }) {
  const t = useTranslations("store.cart");
  const toast = useToast();
  const apply = useApplyCode();
  const removeCode = useRemoveCode();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const current = cart.discount;
  const staleReason = current && !current.applied && current.reason ? current.reason : null;

  function reasonText(reason: string | null): string {
    return REASONS.includes(reason as Reason) ? t(`codeReason.${reason as Reason}`) : t("codeUnavailable");
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = code.trim().toUpperCase();
    if (!value) {
      setError(t("codeRequired"));
      return;
    }
    if (value.length > 40) {
      setError(t("codeUnavailable"));
      return;
    }
    setError(null);
    apply.mutate(value, {
      onSuccess: () => setCode(""),
      onError: (err) => {
        if (err instanceof ApiError && err.code === "promotion_not_applicable") setError(reasonText(detailReason(err)));
        else if (err instanceof ApiError && err.code === "promotion_unavailable") setError(t("codeUnavailable"));
        else if (err instanceof ApiError && err.code === "rate_limited") setError(t("codeTooMany"));
        else setError(t("updateFailed"));
      },
    });
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-bd bg-white p-4 sm:rounded-none sm:border-0 sm:p-0 sm:pt-5">
      {current && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Badge tone={current.applied ? "soft-ok" : "soft-err"}>
            <Tag size={12} aria-hidden="true" />
            {current.code}
          </Badge>
          <span className={current.applied ? "text-ok-tx" : "text-err-tx"}>
            {current.applied ? t("codeApplied", { name: current.name }) : reasonText(staleReason)}
          </span>
          <button
            type="button"
            disabled={removeCode.isPending}
            onClick={() => removeCode.mutate(undefined, { onError: () => toast.show(t("updateFailed"), "error") })}
            className="cursor-pointer border-0 bg-transparent p-0 text-sm font-medium text-pri"
          >
            {t("removeCode")}
          </button>
        </div>
      )}
      <form onSubmit={onSubmit} noValidate className="flex flex-wrap items-start gap-2 sm:gap-3">
        <Field label={t("discountCode")} error={error} className="min-w-0 flex-1 sm:w-[320px] sm:flex-none">
          {(control) => (
            <Input
              {...control}
              value={code}
              maxLength={40}
              autoComplete="off"
              autoCapitalize="characters"
              placeholder={t("codePlaceholder")}
              onChange={(event) => {
                setCode(event.target.value);
                if (error) setError(null);
              }}
            />
          )}
        </Field>
        <Button type="submit" variant="secondary" className="mt-[26px]" disabled={apply.isPending}>
          <Tag size={16} aria-hidden="true" />
          {t("apply")}
        </Button>
      </form>
    </div>
  );
}
