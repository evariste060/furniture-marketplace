import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { CartView } from "@/features/cart/cart-view";
import { getPathname } from "@/i18n/navigation";

export async function generateMetadata({ params }: PageProps<"/[locale]/cart">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "store.cart" });
  return { title: t("title"), robots: { index: false } };
}

/** /cart (Cart.dc.html): the visitor's own cart, read in the browser through the proxy. */
export default async function CartPage() {
  const t = await getTranslations("store.cart");
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const home = getPathname({ href: "/", locale: await getLocale() });
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex flex-col gap-5 pt-4 pb-32 sm:pt-8 sm:pb-16">
        <Breadcrumb label={tu("breadcrumb")} items={[{ label: th("home"), href: home }, { label: t("crumb") }]} />
        <CartView />
      </div>
    </main>
  );
}
