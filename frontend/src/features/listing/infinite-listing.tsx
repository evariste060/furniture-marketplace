"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef } from "react";
import { ListingCard } from "@/components/store/listing-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { ProductQuery } from "@/lib/api/catalogue";
import type { ListingView } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import type { components } from "@/lib/api/schema";

type ProductPage = components["schemas"]["Page_CatalogProduct_"];

/** Start loading the next page 400px before the end of the list comes into view. The large top
 * margin counts an end already scrolled past (a fling or the End key jumping over it into the
 * footer) as reached too. */
const PREFETCH_MARGIN = "100000px 0px 400px 0px";
const SKELETONS = 3;

/** The All Products grid: the server renders page 1, and the next pages of the same query
 * (filters and sort from the URL) are fetched from the API as the end of the list comes near, and
 * appended. A new filter or sort is a new `query`: the parent remounts this with a new key, so
 * results of different queries never mix and a late reply only fills its own (unused) cache entry.
 * Loaded pages stay in the query cache, so going back from a product shows them again. */
export function InfiniteListing({ query, initial, view }: { query: ProductQuery; initial: ProductPage; view: ListingView }) {
  const t = useTranslations("store.listing");
  const sentinel = useRef<HTMLDivElement>(null);
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchNextPageError } = useInfiniteQuery({
    queryKey: ["listing", query],
    queryFn: async ({ pageParam, signal }) => {
      const { data, error, response } = await browserApi.GET("/api/v1/catalog/products", {
        params: { query: { ...query, page: pageParam } },
        signal,
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    initialPageParam: 1,
    getNextPageParam: (last) => (last.items.length > 0 && last.page * last.size < last.total ? last.page + 1 : undefined),
    initialData: { pages: [initial], pageParams: [1] },
    // The pages are only ever appended; refetching them all would reorder what the visitor sees.
    staleTime: Infinity,
  });

  // A product can move between pages while the visitor scrolls (a sale ends, stock changes), so
  // it is shown once, where it first appeared.
  const products = useMemo(() => {
    const seen = new Set<string>();
    return (data?.pages ?? []).flatMap((page) => page.items).filter((p) => !seen.has(p.id) && seen.add(p.id));
  }, [data]);
  const total = data?.pages.at(-1)?.total ?? initial.total;

  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasNextPage || isFetchingNextPage || isFetchNextPageError) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) void fetchNextPage({ cancelRefetch: false });
      },
      { rootMargin: PREFETCH_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage]);

  const grid = cx("m-0 grid list-none grid-cols-1 gap-3 p-0 sm:gap-4", view === "grid" ? "sm:grid-cols-2 xl:grid-cols-3" : "");
  return (
    <>
      <ul className={grid}>
        {products.map((product, i) => (
          <li key={product.id}>
            <ListingCard product={product} preload={i < 2} />
          </li>
        ))}
        {isFetchingNextPage &&
          Array.from({ length: SKELETONS }, (_, i) => (
            <li key={`skeleton-${i}`} aria-hidden="true">
              <Skeleton className="h-[270px] rounded-xl" />
            </li>
          ))}
      </ul>
      <div ref={sentinel} className="flex flex-col items-center gap-3 py-2 text-center text-sm text-tx2">
        <p role="status" className={isFetchingNextPage ? "sr-only" : "m-0"}>
          {isFetchingNextPage ? t("loadingMore") : !hasNextPage && products.length > 0 ? t("allLoaded", { count: total }) : null}
        </p>
        {isFetchNextPageError && (
          <div role="alert" className="flex flex-col items-center gap-2">
            <p className="m-0 text-err-tx">{t("loadMoreError")}</p>
            <Button variant="outline" size="sm" onClick={() => void fetchNextPage()}>
              {t("retry")}
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
