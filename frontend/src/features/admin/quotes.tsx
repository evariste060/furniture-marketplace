"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, CheckCheck, ClipboardList, History, Inbox, Languages, MapPin, MessageSquareText, PhoneCall, Sparkles, UserRound, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Drawer } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import { formatDate, formatPhone } from "@/lib/format";
import { Avatar, CopyChip, DrawerHeader, DrawerSection, Fact, FACTS, ListHeading, RowActions, rowClass, StatusCards, Timeline, TimelineItem } from "./inbox";
import { timeAgo } from "./time";
import { ListFooter, LoadError, must, PageHeader, useListParams } from "./ui";

type Quote = components["schemas"]["StaffQuoteRequest"];
type Status = Quote["status"];
type Tab = Status | "";

export const QUOTE_STATUSES = ["new", "contacted", "closed"] as const;
const TABS = ["", "new", "contacted", "closed"] as const satisfies readonly Tab[];
const PAGE_SIZE = 20;
const STATUS_TONE: Record<Status, BadgeTone> = { new: "soft-warn", contacted: "soft-info", closed: "soft-neutral" };
/** The status cards: an icon and its colours. */
const LOOK: Record<Tab, { Icon: LucideIcon; chip: string; ring: string }> = {
  "": { Icon: ClipboardList, chip: "bg-navy text-white", ring: "ring-navy" },
  new: { Icon: Sparkles, chip: "bg-warn-bg text-warn-tx", ring: "ring-warn" },
  contacted: { Icon: PhoneCall, chip: "bg-light text-pri-h", ring: "ring-pri" },
  closed: { Icon: CheckCheck, chip: "bg-ok-bg text-ok-tx", ring: "ring-ok" },
};
const DUE_TONE = { passed: "soft-err", today: "soft-warn", tomorrow: "soft-warn", soon: "soft-warn", later: "soft-neutral" } as const satisfies Record<string, BadgeTone>;

/** Total units asked for across a request's lines. */
export function quoteUnits(lines: readonly { quantity: number }[]): number {
  return lines.reduce((sum, line) => sum + line.quantity, 0);
}

const kigaliDay = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Kigali" }).format(d);

/** How close a "needed by" day (YYYY-MM-DD) is, counted in Kigali days: passed, today, tomorrow,
 * soon (within a week) or later, with the number of days left. */
export function dueIn(neededBy: string, now = new Date()): { kind: keyof typeof DUE_TONE; days: number } {
  const days = Math.round((Date.parse(`${neededBy}T00:00:00Z`) - Date.parse(`${kigaliDay(now)}T00:00:00Z`)) / 86_400_000);
  const kind = days < 0 ? "passed" : days === 0 ? "today" : days === 1 ? "tomorrow" : days <= 7 ? "soon" : "later";
  return { kind, days };
}

/** Business quote requests from the Bulk orders page (module 19; layout owner 2026-11-18, like
 * Service requests). Status cards on top (each one filters, with its count), the requests in a
 * table with one-click Call and WhatsApp, and the chosen request in a drawer: who, ways to reach
 * them, where it stands (click a step to move it), what they want and by when. The status lives in
 * the URL (?status=, "all" for every request; new by default). */
export function QuotesView() {
  const t = useTranslations("admin.quotes");
  const tc = useTranslations("admin.common");
  const { get, page, set, hrefWith } = useListParams();
  const raw = get("status");
  const status: Tab = raw === "all" ? "" : (QUOTE_STATUSES as readonly string[]).includes(raw) ? (raw as Status) : "new";
  const [openId, setOpenId] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const list = useQuery({
    queryKey: ["admin", "quotes", { status, page }],
    queryFn: () => must(browserApi.GET("/api/v1/staff/quote-requests", { params: { query: { status: status || undefined, page, size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
  });
  const counts = useQuery({
    queryKey: ["admin", "quotes", "counts"],
    queryFn: async () => {
      const totals = await Promise.all(TABS.map((s) => must(browserApi.GET("/api/v1/staff/quote-requests", { params: { query: { status: s || undefined, size: 1 } } }))));
      return Object.fromEntries(TABS.map((s, i) => [s, totals[i]!.total])) as Record<Tab, number>;
    },
  });
  const items = list.data?.items ?? [];
  const opened = items.find((q) => q.id === openId) ?? null;

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />

      {/* Each card filters the list by status. */}
      <StatusCards
        label={t("tabsLabel")}
        className="grid-cols-2 lg:grid-cols-4"
        value={status}
        onChange={(s) => (setOpenId(null), set({ status: s === "new" ? null : s || "all" }))}
        cards={TABS.map((s) => ({
          key: s,
          ...LOOK[s],
          label: t(`tiles.${s || "all"}`),
          hint: t(`hints.${s || "all"}`),
          count: counts.data?.[s],
          pulse: s === "new" && (counts.data?.new ?? 0) > 0,
        }))}
      />

      <section aria-label={t("listLabel")} className="overflow-hidden rounded-xl border border-bd bg-card shadow-sh">
        <ListHeading Icon={LOOK[status].Icon} chip={LOOK[status].chip} title={t(`tiles.${status || "all"}`)} total={list.data?.total} />
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
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-light text-pri-h">
              <Inbox size={26} />
            </span>
            <p className="m-0 max-w-96 text-sm text-tx2">{t(`empty.${status || "all"}`)}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.company")}</Th>
                <Th>{t("columns.request")}</Th>
                <Th>{t("columns.sent")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{tc("actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {items.map((q) => (
                <QuoteRow key={q.id} quote={q} now={now} selected={q.id === openId} onOpen={() => setOpenId(q.id)} />
              ))}
            </tbody>
          </Table>
        )}
        {list.data && list.data.total > PAGE_SIZE && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>

      <Drawer
        open={opened !== null}
        onClose={() => setOpenId(null)}
        title={opened ? t("drawerTitle", { company: opened.company }) : t("title")}
        closeLabel={tc("close")}
        className="max-w-[min(520px,100%)]!"
      >
        {opened && <QuoteDetail key={opened.id} quote={opened} now={now} />}
      </Drawer>
    </>
  );
}

function QuoteRow({ quote, now, selected, onOpen }: { quote: Quote; now: number; selected: boolean; onOpen: () => void }) {
  const t = useTranslations("admin.quotes");
  return (
    <tr className={rowClass(selected, quote.status === "new")}>
      <Td className="min-w-[220px]">
        <div className="flex items-center gap-3">
          <Avatar name={quote.company} />
          <button type="button" onClick={onOpen} className="flex min-w-0 cursor-pointer flex-col border-0 bg-transparent p-0 text-left">
            <b className="font-semibold text-pri-h hover:underline">{quote.company}</b>
            <span className="text-cap text-tx2">{quote.contact_name}</span>
            <span className="font-mono text-cap whitespace-nowrap text-tx2">{quote.reference}</span>
          </button>
        </div>
      </Td>
      <Td className="min-w-[200px]">
        <span className="flex flex-wrap gap-1.5">
          <span className="rounded-full bg-subtle px-2 py-0.5 text-cap font-medium whitespace-nowrap text-tx2">{t("summary", { products: quote.lines.length, units: quoteUnits(quote.lines) })}</span>
          {quote.needed_by && quote.status !== "closed" && <Due neededBy={quote.needed_by} />}
        </span>
      </Td>
      <Td className="whitespace-nowrap">
        <span className="flex flex-col">
          <span className="font-medium">{timeAgo(quote.created_at, now)}</span>
          <span className="text-cap text-tx2">{formatDate(quote.created_at, "dateTime")}</span>
        </span>
      </Td>
      <Td>
        <Badge tone={STATUS_TONE[quote.status]}>{t(`status.${quote.status}`)}</Badge>
      </Td>
      <Td>
        <RowActions
          whatsapp={whatsappHref(quote.phone, t("whatsappMessage", { name: quote.contact_name, reference: quote.reference }))}
          whatsappLabel={t("whatsappName", { name: quote.contact_name })}
          openLabel={t("open", { company: quote.company })}
          onOpen={onOpen}
        />
      </Td>
    </tr>
  );
}

/** How soon the customer needs the goods, coloured by urgency. */
function Due({ neededBy }: { neededBy: string }) {
  const t = useTranslations("admin.quotes");
  const { kind, days } = dueIn(neededBy);
  return (
    <Badge tone={DUE_TONE[kind]} className="gap-1">
      <CalendarClock size={12} aria-hidden="true" />
      {t(`due.${kind}`, { days, date: formatDate(neededBy, "date") })}
    </Badge>
  );
}

function QuoteDetail({ quote, now }: { quote: Quote; now: number }) {
  const t = useTranslations("admin.quotes");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const change = useMutation({
    mutationFn: (status: Status) => must(browserApi.PATCH("/api/v1/staff/quote-requests/{quote_id}", { params: { path: { quote_id: quote.id } }, body: { status } })),
    onSuccess: (saved) => {
      toast.show(t("moved", { status: t(`status.${saved.status}`) }));
      void client.invalidateQueries({ queryKey: ["admin", "quotes"] });
      void client.invalidateQueries({ queryKey: ["admin", "count", "quotes-new"] });
    },
    onError: () => toast.show(tc("saveError"), "error"),
  });
  const units = quoteUnits(quote.lines);
  const most = Math.max(...quote.lines.map((l) => l.quantity), 1);
  const at = QUOTE_STATUSES.indexOf(quote.status);

  return (
    <div className="flex flex-col gap-5 p-5">
      {/* Who asked, and the ways to reach them. */}
      <DrawerHeader
        name={quote.company}
        badges={
          <>
            <Badge tone={STATUS_TONE[quote.status]}>{t(`status.${quote.status}`)}</Badge>
            <CopyChip value={quote.reference} label={t("copyReference", { reference: quote.reference })} />
          </>
        }
        meta={`${t("requestedBy", { name: quote.contact_name })} · ${t("receivedAgo", { ago: timeAgo(quote.created_at, now), date: formatDate(quote.created_at, "dateTime") })}`}
        phone={quote.phone}
        phoneText={formatPhone(quote.phone)}
        whatsapp={whatsappHref(quote.phone, t("whatsappMessage", { name: quote.contact_name, reference: quote.reference }))}
        email={quote.email}
      />

      {/* Where the request stands: click a step to move it there. */}
      <DrawerSection title={t("progress")} aside={quote.handled_at ? <span className="text-cap text-tx2">{t("handled", { date: formatDate(quote.handled_at, "dateTime") })}</span> : undefined}>
        <ol aria-label={t("progress")} className="m-0 grid list-none grid-cols-3 gap-2 p-0">
          {QUOTE_STATUSES.map((s, i) => {
            const done = i < at || (i === at && s === "closed");
            const current = i === at;
            return (
              <li key={s} className="min-w-0">
                <button
                  type="button"
                  aria-current={current ? "step" : undefined}
                  disabled={current || change.isPending}
                  onClick={() => change.mutate(s)}
                  className={cx(
                    "group flex w-full flex-col items-center gap-1.5 rounded-lg border bg-card px-2 py-3 text-center transition-[border-color,box-shadow] duration-150 motion-reduce:transition-none",
                    current ? "cursor-default border-pri ring-1 ring-pri" : "cursor-pointer border-bd hover:border-bd2 hover:shadow-sh disabled:cursor-wait disabled:opacity-60",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cx(
                      "flex size-8 items-center justify-center rounded-full text-cap font-semibold",
                      done ? "bg-ok-tx text-white" : current ? "bg-pri text-white ring-4 ring-light" : "border border-bd2 bg-card text-tx2",
                    )}
                  >
                    {done ? <Check size={15} /> : i + 1}
                  </span>
                  <span className={cx("max-w-full truncate text-sm", current ? "font-semibold text-head" : "font-medium text-tx2 group-hover:text-tx")}>{t(`status.${s}`)}</span>
                  {!current && <span className="sr-only">{t(`mark.${s}`)}</span>}
                </button>
              </li>
            );
          })}
        </ol>
        <p className="m-0 text-cap text-tx2">{t(`stageHint.${quote.status}`)}</p>
      </DrawerSection>

      {/* What they want: each line's bar shows its share of the largest quantity. */}
      <DrawerSection title={t("productsHeading")} aside={<span className="text-cap font-semibold text-tx2">{t("summary", { products: quote.lines.length, units })}</span>}>
        <div className="flex flex-col gap-3 rounded-xl border border-bd p-4">
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {quote.lines.map((line, i) => (
              <li key={i} className="flex flex-col gap-1.5">
                <span className="flex items-center gap-3">
                  <span aria-hidden="true" className="flex size-6 flex-none items-center justify-center rounded-full bg-subtle text-cap font-semibold text-tx2">
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 font-medium break-words text-tx">{line.product}</span>
                  <b className="flex-none rounded-md bg-light px-2 py-0.5 text-sm font-semibold text-pri-h tabular-nums">{t("units", { count: line.quantity })}</b>
                </span>
                <span aria-hidden="true" className="ml-9 h-1 overflow-hidden rounded-full bg-subtle">
                  <span className="block h-full rounded-full bg-pri/60" style={{ width: `${Math.max(4, (line.quantity / most) * 100)}%` }} />
                </span>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between border-t border-bd pt-3">
            <span className="text-sm font-semibold text-tx">{t("total")}</span>
            <b className="t-h4 tabular-nums">{units.toLocaleString("en-GB")}</b>
          </div>
        </div>
      </DrawerSection>

      {/* Where and by when. */}
      <DrawerSection title={t("deliveryHeading")}>
        <dl className={FACTS}>
          <Fact Icon={UserRound} label={t("contact")}>
            {quote.contact_name}
          </Fact>
          <Fact Icon={MapPin} label={t("location")}>
            {quote.delivery_location || <span className="text-tx2 italic">{t("notGiven")}</span>}
          </Fact>
          <Fact Icon={CalendarClock} label={t("neededBy")}>
            {quote.needed_by ? (
              <span className="flex flex-wrap items-center gap-2">
                {formatDate(quote.needed_by, "date")}
                {quote.status !== "closed" && <Due neededBy={quote.needed_by} />}
              </span>
            ) : (
              <span className="text-tx2 italic">{t("notGiven")}</span>
            )}
          </Fact>
          {quote.locale === "rw" && (
            <Fact Icon={Languages} label={t("language")}>
              {t("prefersRw")}
            </Fact>
          )}
        </dl>
        {/* In their words. */}
        {quote.message && (
          <figure className="m-0 flex gap-3 rounded-xl border border-bd bg-card p-4">
            <MessageSquareText size={18} aria-hidden="true" className="mt-0.5 flex-none text-pri-fg" />
            <blockquote className="m-0 flex flex-col gap-1">
              <span className="text-cap font-semibold text-tx2">{t("message")}</span>
              <p className="m-0 break-words whitespace-pre-line text-tx">{quote.message}</p>
            </blockquote>
          </figure>
        )}
      </DrawerSection>

      {/* Activity */}
      <DrawerSection title={t("activityTitle")}>
        <Timeline>
          <TimelineItem Icon={Inbox} label={t("activity.received")} at={quote.created_at} />
          {quote.handled_at && <TimelineItem Icon={History} label={t("activity.handled", { status: t(`status.${quote.status}`) })} at={quote.handled_at} />}
        </Timeline>
      </DrawerSection>
    </div>
  );
}
