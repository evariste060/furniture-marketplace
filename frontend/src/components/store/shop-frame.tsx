import type { ReactNode } from "react";
import { MiniCartProvider } from "@/features/cart/mini-cart";
import { MenuStateProvider } from "./menu-state";
import { MobileTabBar } from "./mobile-tab-bar";
import { StoreFooter } from "./store-footer";
import { StoreHeader } from "./store-header";

/** The storefront frame: header, footer and the phone tab bar; "Add to Cart" opens the mini cart.
 * Used by the shop layout and by the not-found page outside it. */
export function ShopFrame({ children }: { children: ReactNode }) {
  return (
    <MenuStateProvider>
      <MiniCartProvider>
        <StoreHeader />
        <div className="pb-16 sm:pb-0">
          {children}
          <StoreFooter />
        </div>
        <MobileTabBar />
      </MiniCartProvider>
    </MenuStateProvider>
  );
}
