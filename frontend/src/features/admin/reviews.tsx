"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  BadgeCheck,
  Check,
  CheckCheck,
  ChevronRight,
  Clock,
  ExternalLink,
  EyeOff,
  Inbox,
  Info,
  MessageSquareText,
  Package,
  Receipt,
  ShieldCheck,
  Star,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import {
  Avatar,
  DrawerSection,
  Fact,
  FACTS,
  ListHeading,
  rowClass,
  StatusCards,
  Timeline,
  TimelineItem,
} from "./inbox";
import { timeAgo } from "./time";
import { ListFooter, LoadError, must, PageHeader, useListParams } from "./ui";

type Review = components["schemas"]["StaffReview"];
type Status = Review["status"];
type Tab = Status | "";

const STATUSES = ["pending", "approved", "rejected"] as const;
const TABS = [
  "",
  "pending",
  "approved",
  "rejected",
] as const satisfies readonly Tab[];
const PAGE_SIZE = 20;
/** Reviews.dc.html reject reasons; the chosen wording is stored as the staff-only reason. */
export const REJECT_REASONS = [
  "spam",
  "offensive",
  "offTopic",
  "personalInfo",
] as const;
type Reason = (typeof REJECT_REASONS)[number];
const STATUS_TONE: Record<Status, BadgeTone> = {
  pending: "soft-warn",
  approved: "soft-ok",
  rejected: "soft-err",
};
/** The status cards: an icon and its colours. */
const LOOK: Record<Tab, { Icon: LucideIcon; chip: string; ring: string }> = {
  "": { Icon: Star, chip: "bg-navy text-white", ring: "ring-navy" },
  pending: { Icon: Clock, chip: "bg-warn-bg text-warn-tx", ring: "ring-warn" },
  approved: { Icon: CheckCheck, chip: "bg-ok-bg text-ok-tx", ring: "ring-ok" },
  rejected: { Icon: EyeOff, chip: "bg-err-bg text-err-tx", ring: "ring-err" },
};

function Stars({ rating, size }: { rating: number; size: number }) {
  const t = useTranslations("admin.reviews");
  return (
    <span
      role="img"
      aria-label={t("stars", { count: rating })}
      className="inline-flex flex-none gap-px text-star"
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          size={size}
          aria-hidden="true"
          fill="currentColor"
          strokeWidth={0}
          className={n > rating ? "text-bd2" : undefined}
        />
      ))}
    </span>
  );
}

/** Reviews.dc.html as an inbox, like Service requests (layout owner 2026-11-18): status cards on
 * top (each one filters, with its count), the reviews in a table, and the chosen one in a drawer
 * with what the customer wrote, what it is about, the decision (approve, or pick a reason and
 * hide it) and its history. The status lives in the URL (?status=, "all" for every review;
 * pending by default). */
export function ReviewsView() {
  const t = useTranslations("admin.reviews");
  const tc = useTranslations("admin.common");
  const { get, page, set, hrefWith } = useListParams();
  const raw = get("status");
  const status: Tab =
    raw === "all"
      ? ""
      : (STATUSES as readonly string[]).includes(raw)
        ? (raw as Status)
        : "pending";
  const [openId, setOpenId] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const list = useQuery({
    queryKey: ["admin", "reviews", { status, page }],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/reviews", {
          params: {
            query: { status: status || undefined, page, size: PAGE_SIZE },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const counts = useQuery({
    queryKey: ["admin", "reviews", "counts"],
    queryFn: async () => {
      const totals = await Promise.all(
        TABS.map((s) =>
          must(
            browserApi.GET("/api/v1/staff/reviews", {
              params: { query: { status: s || undefined, size: 1 } },
            }),
          ),
        ),
      );
      return Object.fromEntries(
        TABS.map((s, i) => [s, totals[i]!.total]),
      ) as Record<Tab, number>;
    },
  });
  const items = list.data?.items ?? [];
  const opened = items.find((r) => r.id === openId) ?? null;

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />

      {/* Each card filters the list by status. */}
      <StatusCards
        label={t("tabsLabel")}
        className="grid-cols-2 lg:grid-cols-4"
        value={status}
        onChange={(s) => (
          setOpenId(null),
          set({ status: s === "pending" ? null : s || "all" })
        )}
        cards={TABS.map((s) => ({
          key: s,
          ...LOOK[s],
          label: t(`tiles.${s || "all"}`),
          hint: t(`hints.${s || "all"}`),
          count: counts.data?.[s],
          pulse: s === "pending" && (counts.data?.pending ?? 0) > 0,
        }))}
      />

      <section
        aria-label={t("listLabel")}
        className="overflow-hidden rounded-xl border border-bd bg-card shadow-sh"
      >
        <ListHeading
          Icon={LOOK[status].Icon}
          chip={LOOK[status].chip}
          title={t(`tiles.${status || "all"}`)}
          total={list.data?.total}
        />
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-4" />
        ) : !list.data ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
            <span
              aria-hidden="true"
              className={cx(
                "flex size-14 items-center justify-center rounded-full",
                status === "pending"
                  ? "bg-ok-bg text-ok-tx"
                  : "bg-light text-pri-h",
              )}
            >
              {status === "pending" ? (
                <CheckCheck size={26} />
              ) : (
                <MessageSquareText size={26} />
              )}
            </span>
            <p className="m-0 max-w-96 text-sm text-tx2">
              {t(`empty.${status || "all"}`)}
            </p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.reviewer")}</Th>
                <Th>{t("columns.review")}</Th>
                <Th>{t("columns.product")}</Th>
                <Th>{t("columns.sent")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{tc("actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <ReviewRow
                  key={r.id}
                  review={r}
                  now={now}
                  selected={r.id === openId}
                  onOpen={() => setOpenId(r.id)}
                />
              ))}
            </tbody>
          </Table>
        )}
        {list.data && list.data.total > PAGE_SIZE && (
          <ListFooter
            page={page}
            size={PAGE_SIZE}
            total={list.data.total}
            hrefFor={(n) => hrefWith({ page: n })}
          />
        )}
      </section>

      <Drawer
        open={opened !== null}
        onClose={() => setOpenId(null)}
        title={
          opened ? t("drawerTitle", { name: opened.author_name }) : t("title")
        }
        closeLabel={tc("close")}
        className="max-w-[min(520px,100%)]!"
      >
        {opened && <ReviewDetail key={opened.id} review={opened} now={now} />}
      </Drawer>
    </>
  );
}

function ReviewRow({
  review,
  now,
  selected,
  onOpen,
}: {
  review: Review;
  now: number;
  selected: boolean;
  onOpen: () => void;
}) {
  const t = useTranslations("admin.reviews");
  return (
    <tr className={rowClass(selected, review.status === "pending")}>
      <Td className="min-w-[170px]">
        <div className="flex items-center gap-3">
          <Avatar name={review.author_name} />
          <button
            type="button"
            onClick={onOpen}
            className="flex min-w-0 cursor-pointer flex-col border-0 bg-transparent p-0 text-left"
          >
            <b className="font-semibold text-pri-h hover:underline">
              {review.author_name}
            </b>
            <span className="inline-flex items-center gap-1 text-cap text-ok-tx">
              <BadgeCheck size={12} aria-hidden="true" />
              {t("verified")}
            </span>
          </button>
        </div>
      </Td>
      <Td className="max-w-[250px] min-w-[200px]">
        <span className="flex flex-col gap-0.5">
          <Stars rating={review.rating} size={13} />
          <span
            className={cx(
              "truncate text-sm",
              review.title ? "font-semibold text-tx" : "text-tx2 italic",
            )}
          >
            {review.title || t("noTitle")}
          </span>
          {review.body && (
            <span className="truncate text-cap text-tx2">{review.body}</span>
          )}
        </span>
      </Td>
      <Td className="max-w-[180px]">
        <span className="flex flex-col gap-0.5">
          <span className="truncate font-medium">{review.product_name}</span>
          <span className="font-mono text-cap whitespace-nowrap text-tx2">
            {review.order_number}
          </span>
        </span>
      </Td>
      <Td className="whitespace-nowrap">
        <span className="flex flex-col">
          <span className="font-medium">{timeAgo(review.created_at, now)}</span>
          <span className="text-cap text-tx2">
            {formatDate(review.created_at, "dateTime")}
          </span>
        </span>
      </Td>
      <Td>
        <Badge tone={STATUS_TONE[review.status]}>
          {t(`status.${review.status}`)}
        </Badge>
      </Td>
      <Td className="text-right">
        <Button
          variant="neutral"
          size="sm"
          square
          className="px-0!"
          onClick={onOpen}
          aria-label={t("open", { name: review.author_name })}
          title={t("openShort")}
        >
          <ChevronRight size={16} aria-hidden="true" />
        </Button>
      </Td>
    </tr>
  );
}

function ReviewDetail({ review, now }: { review: Review; now: number }) {
  const t = useTranslations("admin.reviews");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState<Reason | null>(null);
  const [error, setError] = useState<string | null>(null);
  const done = (message: string) => {
    toast.show(message);
    void client.invalidateQueries({ queryKey: ["admin", "reviews"] });
    void client.invalidateQueries({
      queryKey: ["admin", "count", "reviews-pending"],
    });
  };
  const approve = useMutation({
    mutationFn: () =>
      must(
        browserApi.POST("/api/v1/staff/reviews/{review_id}/approve", {
          params: { path: { review_id: review.id } },
        }),
      ),
    onSuccess: () => done(t("approved")),
    onError: () => toast.show(tc("saveError"), "error"),
  });
  const reject = useMutation({
    mutationFn: (why: Reason) =>
      must(
        browserApi.POST("/api/v1/staff/reviews/{review_id}/reject", {
          params: { path: { review_id: review.id } },
          body: { reason: t(`reasons.${why}`) },
        }),
      ),
    onSuccess: () => done(t("rejected")),
    onError: () => toast.show(tc("saveError"), "error"),
  });
  const busy = approve.isPending || reject.isPending;

  return (
    <div className="flex flex-col gap-5 p-5">
      {/* The rating and title, who wrote it, and where it stands. */}
      <div className="flex flex-col gap-3 rounded-xl border border-bd bg-linear-to-br from-light to-card p-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="flex size-14 flex-none flex-col items-center justify-center rounded-xl bg-warn-bg leading-none text-warn-tx"
          >
            <b className="t-h3 tabular-nums">{review.rating}</b>
            <span className="text-cap">/ 5</span>
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="flex flex-wrap items-center gap-2">
              <Stars rating={review.rating} size={16} />
              <Badge tone={STATUS_TONE[review.status]}>
                {t(`status.${review.status}`)}
              </Badge>
            </span>
            <b
              className={cx(
                "text-lg break-words",
                review.title
                  ? "font-bold text-head"
                  : "font-medium text-tx2 italic",
              )}
            >
              {review.title || t("noTitle")}
            </b>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-cap text-tx2">
              <span className="font-semibold text-tx">
                {review.author_name}
              </span>
              <span className="inline-flex items-center gap-1 text-ok-tx">
                <BadgeCheck size={13} aria-hidden="true" />
                {t("verified")}
              </span>
              <span>
                {t("writtenAgo", {
                  ago: timeAgo(review.created_at, now),
                  date: formatDate(review.created_at, "dateTime"),
                })}
              </span>
            </span>
          </div>
        </div>
      </div>

      {/* In the customer's words. */}
      <DrawerSection title={t("reviewHeading")}>
        {review.body ? (
          <figure className="m-0 flex gap-3 rounded-xl border border-bd bg-card p-4">
            <MessageSquareText
              size={18}
              aria-hidden="true"
              className="mt-0.5 flex-none text-star"
            />
            <blockquote className="m-0">
              <p className="m-0 break-words whitespace-pre-line text-tx">
                {review.body}
              </p>
            </blockquote>
          </figure>
        ) : (
          <p className="m-0 rounded-xl bg-page px-4 py-3 text-sm text-tx2 italic">
            {t("noBody")}
          </p>
        )}
      </DrawerSection>

      {/* The decision. */}
      <DrawerSection title={t("decisionTitle")}>
        {review.status !== "rejected" && (
          <div className="flex flex-col gap-2">
            <span
              id="review-reason"
              className="text-cap font-semibold text-tx2"
            >
              {review.status === "approved" ? t("hideWhy") : t("rejectWhy")}
            </span>
            <div
              role="group"
              aria-labelledby="review-reason"
              className="flex flex-wrap gap-2"
            >
              {REJECT_REASONS.map((r) => {
                const on = reason === r;
                return (
                  <button
                    key={r}
                    type="button"
                    aria-pressed={on}
                    onClick={() => (setReason(on ? null : r), setError(null))}
                    className={cx(
                      "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                      on
                        ? "border-err bg-err-bg text-err-tx"
                        : error
                          ? "border-err bg-card text-tx2"
                          : "border-bd bg-card text-tx2 hover:border-bd2 hover:text-tx",
                    )}
                  >
                    {on && <Check size={14} aria-hidden="true" />}
                    {t(`reasons.${r}`)}
                  </button>
                );
              })}
            </div>
            {error && (
              <span role="alert" className="text-cap text-err-tx">
                {error}
              </span>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {review.status !== "approved" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => approve.mutate()}
              className="gap-2"
            >
              <Check size={16} aria-hidden="true" />
              {t("approve")}
            </Button>
          )}
          {review.status !== "rejected" && (
            <Button
              variant="danger-outline"
              size="sm"
              disabled={busy}
              onClick={() => {
                if (!reason) return setError(t("chooseReason"));
                reject.mutate(reason);
              }}
              className="gap-2"
            >
              <EyeOff size={16} aria-hidden="true" />
              {review.status === "approved" ? t("hide") : t("reject")}
            </Button>
          )}
        </div>
        <p className="m-0 flex items-start gap-2 text-cap text-tx2">
          <Info size={14} aria-hidden="true" className="mt-px flex-none" />
          {t("ratingNote")}
        </p>
      </DrawerSection>

      {/* What it is about. */}
      <DrawerSection title={t("aboutHeading")}>
        <dl className={FACTS}>
          <Fact Icon={Package} label={t("product")}>
            <Link
              href={`/admin/products/${review.product_id}`}
              className="break-words"
            >
              {review.product_name}
            </Link>
            <a
              href={`/product/${review.product_slug}`}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-0.5 flex items-center gap-1 text-cap font-normal text-tx2 hover:text-pri-h"
            >
              <ExternalLink size={12} aria-hidden="true" />
              {t("viewOnStore")}
              <span className="sr-only"> {t("newTab")}</span>
            </a>
          </Fact>
          <Fact Icon={Receipt} label={t("order")}>
            {/* The order number only (SC-06: the admin has no order page). */}
            <span className="font-mono whitespace-nowrap">
              {review.order_number}
            </span>
          </Fact>
        </dl>
      </DrawerSection>

      {/* When it arrived, and who decided before and why. */}
      <DrawerSection title={t("moderationHeading")}>
        <Timeline>
          <TimelineItem
            Icon={Inbox}
            label={t("activity.received")}
            at={review.created_at}
          />
          {review.moderated_at && (
            <TimelineItem
              Icon={ShieldCheck}
              label={t("activity.moderated", {
                status: t(`status.${review.status}`),
              })}
              at={review.moderated_at}
              note={
                review.moderation_reason
                  ? t("reason", { reason: review.moderation_reason })
                  : null
              }
            />
          )}
        </Timeline>
      </DrawerSection>
    </div>
  );
}
