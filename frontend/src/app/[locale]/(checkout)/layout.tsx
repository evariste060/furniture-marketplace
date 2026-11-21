import { CheckoutFooter } from "@/features/checkout/checkout-header";
import { INFO_PAGES } from "@/lib/info-pages";

/** Checkout and payment status (CheckoutHeader.dc.html): no store header, menu or footer, so
 * nothing leads away from the order by accident. Each page draws the checkout header, since it
 * shows the current step. */
export default function CheckoutLayout({ children }: LayoutProps<"/[locale]">) {
  return (
    <div className="flex min-h-dvh flex-col bg-page">
      <div className="flex-1">{children}</div>
      <CheckoutFooter deliveryHref={INFO_PAGES.delivery} returnsHref={INFO_PAGES.returns} />
    </div>
  );
}
