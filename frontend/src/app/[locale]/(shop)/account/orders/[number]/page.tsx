import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { OrderDetailView } from "@/features/account/account-orders";
import { orderNumber as parseOrderNumber } from "@/lib/checkout";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/orders/[number]">): Promise<Metadata> {
  const { locale, number } = await params;
  const t = await getTranslations({ locale, namespace: "store.account" });
  return { title: t("orderNumber", { number: parseOrderNumber(number) ?? "" }), robots: { index: false } };
}

async function Detail({ params }: { params: PageProps<"/[locale]/account/orders/[number]">["params"] }) {
  const number = parseOrderNumber((await params).number);
  if (!number) notFound();
  return <OrderDetailView number={number} />;
}

/** /account/orders/[number] (OrderDetail.dc.html), read in the browser as the signed-in owner. */
export default function OrderDetailPage({ params }: PageProps<"/[locale]/account/orders/[number]">) {
  return (
    <Suspense fallback={null}>
      <Detail params={params} />
    </Suspense>
  );
}
