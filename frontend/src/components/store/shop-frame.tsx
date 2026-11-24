import type { ReactNode } from "react";
import { MiniCartProvider } from "@/features/cart/mini-cart";
import { BackToTop } from "./back-to-top";
import { MenuStateProvider } from "./menu-state";
import { MobileTabBar } from "./mobile-tab-bar";
import { StoreFooter } from "./store-footer";
import { StoreHeader } from "./store-header";

/** The storefront frame: header, footer, the phone tab bar and Back to top (SC-09); "Add to Cart"
 * opens the mini cart.
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
        <BackToTop />
      </MiniCartProvider>
    </MenuStateProvider>
  );
}
