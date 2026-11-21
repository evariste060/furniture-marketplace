import { ShopFrame } from "@/components/store/shop-frame";

/** Storefront pages with the store header and footer. */
export default function ShopLayout({ children }: LayoutProps<"/[locale]">) {
  return <ShopFrame>{children}</ShopFrame>;
}
