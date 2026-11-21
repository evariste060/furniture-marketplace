import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { CheckoutHeader } from "@/features/checkout/checkout-header";
import { PaymentStatusView } from "@/features/checkout/payment-status";
import { orderNumber as parseOrderNumber } from "@/lib/checkout";

export async function generateMetadata({ params }: PageProps<"/[locale]/checkout/pay/[orderNumber]">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.payment" });
  return { title: t("title"), robots: { index: false } };
}

async function Payment({ params }: { params: PageProps<"/[locale]/checkout/pay/[orderNumber]">["params"] }) {
  const number = parseOrderNumber((await params).orderNumber);
  if (!number) notFound();
  return <PaymentStatusView orderNumber={number} />;
}

/** /checkout/pay/[orderNumber] (PaymentWaiting, PaymentFailed): read in the browser, which holds
 * the guest's proof of the order (its phone) for this tab only. */
export default function PaymentPage({ params }: PageProps<"/[locale]/checkout/pay/[orderNumber]">) {
  return (
    <Suspense fallback={<CheckoutHeader step={null} />}>
      <Payment params={params} />
    </Suspense>
  );
}
