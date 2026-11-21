import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { OrderConfirmedView } from "@/features/orders/order-confirmed";
import { orderNumber as parseOrderNumber } from "@/lib/checkout";

export async function generateMetadata({ params }: PageProps<"/[locale]/order/[number]/confirmed">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.order" });
  return { title: t("metaTitle"), robots: { index: false } };
}

async function Confirmed({ params }: { params: PageProps<"/[locale]/order/[number]/confirmed">["params"] }) {
  const number = parseOrderNumber((await params).number);
  if (!number) notFound();
  return <OrderConfirmedView orderNumber={number} />;
}

/** /order/[number]/confirmed (OrderConfirmed.dc.html), read in the browser with the order's proof. */
export default function OrderConfirmedPage({ params }: PageProps<"/[locale]/order/[number]/confirmed">) {
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex max-w-[1000px] flex-col gap-6 pt-6 pb-16 sm:pt-10">
        <Suspense fallback={null}>
          <Confirmed params={params} />
        </Suspense>
      </div>
    </main>
  );
}
