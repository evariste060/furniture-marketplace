"use client";

import { SoldBy } from "@/components/store/sold-by";
import { ArrowRight, CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { buttonClasses } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { ProductImage } from "@/components/ui/product-image";
import { Link } from "@/i18n/navigation";
import { IMAGE_SIZES } from "@/lib/images";
import { formatMoney } from "@/lib/format";
import { useCart } from "./use-cart";

/** MiniCart.dc.html: the drawer "Add to Cart" opens, with the line just added and the cart
 * subtotal. "You may also need" is left out: recommendations are outside the MVP (ADR-002). */
type MiniCart = { show: (variantId: string) => void };
const MiniCartContext = createContext<MiniCart | null>(null);

export function MiniCartProvider({ children }: { children: ReactNode }) {
  const [variantId, setVariantId] = useState<string | null>(null);
  const show = useCallback((id: string) => setVariantId(id), []);
  const value = useMemo(() => ({ show }), [show]);
  return (
    <MiniCartContext value={value}>
      {children}
      <MiniCartDrawer variantId={variantId} onClose={() => setVariantId(null)} />
    </MiniCartContext>
  );
}

/** The drawer, or null outside the store layout (callers then show a toast). */
export function useMiniCart(): MiniCart | null {
  return useContext(MiniCartContext);
}

function MiniCartDrawer({ variantId, onClose }: { variantId: string | null; onClose: () => void }) {
  const t = useTranslations("store.cart");
  const tui = useTranslations("ui");
  const { data: cart } = useCart(null, { enabled: variantId !== null });
  const line = cart?.lines.find((l) => l.variant_id === variantId);
  return (
    <Drawer
      open={variantId !== null}
      onClose={onClose}
      title={t("added")}
      closeLabel={tui("close")}
      icon={<CircleCheck size={22} className="flex-none text-ok" aria-hidden="true" />}
    >
      {line && (
        <div className="flex items-center gap-3.5 px-6 py-5">
          <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-20" iconSize={28} />
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <b className="font-semibold">{line.product_name}</b>
            <span className="text-cap text-mut">
              {line.variant_name} · {t("qty", { count: line.quantity })}
            </span>
            <SoldBy store={line.store} />
            {line.unit_price !== null && <span className="font-semibold text-head">{formatMoney(line.unit_price)}</span>}
          </span>
        </div>
      )}
      {cart && (
        <div className="flex items-center justify-between bg-page px-6 py-4">
          <span className="text-sm text-tx2">{t("cartSubtotal", { count: cart.item_count })}</span>
          <b className="font-semibold">{formatMoney(cart.merchandise_subtotal)}</b>
        </div>
      )}
      <div className="flex flex-col gap-2.5 px-6 py-5">
        <Link href="/cart" onClick={onClose} className={buttonClasses({ block: true })}>
          {t("viewCartCheckout")}
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <button type="button" onClick={onClose} className={buttonClasses({ variant: "outline", block: true })}>
          {t("continueShopping")}
        </button>
      </div>
    </Drawer>
  );
}
