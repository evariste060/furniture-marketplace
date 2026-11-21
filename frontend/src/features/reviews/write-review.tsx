"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleCheck, Clock, Link2Off, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/form";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { IMAGE_SIZES } from "@/lib/images";

/** /review/[token] (WriteReview.dc.html): one delivered item, from a single-use link. The link,
 * the buyer and the limits are checked by the backend; the review waits for moderation. */

export const REVIEW_TITLE_MAX = 80;
export const REVIEW_BODY_MAX = 2000;
export const REVIEW_BODY_MIN = 20;

type Outcome = "thanks" | "expired" | "used" | "invalid";

export function WriteReview({ token }: { token: string }) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const info = useQuery({
    queryKey: ["review-link", token],
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET("/api/v1/reviews/{token}", { params: { path: { token } } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    staleTime: Infinity,
  });

  if (outcome) return <StateCard outcome={outcome} slug={info.data?.product.slug ?? null} />;
  if (info.isPending)
    return (
      <div aria-busy="true" className="flex flex-col gap-5">
        <Skeleton className="h-16 w-2/3" />
        <Skeleton className="h-[480px] w-full rounded-xl" />
      </div>
    );
  if (info.isError) {
    if (info.error instanceof ApiError && info.error.status === 404) return <StateCard outcome="invalid" slug={null} />;
    return <LoadFailed onRetry={() => info.refetch()} />;
  }
  if (info.data.status === "expired") return <StateCard outcome="expired" slug={info.data.product.slug} />;
  if (info.data.status === "used") return <StateCard outcome="used" slug={info.data.product.slug} />;
  return <ReviewForm token={token} info={info.data} onOutcome={setOutcome} />;
}

function LoadFailed({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("store.review");
  return (
    <Card padding={24} role="alert" className="flex flex-col items-start gap-3">
      <p className="text-tx2">{t("loadFailed")}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {t("retry")}
      </Button>
    </Card>
  );
}

const STATES: Record<Outcome, { icon: ReactNode; tone: string; link: "home" | "login" | "product" }> = {
  thanks: { icon: <CircleCheck size={24} aria-hidden="true" />, tone: "bg-ok-bg text-ok-tx", link: "home" },
  expired: { icon: <Clock size={24} aria-hidden="true" />, tone: "bg-warn-bg text-warn-tx", link: "login" },
  used: { icon: <Star size={24} aria-hidden="true" />, tone: "bg-light text-pri", link: "product" },
  invalid: { icon: <Link2Off size={24} aria-hidden="true" />, tone: "bg-subtle text-tx2", link: "login" },
};

/** The page's other states: thank you, expired, already reviewed (and an unknown link). */
function StateCard({ outcome, slug }: { outcome: Outcome; slug: string | null }) {
  const t = useTranslations("store.review");
  const state = STATES[outcome];
  const href = state.link === "home" ? "/" : state.link === "login" ? "/login?returnTo=/account/orders" : slug ? `/product/${slug}` : "/";
  const linkText = state.link === "product" && !slug ? t("continueShopping") : t(`${outcome}.link`);
  return (
    <Card padding={32} className="mx-auto flex w-full max-w-[480px] flex-col items-center gap-2 text-center max-sm:p-6">
      <span className={cx("flex size-12 items-center justify-center rounded-full", state.tone)}>{state.icon}</span>
      <h1 className="text-lg font-semibold">{t(`${outcome}.title`)}</h1>
      <p role={outcome === "thanks" ? "status" : undefined} className="text-sm text-tx2">
        {t(`${outcome}.text`)}
      </p>
      <Link href={href} className="text-sm font-medium">
        {linkText}
      </Link>
    </Card>
  );
}

type Info = components["schemas"]["ReviewLinkInfo"];

function ReviewForm({ token, info, onOutcome }: { token: string; info: Info; onOutcome: (outcome: Outcome) => void }) {
  const t = useTranslations("store.review");
  const form = useRef<HTMLFormElement>(null);
  const [rating, setRating] = useState(0);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [errors, setErrors] = useState<{ rating?: string; body?: string }>({});
  const [failure, setFailure] = useState<string | null>(null);
  const submit = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await browserApi.POST("/api/v1/reviews/{token}", {
        params: { path: { token } },
        body: { rating, title: title.trim() || null, body: body.trim() },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: () => onOutcome("thanks"),
    onError: (error) => {
      const code = error instanceof ApiError ? error.code : "";
      if (code === "already_reviewed") onOutcome("used");
      else if (code === "review_link_expired") onOutcome("expired");
      else if (code === "review_link_not_found") onOutcome("invalid");
      else setFailure(t(code === "rate_limited" ? "limited" : code === "product_unavailable" ? "productGone" : "submitFailed"));
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    if (!rating) found.rating = t("ratingRequired");
    if (body.trim().length < REVIEW_BODY_MIN) found.body = t("bodyShort", { min: REVIEW_BODY_MIN });
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length) {
      requestAnimationFrame(() => form.current?.querySelector<HTMLElement>("[aria-invalid=true]")?.focus());
      return;
    }
    submit.mutate();
  }

  const words = ["", t("words.1"), t("words.2"), t("words.3"), t("words.4"), t("words.5")];
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <h1 className="t-h1 text-navy">{t("title")}</h1>
        <p className="text-tx2">{t("text")}</p>
      </div>
      <form ref={form} onSubmit={onSubmit} noValidate aria-labelledby="review-product" className="flex flex-col gap-[18px] rounded-xl border border-bd bg-white p-6 max-sm:p-4">
        <div className="flex items-center gap-3.5">
          <ProductImage image={info.product.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-[72px] flex-none" iconSize={28} />
          <span className="flex flex-col gap-0.5">
            <b id="review-product" className="font-semibold">
              {info.product.name}
            </b>
            {info.variant_name && <span className="text-sm text-tx2">{info.variant_name}</span>}
          </span>
        </div>
        {failure && (
          <div role="alert" className="rounded-lg bg-err-bg px-3 py-2.5 text-sm text-err-tx">
            {failure}
          </div>
        )}
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0" aria-describedby={errors.rating ? "rating-error" : undefined}>
          <legend className="mb-2 p-0 text-sm font-medium">
            {t("rating")} <span className="text-err">*</span>
          </legend>
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <label key={n} className="cursor-pointer rounded-md has-focus-visible:outline-2 has-focus-visible:outline-pri">
                <input
                  type="radio"
                  name="rating"
                  value={n}
                  checked={rating === n}
                  onChange={() => (setRating(n), setErrors((e) => ({ ...e, rating: undefined })))}
                  aria-invalid={errors.rating && n === 1 ? true : undefined}
                  className="sr-only"
                />
                <span className="sr-only">{t("stars", { count: n })}</span>
                <Star size={32} aria-hidden="true" className={n <= rating ? "fill-star text-star" : "text-bd2"} />
              </label>
            ))}
            <span className="ml-2 text-sm font-medium" aria-live="polite">
              {words[rating]}
            </span>
          </div>
          {errors.rating && (
            <span id="rating-error" className="text-cap text-err">
              {errors.rating}
            </span>
          )}
        </fieldset>
        <Field
          label={
            <>
              {t("titleLabel")} <span className="font-normal text-tx2">{t("optional")}</span>
            </>
          }
        >
          {(c) => <Input {...c} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={REVIEW_TITLE_MAX} />}
        </Field>
        <Field
          label={
            <>
              {t("bodyLabel")} <span className="text-err">*</span>
            </>
          }
          help={t("bodyHelp", { min: REVIEW_BODY_MIN })}
          error={errors.body}
        >
          {(c) => <Textarea {...c} value={body} onChange={(e) => setBody(e.target.value)} maxLength={REVIEW_BODY_MAX} />}
        </Field>
        <div className="flex justify-end border-t border-bd pt-4">
          <Button type="submit" disabled={submit.isPending}>
            {t("submit")}
          </Button>
        </div>
      </form>
    </>
  );
}
