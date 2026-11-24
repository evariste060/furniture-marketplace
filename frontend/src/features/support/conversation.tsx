"use client";

import { useMutation } from "@tanstack/react-query";
import { CircleAlert, Headset, Send } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/form";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import { bodyError, SUPPORT_LIMITS, SUPPORT_TONE } from "./support";

export type Thread = components["schemas"]["SupportThreadDetail"];

/** One support conversation as the customer sees it (My messages and the private link): the
 * subject and where it stands, every message (support's on the left, theirs on the right, the
 * latest support reply highlighted) and a reply box. */
export function Conversation({ thread, onReply }: { thread: Thread; onReply: (body: string) => Promise<void> }) {
  const t = useTranslations("store.support");
  const lastStaff = thread.messages.findLast((m) => m.author === "staff")?.id;
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="t-h1 text-head">{thread.subject}</h1>
          <Badge tone={SUPPORT_TONE[thread.status]}>{t(`status.${thread.status}`)}</Badge>
        </div>
        <p className="m-0 text-sm text-tx2">
          {t(`topics.${thread.topic}.label`)} · {thread.reference}
          {thread.order_number && ` · ${t("aboutOrder", { number: thread.order_number })}`} · {t("startedOn", { date: formatDate(thread.created_at, "date") })}
        </p>
      </div>
      {thread.status === "answered" && (
        <p role="status" className="m-0 flex items-center gap-2.5 rounded-xl bg-ok-bg px-4 py-3 text-sm font-medium text-ok-tx">
          <Headset size={18} aria-hidden="true" className="flex-none" />
          {t("answeredNote")}
        </p>
      )}
      <div className="flex flex-col gap-4 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
        <ol aria-label={t("conversation")} className="m-0 flex list-none flex-col gap-4 p-0">
          {thread.messages.map((m) => (
            <Bubble key={m.id} mine={m.author === "customer"} latest={m.id === lastStaff} who={m.author === "customer" ? t("you") : t("supportName")} at={m.created_at} body={m.body} />
          ))}
        </ol>
        {thread.status === "closed" && <p className="m-0 rounded-lg bg-page px-4 py-3 text-sm text-tx2">{t("closedNote")}</p>}
        <ReplyBox onSend={onReply} />
      </div>
    </>
  );
}

/** One message: the customer's on the right in light blue, support's on the left. */
function Bubble({ mine, latest, who, at, body }: { mine: boolean; latest: boolean; who: string; at: string; body: string }) {
  const t = useTranslations("store.support");
  return (
    <li className={cx("flex max-w-[85%] flex-col gap-1 max-sm:max-w-full", mine ? "items-end self-end" : "items-start self-start")}>
      <span className="flex items-center gap-1.5 text-cap text-tx2">
        {!mine && <Headset size={13} aria-hidden="true" className="text-pri-fg" />}
        <b className="font-semibold text-tx">{who}</b>· {formatDate(at, "dateTime")}
        {latest && <Badge tone="soft-ok">{t("latestReply")}</Badge>}
      </span>
      <p
        className={cx(
          "m-0 rounded-xl px-4 py-3 text-base break-words whitespace-pre-line text-tx",
          mine ? "rounded-tr-sm bg-light" : cx("rounded-tl-sm border bg-card", latest ? "border-ok shadow-sh" : "border-bd"),
        )}
      >
        {body}
      </p>
    </li>
  );
}

/** A reply box: checked like the backend (2 to 2,000 characters) and cleared once sent. */
function ReplyBox({ onSend }: { onSend: (body: string) => Promise<void> }) {
  const t = useTranslations("store.support");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string>();
  const send = useMutation({ mutationFn: onSend, onSuccess: () => setBody("") });
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = bodyError(body);
    setError(problem);
    if (problem) return event.currentTarget.querySelector<HTMLElement>("textarea")?.focus();
    send.mutate(body.trim());
  }
  const limited = send.error instanceof ApiError && send.error.status === 429;
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-3 border-t border-bd pt-4">
      <Field label={t("replyLabel")} error={error ? t(`errors.${error}` as "errors.required") : undefined}>
        {(p) => <Textarea {...p} value={body} onChange={(e) => setBody(e.target.value)} maxLength={SUPPORT_LIMITS.body} placeholder={t("replyPlaceholder")} />}
      </Field>
      {send.isError && (
        <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          <CircleAlert size={18} aria-hidden="true" className="flex-none" />
          {t(limited ? "limited" : "failed")}
        </div>
      )}
      <Button type="submit" disabled={send.isPending} className="self-end">
        <Send size={16} aria-hidden="true" />
        {t("sendReply")}
      </Button>
    </form>
  );
}
