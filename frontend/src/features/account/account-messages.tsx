"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, MessageSquareText } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Conversation, type Thread } from "@/features/support/conversation";
import { SUPPORT_TONE } from "@/features/support/support";
import { getPathname, Link } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";

const PAGE_SIZE = 10;
const KEY = ["customer", "support"] as const;

function LoadFailed({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("store.account");
  return (
    <Card padding={24} role="alert" className="flex flex-col items-start gap-3">
      <p className="text-tx2">{t("loadFailed")}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {t("retry")}
      </Button>
    </Card>
  );
}

/** /account/messages: the customer's conversations with support, latest activity first. */
export function MessagesView() {
  const t = useTranslations("store.support");
  const tl = useTranslations("ui");
  const locale = useLocale();
  const params = useSearchParams();
  const page = Math.max(1, Math.min(10_000, Number.parseInt(params.get("page") ?? "1", 10) || 1));
  const list = useQuery({
    queryKey: [...KEY, "list", page],
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/support-threads", { params: { query: { page, size: PAGE_SIZE } } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    placeholderData: keepPreviousData,
  });
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="t-h1 text-navy">{t("mineTitle")}</h1>
          <p className="text-tx2">{t("mineText")}</p>
        </div>
        <Link href="/contact" className={buttonClasses({ size: "sm" })}>
          <MessageSquareText size={16} aria-hidden="true" />
          {t("newMessage")}
        </Link>
      </div>
      {list.isPending ? (
        [0, 1, 2].map((i) => <Skeleton key={i} className="h-[108px] w-full rounded-xl" />)
      ) : list.isError ? (
        <LoadFailed onRetry={() => list.refetch()} />
      ) : list.data.items.length === 0 ? (
        <Card padding={24} className="flex flex-col items-start gap-3">
          <p className="text-tx2">{t("mineEmpty")}</p>
          <Link href="/contact" className={buttonClasses({ size: "sm", variant: "outline" })}>
            {t("newMessage")}
          </Link>
        </Card>
      ) : (
        <>
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {list.data.items.map((thread) => (
              <li key={thread.id}>
                <Link
                  href={`/account/messages/${thread.reference}`}
                  className="group flex items-center gap-4 rounded-xl border border-bd bg-white p-5 text-tx no-underline hover:border-pri hover:text-tx max-sm:p-4"
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <b className="font-semibold">{thread.subject}</b>
                      <Badge tone="soft-neutral">{t(`topics.${thread.topic}.label`)}</Badge>
                      <Badge tone={SUPPORT_TONE[thread.status]}>{t(`status.${thread.status}`)}</Badge>
                    </span>
                    <span className="truncate text-sm text-tx2">
                      {thread.last_author === "staff" ? `${t("supportName")}: ` : `${t("you")}: `}
                      {thread.last_preview}
                    </span>
                    <span className="text-cap text-mut">
                      {thread.reference} · {formatDate(thread.last_message_at, "dateTime")}
                    </span>
                  </span>
                  <ChevronRight size={18} aria-hidden="true" className="flex-none text-tx2 group-hover:text-pri" />
                </Link>
              </li>
            ))}
          </ul>
          <Pagination
            total={list.data.total}
            page={page}
            size={PAGE_SIZE}
            hrefFor={(n) => getPathname({ href: { pathname: "/account/messages", query: n > 1 ? { page: String(n) } : {} }, locale })}
            labels={{ nav: tl("pagination"), previous: tl("previous"), next: tl("next"), page: (n) => tl("page", { n }) }}
          />
        </>
      )}
    </>
  );
}

/** /account/messages/[reference]: one conversation and a reply box. */
export function ConversationView({ reference }: { reference: string }) {
  const t = useTranslations("store.support");
  const client = useQueryClient();
  const query = useQuery({
    queryKey: [...KEY, "thread", reference],
    queryFn: async (): Promise<Thread> => {
      const { data, error, response } = await browserApi.GET("/api/v1/customers/me/support-threads/{reference}", { params: { path: { reference } } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });
  const back = (
    <Link href="/account/messages" className="flex items-center gap-1.5 self-start text-sm font-medium">
      <ArrowLeft size={16} aria-hidden="true" />
      {t("allMessages")}
    </Link>
  );
  if (query.isPending)
    return (
      <>
        {back}
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </>
    );
  if (query.isError) {
    const missing = query.error instanceof ApiError && query.error.status === 404;
    return (
      <>
        {back}
        {missing ? (
          <Card padding={24} role="alert" className="flex flex-col gap-2">
            <h1 className="t-h2">{t("notFound")}</h1>
            <p className="text-tx2">{t("notFoundText")}</p>
          </Card>
        ) : (
          <LoadFailed onRetry={() => query.refetch()} />
        )}
      </>
    );
  }
  return (
    <>
      {back}
      <Conversation
        thread={query.data}
        onReply={async (body) => {
          const { data, error, response } = await browserApi.POST("/api/v1/customers/me/support-threads/{reference}/messages", { params: { path: { reference } }, body: { body } });
          if (!data) throw ApiError.from(response.status, error);
          client.setQueryData([...KEY, "thread", reference], data);
          void client.invalidateQueries({ queryKey: [...KEY, "list"] });
        }}
      />
    </>
  );
}
