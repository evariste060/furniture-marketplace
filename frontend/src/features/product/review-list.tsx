"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Check, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { REVIEW_PAGE_SIZE } from "@/lib/catalogue";
import { formatDate } from "@/lib/format";

type ReviewPage = components["schemas"]["Page_PublicReview_"];
type Review = components["schemas"]["PublicReview"];


function Stars({ rating }: { rating: number }) {
  const t = useTranslations("store.productPage");
  return (
    <span role="img" aria-label={t("starsOf", { rating })} className="inline-flex gap-px">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} size={14} fill="currentColor" strokeWidth={0} className={n <= rating ? "text-star" : "text-bd2"} aria-hidden="true" />
      ))}
    </span>
  );
}

function ReviewItem({ review }: { review: Review }) {
  const t = useTranslations("store.productPage");
  return (
    <article className="flex flex-col gap-2.5 border-b border-bd py-5">
      <div className="flex flex-wrap items-center gap-2.5">
        <Stars rating={review.rating} />
        {review.verified_purchase && (
          <Badge tone="soft-ok">
            <Check size={12} aria-hidden="true" />
            {t("verified")}
          </Badge>
        )}
      </div>
      {review.title && <h3 className="text-sm font-semibold">{review.title}</h3>}
      {/* Plain text from the API, never HTML; line breaks are kept. */}
      {review.body && <p className="whitespace-pre-line text-tx2">{review.body}</p>}
      <span className="text-sm">
        <b className="font-medium">{review.author_name}</b> <span className="text-mut">· {formatDate(review.created_at)}</span>
      </span>
    </article>
  );
}

/** Product.dc.html's review list: approved reviews, newest first; "Show more reviews" loads the
 * next page. The first page comes from the server. */
export function ReviewList({ slug, first }: { slug: string; first: ReviewPage }) {
  const t = useTranslations("store.productPage");
  const query = useInfiniteQuery({
    queryKey: ["reviews", slug],
    initialPageParam: 1,
    initialData: { pages: [first], pageParams: [1] },
    staleTime: 60_000,
    queryFn: async ({ pageParam }) => {
      const { data, error, response } = await browserApi.GET("/api/v1/catalog/products/{slug}/reviews", {
        params: { path: { slug }, query: { page: pageParam, size: REVIEW_PAGE_SIZE } },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    getNextPageParam: (last) => (last.page * last.size < last.total ? last.page + 1 : undefined),
  });
  const reviews = query.data.pages.flatMap((p) => p.items);
  const total = query.data.pages.at(-1)?.total ?? first.total;
  return (
    <div className="flex min-w-0 flex-[999_1_520px] flex-col">
      <p className="pb-2 text-sm text-mut" aria-live="polite">
        {t("showingReviews", { shown: reviews.length, total })}
      </p>
      {reviews.map((review) => (
        <ReviewItem key={review.id} review={review} />
      ))}
      {query.isError && (
        <p role="alert" className="mt-4 rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("reviewsError")}
        </p>
      )}
      {query.hasNextPage && (
        <div className="pt-5">
          <Button variant="outline" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {t("showMore")}
          </Button>
        </div>
      )}
    </div>
  );
}
