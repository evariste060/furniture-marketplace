import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { CheckoutHeader } from "@/features/checkout/checkout-header";
import { CheckoutView } from "@/features/checkout/checkout-view";

export async function generateMetadata({ params }: PageProps<"/[locale]/checkout">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.checkout" });
  return { title: t("title"), robots: { index: false } };
}

/** /checkout (CheckoutContact, CheckoutDelivery, CheckoutPayment, CheckoutReview): the steps
 * run in the browser; the step is read from the URL at request time. */
export default function CheckoutPage() {
  return (
    <Suspense fallback={<CheckoutHeader step="contact" />}>
      <CheckoutView />
    </Suspense>
  );
}
