import { Star, StarHalf } from "lucide-react";
import { useTranslations } from "next-intl";
import { starFill } from "@/lib/catalogue";
import type { components } from "@/lib/api/schema";

type Rating = components["schemas"]["CatalogRating"];

/** The cards' rating row: five stars and "4.8 (120)" (`showText={false}`: stars only). A product without approved reviews shows
 * the design's no-rating state, an empty 16px row, so the cards still line up. */
export function RatingStars({ rating, size = 12, showText = true }: { rating: Rating; size?: number; showText?: boolean }) {
  const t = useTranslations("store.product");
  if (!rating.count || rating.average === null || rating.average === undefined) {
    return <span aria-hidden="true" className="block h-4" />;
  }
  const fill = starFill(rating.average);
  const average = rating.average.toFixed(1);
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-flex gap-px text-star" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((n) => (
          <span key={n} className="relative inline-flex">
            <Star size={size} className="text-bd2" fill="currentColor" strokeWidth={0} />
            {n <= fill ? (
              <Star size={size} className="absolute inset-0" fill="currentColor" strokeWidth={0} />
            ) : n - 0.5 === fill ? (
              <StarHalf size={size} className="absolute inset-0" fill="currentColor" strokeWidth={0} />
            ) : null}
          </span>
        ))}
      </span>
      <span className="sr-only">{t("ratingLabel", { average, count: rating.count })}</span>
      {showText && (
        <span className="text-cap text-mut" aria-hidden="true">
          {t("rating", { average, count: rating.count })}
        </span>
      )}
    </span>
  );
}
