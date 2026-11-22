"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes, House, Package, ShoppingCart, Store } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { CatalogScopeProvider, SELLER_SCOPE } from "@/features/admin/catalog-scope";
import { PanelShell, type PanelGroup } from "@/features/admin/panel-shell";
import { must } from "@/features/admin/ui";
import { browserApi } from "@/lib/api/client";
import { SellerStoreProvider, type ClientSellerStore } from "./store-context";

/** The seller dashboard's links (ADR-014 phase 4). Every page acts on the seller's own store; the
 * backend resolves the store again on every call. */
export const SELLER_NAV = [
  { group: "overview", items: [{ key: "dashboard", href: "/seller", Icon: House }] },
  { group: "sales", items: [{ key: "orders", href: "/seller/orders", Icon: ShoppingCart }] },
  {
    group: "catalogue",
    items: [
      { key: "products", href: "/seller/products", Icon: Package },
      { key: "inventory", href: "/seller/inventory", Icon: Boxes },
    ],
  },
  { group: "store", items: [{ key: "store", href: "/seller/store", Icon: Store }] },
] as const;

type SellerNavKey = (typeof SELLER_NAV)[number]["items"][number]["key"];

/** The link a path belongs to: the longest matching href. */
export function activeSellerNav(pathname: string): SellerNavKey | null {
  let best: { key: SellerNavKey; href: string } | null = null;
  for (const { items } of SELLER_NAV) {
    for (const item of items) {
      const match = item.href === "/seller" ? pathname === "/seller" : pathname === item.href || pathname.startsWith(`${item.href}/`);
      if (match && (!best || item.href.length > best.href.length)) best = item;
    }
  }
  return best?.key ?? null;
}

/** Seller orders waiting for this store's confirmation (the Orders badge). */
export const TO_CONFIRM_KEY = ["seller", "count", "orders-pending"] as const;

export function useToConfirm() {
  return useQuery({
    queryKey: TO_CONFIRM_KEY,
    queryFn: async () => (await must(browserApi.GET("/api/v1/seller/orders", { params: { query: { status: "pending", size: 1 } } }))).total,
  });
}

export function SellerShell({ store, fullName, children }: { store: ClientSellerStore; fullName: string; children: ReactNode }) {
  const t = useTranslations("admin.seller.shell");
  const pathname = usePathname();
  const active = activeSellerNav(pathname);
  const toConfirm = useToConfirm();
  const groups: PanelGroup[] = SELLER_NAV.map(({ group, items }) => ({
    key: group,
    label: t(`groups.${group}`),
    links: items.map(({ key, href, Icon }) => ({
      key,
      href,
      Icon,
      label: t(`nav.${key}`),
      count: key === "orders" ? toConfirm.data : undefined,
      active: key === active,
    })),
  }));
  return (
    <SellerStoreProvider store={store}>
      <CatalogScopeProvider scope={SELLER_SCOPE}>
        <PanelShell
          home="/seller"
          homeLabel={t("home")}
          panelLabel={t("panel")}
          navLabel={t("navLabel")}
          groups={groups}
          person={{ name: fullName || store.name, subtitle: `${t("owner")} · ${store.name}` }}
          cookiePath="/seller"
          // The public store page (/store/[slug]) is ADR-014 phase 5.
          topbar={{ start: <b className="truncate text-base font-semibold text-navy">{store.name}</b> }}
        >
          {children}
        </PanelShell>
      </CatalogScopeProvider>
    </SellerStoreProvider>
  );
}
