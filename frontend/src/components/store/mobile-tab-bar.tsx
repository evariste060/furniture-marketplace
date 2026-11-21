"use client";

import { House, LayoutGrid, Search, ShoppingCart } from "lucide-react";
import { useTranslations } from "next-intl";
import { Suspense, type ReactNode } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { AccountTab } from "./account-menu";

const ITEM = "flex flex-1 flex-col items-center gap-0.5 border-0 bg-transparent p-0 text-cap font-medium cursor-pointer";

/** The MobileHome.dc.html bottom bar (≤700px): Home, Categories (all products, like the desktop "All Categories"), Search, Cart and
 * Account (a customer's account menu pops up above it). Product pages show their Add to Cart / Buy Now bar there instead (MobileProduct), and the cart its
 * total and checkout button (MobileCart). */
export function MobileTabBar() {
  // The current tab is known at request time on pages with a dynamic segment.
  return (
    <Suspense fallback={<TabBarView pathname={null} />}>
      <LiveTabBar />
    </Suspense>
  );
}

function LiveTabBar() {
  return <TabBarView pathname={usePathname()} />;
}

function TabBarView({ pathname }: { pathname: string | null }) {
  const t = useTranslations("store.tabs");
  if (pathname?.startsWith("/product/") || pathname === "/cart") return null;
  const tone = (active: boolean) => (active ? "text-pri" : "text-mut hover:text-tx");
  const item = (href: string, icon: ReactNode, label: string) => {
    const active = pathname !== null && (href === "/" ? pathname === "/" : pathname.startsWith(href));
    return (
      <Link href={href} aria-current={active ? "page" : undefined} className={cx(ITEM, tone(active))}>
        {icon}
        {label}
      </Link>
    );
  };
  return (
    <nav aria-label={t("label")} className="fixed inset-x-0 bottom-0 z-20 flex h-16 items-center border-t border-bd bg-white px-2 sm:hidden">
      {item("/", <House size={22} aria-hidden="true" />, t("home"))}
      {item("/products", <LayoutGrid size={22} aria-hidden="true" />, t("categories"))}
      {item("/search", <Search size={22} aria-hidden="true" />, t("search"))}
      {item("/cart", <ShoppingCart size={22} aria-hidden="true" />, t("cart"))}
      <AccountTab className={ITEM} tone={tone} pathname={pathname} />
    </nav>
  );
}
