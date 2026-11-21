"use client";

import { useTranslations } from "next-intl";
import { useId } from "react";
import { Select } from "@/components/ui/form";
import { useRouter } from "@/i18n/navigation";
import { listingSearch, SORTS, type ListingSort, type ListingState } from "@/lib/catalogue";
import { cx } from "@/lib/cx";

const LABELS: Record<
  ListingSort,
  "sortRelevance" | "sortPopular" | "sortPriceAsc" | "sortPriceDesc" | "sortNewest" | "sortTopRated"
> = {
  relevance: "sortRelevance",
  popular: "sortPopular",
  price_asc: "sortPriceAsc",
  price_desc: "sortPriceDesc",
  newest: "sortNewest",
  top_rated: "sortTopRated",
};

const SHORT: Partial<Record<ListingSort, "sortRelevanceShort" | "sortPopularShort">> = {
  relevance: "sortRelevanceShort",
  popular: "sortPopularShort",
};

/** The listing's sort: changing it reloads the list from page 1. Best match only with a search. */
export function SortSelect({ state, basePath, compact = false }: { state: ListingState; basePath: string; compact?: boolean }) {
  const t = useTranslations("store.listing");
  const router = useRouter();
  const id = useId();
  return (
    <div className={compact ? "flex flex-1" : "w-[220px] flex-none"}>
      <label htmlFor={id} className="sr-only">
        {t("sortLabel")}
      </label>
      <Select
        id={id}
        value={state.sort}
        onChange={(event) =>
          router.push(`${basePath}${listingSearch({ ...state, sort: event.target.value as ListingSort, page: 1 })}`)
        }
        className={cx(compact && "h-9 text-sm font-semibold")}
      >
        {SORTS.filter((s) => s !== "relevance" || state.q).map((s) => {
          const short = compact ? SHORT[s] : undefined;
          return (
            <option key={s} value={s}>
              {short ? t(short) : t(LABELS[s])}
            </option>
          );
        })}
      </Select>
    </div>
  );
}
