import { ShopFrame } from "@/components/store/shop-frame";
import { NotFoundView } from "@/features/errors/not-found-view";

/** NotFound.dc.html for notFound() outside the shop pages (e.g. an unknown order on the payment
 * page): drawn in the store frame so the visitor can find their way back. */
export default function LocaleNotFound() {
  return (
    <ShopFrame>
      <NotFoundView />
    </ShopFrame>
  );
}
