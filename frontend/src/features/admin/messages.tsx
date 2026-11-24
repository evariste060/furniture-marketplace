"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  CheckCheck,
  CircleAlert,
  CircleHelp,
  Clock,
  CreditCard,
  Headset,
  Inbox,
  Lock,
  Mail,
  Package,
  Phone,
  RotateCcw,
  Send,
  ShieldCheck,
  Smartphone,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import {
  bodyError,
  SUPPORT_LIMITS,
  SUPPORT_STATUSES,
  SUPPORT_TONE,
  type SupportStatus,
  type SupportTopic,
} from "@/features/support/support";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { initials } from "@/lib/auth";
import { whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import { formatDate, formatPhone } from "@/lib/format";
import { useStaffAccess } from "./access";
import {
  Avatar,
  CopyChip,
  DrawerHeader,
  DrawerSection,
  ListHeading,
  RowActions,
  rowClass,
  StatusCards,
} from "./inbox";
import { timeAgo } from "./time";
import {
  FilterBar,
  ListFooter,
  LoadError,
  must,
  PageHeader,
  SearchBox,
  useListParams,
} from "./ui";

type Summary = components["schemas"]["StaffSupportThreadSummary"];
type Detail = components["schemas"]["StaffSupportThreadDetail"];
type Tab = SupportStatus | "";

const PAGE_SIZE = 20;
const TABS = [
  "",
  "open",
  "answered",
  "closed",
] as const satisfies readonly Tab[];
export const TOPIC_ICON: Record<SupportTopic, LucideIcon> = {
  order: Package,
  product: Smartphone,
  payment: CreditCard,
  warranty: ShieldCheck,
  returns: RotateCcw,
  other: CircleHelp,
};
/** The status cards: an icon and its colours. */
const LOOK: Record<Tab, { Icon: LucideIcon; chip: string; ring: string }> = {
  "": { Icon: Inbox, chip: "bg-navy text-white", ring: "ring-navy" },
  open: { Icon: Clock, chip: "bg-warn-bg text-warn-tx", ring: "ring-warn" },
  answered: { Icon: CheckCheck, chip: "bg-ok-bg text-ok-tx", ring: "ring-ok" },
  closed: { Icon: Lock, chip: "bg-subtle text-tx2", ring: "ring-bd2" },
};

const kigaliDay = (d: Date) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Kigali" }).format(d);

/** "14:05" today, "Yesterday", or "12 Nov": how long ago a conversation last moved. */
export function inboxTime(
  iso: string,
  now = new Date(),
): { label: string; kind: "time" | "yesterday" | "date" } {
  const at = new Date(iso);
  if (kigaliDay(at) === kigaliDay(now))
    return { label: formatDate(iso, "time"), kind: "time" };
  if (kigaliDay(at) === kigaliDay(new Date(now.getTime() - 86_400_000)))
    return { label: "", kind: "yesterday" };
  return {
    label: new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      timeZone: "Africa/Kigali",
    }).format(at),
    kind: "date",
  };
}

/** The separator above the first message of each day: today, yesterday, or the date. */
export function messageDay(
  iso: string,
  now = new Date(),
): { label: string; kind: "today" | "yesterday" | "date" } {
  const at = new Date(iso);
  if (kigaliDay(at) === kigaliDay(now)) return { label: "", kind: "today" };
  if (kigaliDay(at) === kigaliDay(new Date(now.getTime() - 86_400_000)))
    return { label: "", kind: "yesterday" };
  return { label: formatDate(iso, "date"), kind: "date" };
}

/** Support: customer messages from the Contact page, laid out like Service requests (layout owner
 * 2026-11-18). Status cards on top (each one filters, with its count), the conversations in a
 * table (search by name, phone, email, reference or order), and the chosen one in a drawer: who and
 * how to reach them, what it is about, the conversation, and the reply box pinned at the bottom.
 * Management reads; administrators and sales reply and close (support:reply). Filters live in the
 * URL: status (open by default, "all" for every conversation), q, page. */
export function MessagesView() {
  const t = useTranslations("admin.messages");
  const tc = useTranslations("admin.common");
  const { get, page, set, hrefWith } = useListParams();
  const raw = get("status");
  const status: Tab =
    raw === "all"
      ? ""
      : (SUPPORT_STATUSES as readonly string[]).includes(raw)
        ? (raw as SupportStatus)
        : "open";
  const q = get("q");
  const [openId, setOpenId] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const list = useQuery({
    queryKey: ["admin", "support", { status, q, page }],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/support-threads", {
          params: {
            query: {
              status: status || undefined,
              q: q || undefined,
              page,
              size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const counts = useQuery({
    queryKey: ["admin", "support", "counts", q],
    queryFn: async () => {
      const totals = await Promise.all(
        TABS.map((s) =>
          must(
            browserApi.GET("/api/v1/staff/support-threads", {
              params: {
                query: { status: s || undefined, q: q || undefined, size: 1 },
              },
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
  const opened = items.find((m) => m.id === openId) ?? null;

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
          set({ status: s === "open" ? null : s || "all" })
        )}
        cards={TABS.map((s) => ({
          key: s,
          ...LOOK[s],
          label: t(`tabs.${s || "all"}`),
          hint: t(`hints.${s || "all"}`),
          count: counts.data?.[s],
          pulse: s === "open" && (counts.data?.open ?? 0) > 0,
        }))}
      />

      <section
        aria-label={t("listLabel")}
        className="overflow-hidden rounded-xl border border-bd bg-card shadow-sh"
      >
        <ListHeading
          Icon={LOOK[status].Icon}
          chip={LOOK[status].chip}
          title={t(`tabs.${status || "all"}`)}
          total={list.data?.total}
        />
        <FilterBar>
          <SearchBox
            label={t("searchLabel")}
            placeholder={t("searchPlaceholder")}
            value={q}
            onSearch={(value) => (setOpenId(null), set({ q: value }))}
            className="h-10 max-w-[420px] flex-[1_1_280px]"
          />
        </FilterBar>
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
                status === "open" && !q
                  ? "bg-ok-bg text-ok-tx"
                  : "bg-light text-pri-h",
              )}
            >
              {status === "open" && !q ? (
                <CheckCheck size={26} />
              ) : (
                <Inbox size={26} />
              )}
            </span>
            <p className="m-0 max-w-96 text-sm text-tx2">
              {q ? t("noMatch") : t(`empty.${status || "all"}`)}
            </p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.customer")}</Th>
                <Th>{t("columns.conversation")}</Th>
                <Th>{t("columns.last")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{tc("actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <ThreadRow
                  key={m.id}
                  thread={m}
                  now={now}
                  selected={m.id === openId}
                  onOpen={() => setOpenId(m.id)}
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
        open={openId !== null}
        onClose={() => setOpenId(null)}
        title={opened ? t("drawerTitle", { name: opened.name }) : t("title")}
        closeLabel={tc("close")}
        className="max-w-[min(560px,100%)]!"
        footer={openId ? <ThreadFooter key={openId} id={openId} /> : undefined}
      >
        {openId && <ThreadPanel key={openId} id={openId} now={now} />}
      </Drawer>
    </>
  );
}

function ThreadRow({
  thread,
  now,
  selected,
  onOpen,
}: {
  thread: Summary;
  now: number;
  selected: boolean;
  onOpen: () => void;
}) {
  const t = useTranslations("admin.messages");
  const Icon = TOPIC_ICON[thread.topic];
  const waiting = thread.status === "open";
  return (
    <tr className={rowClass(selected, waiting)}>
      <Td className="min-w-[190px]">
        <div className="flex items-center gap-3">
          <Avatar name={thread.name} />
          <button
            type="button"
            onClick={onOpen}
            className="flex min-w-0 cursor-pointer flex-col border-0 bg-transparent p-0 text-left"
          >
            <b className="font-semibold text-pri-h hover:underline">
              {thread.name}
            </b>
            <span className="text-cap break-all text-tx2">
              {thread.phone ? formatPhone(thread.phone) : thread.email}
            </span>
            <span className="text-cap text-tx2">
              {thread.has_account ? t("account") : t("guest")}
            </span>
          </button>
        </div>
      </Td>
      <Td className="max-w-[340px] min-w-[220px]">
        <span className="flex flex-col gap-1">
          <span
            className={cx(
              "truncate text-sm",
              waiting ? "font-bold" : "font-semibold",
            )}
          >
            {thread.subject}
          </span>
          <span className="truncate text-cap text-tx2">
            {thread.last_author === "staff" && (
              <b className="font-medium text-tx">{t("youReplied")} </b>
            )}
            {thread.last_preview}
          </span>
          <span className="flex flex-wrap gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full bg-subtle px-2 py-0.5 text-cap text-tx2">
              <Icon size={12} aria-hidden="true" />
              {t(`topics.${thread.topic}`)}
            </span>
            {thread.order_number && (
              <span className="rounded-full bg-light px-2 py-0.5 font-mono text-cap text-pri-h">
                {thread.order_number}
              </span>
            )}
          </span>
        </span>
      </Td>
      <Td className="whitespace-nowrap">
        <span className="flex flex-col">
          <span className="font-medium">
            {timeAgo(thread.last_message_at, now)}
          </span>
          <span className="text-cap text-tx2">
            {t("messageCount", { count: thread.message_count })}
          </span>
        </span>
      </Td>
      <Td>
        <Badge tone={SUPPORT_TONE[thread.status]}>
          {t(`status.${thread.status}`)}
        </Badge>
      </Td>
      <Td className="pl-1">
        <RowActions
          whatsapp={
            thread.phone
              ? whatsappHref(
                  thread.phone,
                  t("whatsappMessage", {
                    name: thread.name,
                    reference: thread.reference,
                  }),
                )
              : null
          }
          whatsappLabel={t("whatsappName", { name: thread.name })}
          openLabel={t("open", { name: thread.name })}
          onOpen={onOpen}
        />
      </Td>
    </tr>
  );
}

function useThread(id: string) {
  return useQuery({
    queryKey: ["admin", "support", "thread", id],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/support-threads/{thread_id}", {
          params: { path: { thread_id: id } },
        }),
      ),
  });
}

/** After a change: the thread from the answer, and the lists and the sidebar count again. */
function useRefresh(id: string) {
  const client = useQueryClient();
  return (saved: Detail) => {
    client.setQueryData(["admin", "support", "thread", id], saved);
    void client.invalidateQueries({
      queryKey: ["admin", "support"],
      predicate: (q) => q.queryKey[2] !== "thread",
    });
    void client.invalidateQueries({
      queryKey: ["admin", "count", "support-open"],
    });
  };
}

function ThreadPanel({ id, now }: { id: string; now: number }) {
  const t = useTranslations("admin.messages");
  const tc = useTranslations("admin.common");
  const reply = useStaffAccess().can("support:reply");
  const toast = useToast();
  const refresh = useRefresh(id);
  const end = useRef<HTMLSpanElement>(null);
  const query = useThread(id);
  const change = useMutation({
    mutationFn: (status: SupportStatus) =>
      must(
        browserApi.PATCH("/api/v1/staff/support-threads/{thread_id}", {
          params: { path: { thread_id: id } },
          body: { status },
        }),
      ),
    onSuccess: (saved) => {
      refresh(saved);
      toast.show(t("moved", { status: t(`status.${saved.status}`) }));
    },
    onError: () => toast.show(tc("saveError"), "error"),
  });
  const count = query.data?.messages.length;
  // The newest message is at the bottom: start there, and follow each new one.
  useEffect(() => {
    if (count) end.current?.scrollIntoView?.({ block: "end" });
  }, [count]);

  if (query.isError)
    return <LoadError onRetry={() => query.refetch()} className="m-5" />;
  if (!query.data)
    return (
      <div aria-busy="true" className="flex flex-col gap-4 p-5">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-20 w-3/4" />
        <Skeleton className="ml-auto h-16 w-2/3" />
      </div>
    );
  const thread = query.data;
  const Icon = TOPIC_ICON[thread.topic];
  const dayOf = (iso: string) => kigaliDay(new Date(iso));
  return (
    <div className="flex flex-col gap-5 p-5">
      {/* Who wrote, and how to reach them. */}
      <DrawerHeader
        name={thread.name}
        badges={
          <>
            <Badge tone={SUPPORT_TONE[thread.status]}>
              {t(`status.${thread.status}`)}
            </Badge>
            <CopyChip
              value={thread.reference}
              label={t("copyReference", { reference: thread.reference })}
            />
          </>
        }
        meta={[
          thread.has_account ? t("account") : t("guest"),
          t("startedAgo", {
            ago: timeAgo(thread.created_at, now),
            date: formatDate(thread.created_at, "dateTime"),
          }),
          thread.locale === "rw" ? t("prefersRw") : null,
        ]
          .filter(Boolean)
          .join(" · ")}
        phone={thread.phone}
        phoneText={thread.phone ? formatPhone(thread.phone) : undefined}
        whatsapp={
          thread.phone
            ? whatsappHref(
                thread.phone,
                t("whatsappMessage", {
                  name: thread.name,
                  reference: thread.reference,
                }),
              )
            : null
        }
        email={thread.email}
      />

      {/* What it is about, and closing or reopening it. */}
      <DrawerSection title={t("subjectTitle")}>
        <div className="flex flex-col gap-2.5 rounded-xl border border-bd bg-page p-4">
          <b className="text-base font-semibold break-words text-head">
            {thread.subject}
          </b>
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full bg-card px-2 py-0.5 text-cap font-medium text-tx2 ring-1 ring-bd">
              <Icon size={12} aria-hidden="true" />
              {t(`topics.${thread.topic}`)}
            </span>
            {thread.order_number && (
              // The order number only (SC-06: orders are the stores', the admin has no order page).
              <span className="inline-flex items-center gap-1 rounded-full bg-light px-2 py-0.5 font-mono text-cap font-semibold text-pri-h">
                <Package size={12} aria-hidden="true" />
                {thread.order_number}
              </span>
            )}
          </span>
        </div>
        {reply && (
          <div className="flex flex-wrap items-center gap-2">
            {thread.status === "closed" ? (
              <Button
                variant="outline"
                size="sm"
                disabled={change.isPending}
                onClick={() => change.mutate("open")}
                className="gap-1.5"
              >
                <RotateCcw size={14} aria-hidden="true" />
                {t("reopen")}
              </Button>
            ) : (
              <Button
                variant="neutral"
                size="sm"
                disabled={change.isPending}
                onClick={() => change.mutate("closed")}
                className="gap-1.5"
              >
                <Lock size={14} aria-hidden="true" />
                {t("close")}
              </Button>
            )}
          </div>
        )}
      </DrawerSection>

      {/* The conversation, oldest first: the customer on the left, the team on the right. */}
      <DrawerSection
        title={t("conversation")}
        aside={
          <span className="text-cap text-tx2">
            {t("messageCount", { count: thread.messages.length })}
          </span>
        }
      >
        <ol
          aria-label={t("conversation")}
          className="m-0 flex list-none flex-col gap-4 rounded-xl bg-page p-4"
        >
          {thread.messages.map((m, i) => {
            const staff = m.author === "staff";
            const day = messageDay(m.created_at);
            const newDay =
              i === 0 ||
              dayOf(m.created_at) !== dayOf(thread.messages[i - 1]!.created_at);
            return (
              <Fragment key={m.id}>
                {newDay && (
                  <li className="flex items-center gap-3 text-cap font-medium text-tx2">
                    <span aria-hidden="true" className="h-px flex-1 bg-bd" />
                    {day.kind === "today"
                      ? t("today")
                      : day.kind === "yesterday"
                        ? t("yesterday")
                        : day.label}
                    <span aria-hidden="true" className="h-px flex-1 bg-bd" />
                  </li>
                )}
                <li
                  className={cx(
                    "flex max-w-[88%] items-end gap-2.5",
                    staff ? "flex-row-reverse self-end" : "self-start",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cx(
                      "flex size-8 flex-none items-center justify-center rounded-full text-cap font-semibold",
                      staff
                        ? "bg-pri text-white"
                        : "border border-bd bg-card text-tx2",
                    )}
                  >
                    {staff ? <Headset size={15} /> : initials(thread.name)}
                  </span>
                  <div
                    className={cx(
                      "flex min-w-0 flex-col gap-1",
                      staff ? "items-end" : "items-start",
                    )}
                  >
                    <span className="px-1 text-cap text-tx2">
                      <b className="font-semibold text-tx">
                        {staff ? (m.staff_name ?? t("staff")) : thread.name}
                      </b>{" "}
                      · {formatDate(m.created_at, "time")}
                    </span>
                    <p
                      className={cx(
                        "m-0 rounded-2xl px-4 py-2.5 break-words whitespace-pre-line shadow-sh",
                        staff
                          ? "rounded-br-sm bg-pri text-white"
                          : "rounded-bl-sm border border-bd bg-card text-tx",
                      )}
                    >
                      {m.body}
                    </p>
                  </div>
                </li>
              </Fragment>
            );
          })}
        </ol>
        <span ref={end} aria-hidden="true" />
      </DrawerSection>
    </div>
  );
}

/** The drawer's pinned bottom: the reply box, or a note for those who only read. */
function ThreadFooter({ id }: { id: string }) {
  const t = useTranslations("admin.messages");
  const reply = useStaffAccess().can("support:reply");
  const query = useThread(id);
  const refresh = useRefresh(id);
  if (!query.data) return null;
  return reply ? (
    <Composer id={id} thread={query.data} onSaved={refresh} />
  ) : (
    <p className="m-0 flex items-center gap-2 text-sm text-tx2">
      <Lock size={15} aria-hidden="true" className="flex-none" />
      {t("readOnly")}
    </p>
  );
}

/** The reply box. Ctrl/Cmd+Enter sends. The note says where the reply goes: by email, to My
 * messages, or nowhere but here (call the customer). */
function Composer({
  id,
  thread,
  onSaved,
}: {
  id: string;
  thread: Detail;
  onSaved: (saved: Detail) => void;
}) {
  const t = useTranslations("admin.messages");
  const toast = useToast();
  const [body, setBody] = useState("");
  const [error, setError] = useState<string>();
  const send = useMutation({
    mutationFn: (text: string) =>
      must(
        browserApi.POST("/api/v1/staff/support-threads/{thread_id}/messages", {
          params: { path: { thread_id: id } },
          body: { body: text },
        }),
      ),
    onSuccess: (saved) => {
      setBody("");
      onSaved(saved);
      toast.show(
        thread.email ? t("sentEmail", { email: thread.email }) : t("sent"),
      );
    },
  });
  function submit() {
    const problem = bodyError(body);
    setError(problem);
    if (!problem) send.mutate(body.trim());
  }
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  }
  const note = thread.email
    ? t("replyHintEmail", { email: thread.email })
    : thread.has_account
      ? t("replyHintAccount")
      : t("replyHintPhone");
  return (
    <form
      onSubmit={onSubmit}
      noValidate
      aria-label={t("replyLabel")}
      className="flex flex-col gap-2"
    >
      <label htmlFor="support-reply" className="sr-only">
        {t("replyLabel")}
      </label>
      <div
        className={cx(
          "flex flex-col rounded-xl border bg-card focus-within:border-pri focus-within:shadow-focus",
          error ? "border-err" : "border-bd",
        )}
      >
        <textarea
          id="support-reply"
          value={body}
          onChange={(e) => (setBody(e.target.value), setError(undefined))}
          onKeyDown={onKeyDown}
          maxLength={SUPPORT_LIMITS.body}
          rows={3}
          placeholder={t("replyPlaceholder", { name: thread.name })}
          aria-invalid={error ? true : undefined}
          aria-describedby="support-reply-note"
          className="max-h-48 min-h-[76px] resize-y rounded-t-xl border-0 bg-transparent px-4 pt-3 pb-1 text-base text-tx outline-none placeholder:text-mut"
        />
        <div className="flex flex-wrap items-center gap-3 border-t border-bd px-3 py-2">
          <span
            id="support-reply-note"
            className={cx(
              "flex min-w-0 flex-1 items-center gap-1.5 text-cap",
              error ? "text-err-fg" : "text-tx2",
            )}
          >
            {error ? (
              t(`errors.${error}` as "errors.required")
            ) : (
              <>
                {thread.email ? (
                  <Mail size={13} aria-hidden="true" className="flex-none" />
                ) : (
                  <Phone size={13} aria-hidden="true" className="flex-none" />
                )}
                <span className="min-w-0">{note}</span>
              </>
            )}
          </span>
          <span className="text-cap text-tx2 max-sm:hidden">
            {t("shortcut")}
          </span>
          <span className="text-cap text-tx2 tabular-nums">
            {body.trim().length} / {SUPPORT_LIMITS.body}
          </span>
          <Button
            type="submit"
            size="sm"
            disabled={send.isPending}
            className="flex-none gap-2"
          >
            <Send size={15} aria-hidden="true" />
            {t("send")}
          </Button>
        </div>
      </div>
      {send.isError && (
        <div
          role="alert"
          className="flex items-center gap-2.5 rounded-lg bg-err-bg px-3 py-2 text-sm text-err-tx"
        >
          <CircleAlert size={16} aria-hidden="true" className="flex-none" />
          {t("sendFailed")}
        </div>
      )}
    </form>
  );
}
