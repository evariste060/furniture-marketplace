"use client";

import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ListingCard } from "@/components/store/listing-card";
import { WishlistButton } from "@/components/store/product-actions";
import { getPathname, Link } from "@/i18n/navigation";
import type { components } from "@/lib/api/schema";
import { IMAGE_SIZES } from "@/lib/images";
import { useToggleWishlist, useWishlist, WISHLIST_PAGE_SIZE } from "./use-wishlist";

type Item = components["schemas"]["WishlistItemResponse"];

/** /account/wishlist (no design of its own: the account layout and a ListingCard grid, as planned
 * for module 21). Each saved product is a listing card with View Details and Add to Cart, and the
 * heart in its corner removes it. A product no longer sold shows its name and photo with "No
 * longer available" and a Remove button. */
export function WishlistView() {
  const t = useTranslations("store.account");
  const tl = useTranslations("ui");
  const locale = useLocale();
  const params = useSearchParams();
  const page = Math.max(1, Math.min(10_000, Number.parseInt(params.get("page") ?? "1", 10) || 1));
  const wishlist = useWishlist(page);
  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="t-h1 text-head">{t("wishlistTitle")}</h1>
        {wishlist.data && wishlist.data.total > 0 && <p className="text-tx2">{t("wishlistCount", { count: wishlist.data.total })}</p>}
      </div>
      {wishlist.isPending ? (
        <div aria-busy="true" className="grid gap-4 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[270px] w-full rounded-xl" />
          ))}
        </div>
      ) : wishlist.isError ? (
        <Card padding={24} role="alert" className="flex flex-col items-start gap-3">
          <p className="text-tx2">{t("loadFailed")}</p>
          <Button variant="outline" size="sm" onClick={() => wishlist.refetch()}>
            {t("retry")}
          </Button>
        </Card>
      ) : wishlist.data.total === 0 ? (
        <Card padding={24} className="flex flex-col items-start gap-3">
          <p className="text-tx2">{t("wishlistEmpty")}</p>
          <Link href="/products" className={buttonClasses({ size: "sm" })}>
            {t("startShopping")}
          </Link>
        </Card>
      ) : (
        <>
          <ul className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2">
            {wishlist.data.items.map((item) =>
              item.available && item.product ? (
                <li key={item.product_id} className="relative">
                  <ListingCard product={item.product} />
                  <WishlistButton productId={item.product_id} productName={item.name} />
                </li>
              ) : (
                <li key={item.product_id}>
                  <Unavailable item={item} />
                </li>
              ),
            )}
          </ul>
          <Pagination
            total={wishlist.data.total}
            page={page}
            size={WISHLIST_PAGE_SIZE}
            hrefFor={(n) => getPathname({ href: { pathname: "/account/wishlist", query: n > 1 ? { page: String(n) } : {} }, locale })}
            labels={{ nav: tl("pagination"), previous: tl("previous"), next: tl("next"), page: (n) => tl("page", { n }) }}
          />
        </>
      )}
    </>
  );
}

/** A saved product that is no longer sold: its page is gone, so it is not linked. */
function Unavailable({ item }: { item: Item }) {
  const t = useTranslations("store.account");
  const tp = useTranslations("store.product");
  const toast = useToast();
  const toggle = useToggleWishlist();
  return (
    <article className="flex h-full items-center gap-4 rounded-xl border border-bd bg-card p-3.5">
      <ProductImage image={item.image} alt="" sizes={IMAGE_SIZES.thumb} className="size-20 flex-none bg-card opacity-60" />
      <div className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
        <b className="t-h4 text-tx2">{item.name}</b>
        <Badge tone="soft-neutral">{t("noLongerAvailable")}</Badge>
        <Button
          variant="outline"
          size="sm"
          className="mt-1"
          disabled={toggle.isPending}
          aria-label={t("removeItem", { name: item.name })}
          onClick={() =>
            toggle.mutate(
              { productId: item.product_id, save: false },
              {
                onSuccess: () => toast.show(tp("removed")),
                onError: () => toast.show(tp("wishlistFailed"), "error"),
              },
            )
          }
        >
          {t("remove")}
        </Button>
      </div>
    </article>
  );
}
