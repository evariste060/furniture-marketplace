"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LockKeyhole } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Link } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { Conversation, type Thread } from "./conversation";

/** /support/[reference]/[key]: a conversation opened by its private link (no account needed). The
 * link comes with the reference after sending and in every reply email. */
export function GuestConversationView({ reference, linkKey }: { reference: string; linkKey: string }) {
  const t = useTranslations("store.support");
  const client = useQueryClient();
  const key = ["support", "link", reference, linkKey];
  const query = useQuery({
    queryKey: key,
    queryFn: async (): Promise<Thread> => {
      const { data, error, response } = await browserApi.GET("/api/v1/support-messages/{reference}/{key}", { params: { path: { reference, key: linkKey } } });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });

  if (query.isPending)
    return (
      <>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </>
    );
  if (query.isError) {
    const missing = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 422);
    return (
      <div role="alert" className="flex flex-col items-start gap-3 rounded-xl border border-bd bg-white p-6">
        <h1 className="t-h2">{missing ? t("linkInvalid") : t("loadFailed")}</h1>
        <p className="m-0 text-tx2">{missing ? t("linkInvalidText") : t("loadFailedText")}</p>
        <Link href="/contact" className={buttonClasses({ size: "sm", variant: "outline" })}>
          {t("newMessage")}
        </Link>
      </div>
    );
  }
  return (
    <>
      <Conversation
        thread={query.data}
        onReply={async (body) => {
          const { data, error, response } = await browserApi.POST("/api/v1/support-messages/{reference}/{key}/messages", { params: { path: { reference, key: linkKey } }, body: { body } });
          if (!data) throw ApiError.from(response.status, error);
          client.setQueryData(key, data);
        }}
      />
      <p className="m-0 flex items-start gap-2 text-sm text-tx2">
        <LockKeyhole size={16} aria-hidden="true" className="mt-0.5 flex-none" />
        {t("privateLinkNote")}
      </p>
    </>
  );
}
