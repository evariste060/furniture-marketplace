import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { OrdersView } from "@/features/account/account-orders";

export async function generateMetadata({ params }: PageProps<"/[locale]/account/orders">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.account" });
  return { title: t("ordersTitle"), robots: { index: false } };
}

/** /account/orders (MyOrders.dc.html). */
export default function Page() {
  return (
    <Suspense fallback={null}>
      <OrdersView />
    </Suspense>
  );
}
