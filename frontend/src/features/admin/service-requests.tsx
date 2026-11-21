"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BellRing,
  Building2,
  CalendarClock,
  CalendarDays,
  CircleCheck,
  CircleX,
  History,
  House,
  Inbox,
  Languages,
  MapPin,
  MessageSquareText,
  PhoneCall,
  RotateCcw,
  School,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { whatsappHref } from "@/lib/contact";
import { formatDate, formatPhone } from "@/lib/format";
import { useStaffAccess } from "./access";
import { Avatar, CopyChip, DrawerHeader, DrawerSection as Section, Fact, FACTS, ListHeading, RowActions, rowClass, StatusCards, Stepper, Timeline, TimelineItem } from "./inbox";
import { timeAgo } from "./time";
import { FilterBar, ListFooter, LoadError, must, PageHeader, useListParams } from "./ui";

type Lead = components["schemas"]["StaffServiceRequest"];
type Status = Lead["status"];
type ClientType = Lead["client_type"];

export const REQUEST_STATUSES = ["new", "contacted", "scheduled", "completed", "cancelled"] as const satisfies readonly Status[];
export const STATUS_TONE: Record<Status, BadgeTone> = {
  new: "soft-warn",
  contacted: "soft-info",
  scheduled: "soft-purple",
  completed: "soft-ok",
  cancelled: "soft-neutral",
};
/** The path a request normally follows; cancelled is set aside from it. */
const PIPELINE = ["new", "contacted", "scheduled", "completed"] as const satisfies readonly Status[];
/** The one-click next step from each status on the path. */
const NEXT: Partial<Record<Status, Status>> = { new: "contacted", contacted: "scheduled", scheduled: "completed" };

/** Each status's icon and colours (the same tones as its badge). */
const STATUS_LOOK: Record<Status | "", { Icon: LucideIcon; chip: string; ring: string }> = {
  "": { Icon: Inbox, chip: "bg-navy text-white", ring: "ring-navy" },
  new: { Icon: BellRing, chip: "bg-warn-bg text-warn-tx", ring: "ring-warn" },
  contacted: { Icon: PhoneCall, chip: "bg-light text-pri-h", ring: "ring-pri" },
  scheduled: { Icon: CalendarClock, chip: "bg-pur-bg text-pur", ring: "ring-pur" },
  completed: { Icon: CircleCheck, chip: "bg-ok-bg text-ok-tx", ring: "ring-ok" },
  cancelled: { Icon: CircleX, chip: "bg-subtle text-tx2", ring: "ring-bd2" },
};
const CLIENT_ICON: Record<ClientType, LucideIcon> = { home: House, business: Building2, institution: School };
const PAGE_SIZE = 20;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Service requests (leads) from the storefront's "Request this service" wizard (ADR-013; layout
 * owner 2026-11-18). Status cards on top give the pipeline at a glance and filter the list; the
 * filters (service, assignee, the day sent in Kigali) live in the URL (?status=, ?service=,
 * ?assigned=, ?from=, ?to=); each row can call or WhatsApp the client straight away and opens the
 * request in a drawer to move it along, assign it, keep notes and see its activity. */
export function ServiceRequestsView() {
  const canManage = useStaffAccess().can("services:manage");
  const t = useTranslations("admin.serviceRequests");
  const tc = useTranslations("admin.common");
  const { get, page, set, hrefWith } = useListParams();
  const status = (REQUEST_STATUSES as readonly string[]).includes(get("status")) ? (get("status") as Status) : "";
  const service = get("service");
  const assigned = canManage ? get("assigned") : "";
  const from = DATE.test(get("from")) ? get("from") : "";
  const to = DATE.test(get("to")) ? get("to") : "";
  const [openId, setOpenId] = useState<string | null>(null);
  const [now] = useState(() => Date.now());
  const services = useQuery({ queryKey: ["admin", "services"], queryFn: () => must(browserApi.GET("/api/v1/staff/services")) });
  const assignees = useQuery({ queryKey: ["admin", "service-requests", "assignees"], queryFn: () => must(browserApi.GET("/api/v1/staff/service-requests/assignees")), enabled: canManage });
  const query = { service_id: service || undefined, assigned_to: assigned || undefined, from: from || undefined, to: to || undefined };
  const list = useQuery({
    queryKey: ["admin", "service-requests", { status, service, assigned, from, to, page }],
    queryFn: () => must(browserApi.GET("/api/v1/staff/service-requests", { params: { query: { ...query, status: status || undefined, page, size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
  });
  const counts = useQuery({
    queryKey: ["admin", "service-requests", "counts", { service, assigned, from, to }],
    queryFn: async () => {
      const tabs = ["", ...REQUEST_STATUSES] as const;
      const totals = await Promise.all(tabs.map((s) => must(browserApi.GET("/api/v1/staff/service-requests", { params: { query: { ...query, status: s || undefined, size: 1 } } }))));
      return Object.fromEntries(tabs.map((s, i) => [s, totals[i]!.total])) as Record<Status | "", number>;
    },
  });
  const items = list.data?.items ?? [];
  const opened = items.find((r) => r.id === openId) ?? null;
  const filtered = Boolean(service || assigned || from || to);

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <StatusCards
        label={t("tabsLabel")}
        className="mb-5 grid-cols-2 sm:grid-cols-3 xl:grid-cols-6"
        value={status}
        onChange={(s) => set({ status: s || null })}
        cards={(["", ...REQUEST_STATUSES] as const).map((s) => ({
          key: s,
          ...STATUS_LOOK[s],
          label: s ? t(`status.${s}`) : t("overview.all"),
          hint: t(`overview.hints.${s || "all"}`),
          count: counts.data?.[s],
          pulse: s === "new" && (counts.data?.new ?? 0) > 0,
        }))}
      />

      <section aria-label={t("listLabel")} className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <ListHeading Icon={STATUS_LOOK[status].Icon} chip={STATUS_LOOK[status].chip} title={status ? t(`status.${status}`) : t("overview.all")} total={list.data?.total}>
          {filtered && (
            <Button variant="ghost" size="sm" onClick={() => set({ service: null, assigned: null, from: null, to: null })}>
              <RotateCcw size={14} aria-hidden="true" />
              {t("clearFilters")}
            </Button>
          )}
        </ListHeading>
        <FilterBar>
          <Field label={t("service")} className="min-w-[200px] flex-[1_1_220px]">
            {(c) => (
              <Select {...c} value={service} onChange={(e) => set({ service: e.target.value || null })}>
                <option value="">{t("allServices")}</option>
                {(services.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name_en}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {canManage && (
            <Field label={t("assignedFilter")} className="min-w-[180px] flex-[1_1_200px]">
              {(c) => (
                <Select {...c} value={assigned} onChange={(e) => set({ assigned: e.target.value || null })}>
                  <option value="">{t("anyone")}</option>
                  {(assignees.data ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label={t("from")} className="w-[170px] max-sm:flex-1">
            {(c) => <Input {...c} type="date" value={from} max={to || undefined} onChange={(e) => set({ from: e.target.value || null })} />}
          </Field>
          <Field label={t("to")} className="w-[170px] max-sm:flex-1">
            {(c) => <Input {...c} type="date" value={to} min={from || undefined} onChange={(e) => set({ to: e.target.value || null })} />}
          </Field>
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
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-light text-pri-h">
              <Inbox size={26} />
            </span>
            <b className="text-base font-semibold">{t(status || filtered ? "emptyFilteredTitle" : "emptyTitle")}</b>
            <p className="m-0 max-w-96 text-sm text-tx2">{t(status || filtered ? "emptyFiltered" : "empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.client")}</Th>
                <Th>{t("columns.service")}</Th>
                <Th>{t("columns.sent")}</Th>
                <Th>{t("columns.assigned")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("columns.actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <RequestRow key={r.id} lead={r} now={now} selected={r.id === openId} onOpen={() => setOpenId(r.id)} />
              ))}
            </tbody>
          </Table>
        )}
        {list.data && list.data.total > PAGE_SIZE && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
      <Drawer
        open={opened !== null}
        onClose={() => setOpenId(null)}
        title={opened ? t("detailTitle", { name: opened.full_name }) : t("title")}
        closeLabel={tc("close")}
        className="max-w-[min(520px,100%)]!"
      >
        {opened && <RequestDetail key={opened.id} lead={opened} canManage={canManage} now={now} />}
      </Drawer>
    </>
  );
}

function RequestRow({ lead, now, selected, onOpen }: { lead: Lead; now: number; selected: boolean; onOpen: () => void }) {
  const t = useTranslations("admin.serviceRequests");
  const TypeIcon = CLIENT_ICON[lead.client_type];
  return (
    <tr className={rowClass(selected, lead.status === "new")}>
      <Td className="min-w-[210px]">
        <div className="flex items-center gap-3">
          <Avatar name={lead.full_name} />
          <button type="button" onClick={onOpen} className="flex min-w-0 cursor-pointer flex-col border-0 bg-transparent p-0 text-left">
            <b className="font-semibold text-pri-h hover:underline">{lead.full_name}</b>
            <span className="text-cap whitespace-nowrap text-tx2">{formatPhone(lead.phone)}</span>
            <span className="font-mono text-cap whitespace-nowrap text-tx2">{lead.reference}</span>
          </button>
        </div>
      </Td>
      <Td className="min-w-[200px]">
        <div className="flex flex-col gap-1.5">
          <span className="font-medium">{lead.service.name}</span>
          <span className="flex flex-wrap gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-full bg-subtle px-2 py-0.5 text-cap text-tx2">
              <TypeIcon size={12} aria-hidden="true" />
              {t(`clientTypes.${lead.client_type}`)}
            </span>
            {lead.preferred_date && (
              <span title={t("preferredDate")} className="inline-flex items-center gap-1 rounded-full bg-light px-2 py-0.5 text-cap whitespace-nowrap text-pri-h">
                <CalendarDays size={12} aria-hidden="true" />
                <span className="sr-only">{t("preferredDate")}: </span>
                {formatDate(lead.preferred_date, "date")}
              </span>
            )}
          </span>
        </div>
      </Td>
      <Td className="whitespace-nowrap">
        <span className="flex flex-col">
          <span className="font-medium">{timeAgo(lead.created_at, now)}</span>
          <span className="text-cap text-tx2">{formatDate(lead.created_at, "dateTime")}</span>
        </span>
      </Td>
      <Td>
        {lead.assigned_to ? (
          <span className="inline-flex items-center gap-2">
            <Avatar name={lead.assigned_to.name} size="sm" />
            {lead.assigned_to.name}
          </span>
        ) : (
          <span className="text-tx2 italic">{t("unassigned")}</span>
        )}
      </Td>
      <Td>
        <Badge tone={STATUS_TONE[lead.status]}>{t(`status.${lead.status}`)}</Badge>
      </Td>
      <Td>
        <RowActions
          whatsapp={whatsappHref(lead.phone, t("whatsappMessage", { name: lead.full_name, reference: lead.reference, service: lead.service.name }))}
          whatsappLabel={t("whatsappName", { name: lead.full_name })}
          openLabel={t("open", { name: lead.full_name })}
          onOpen={onOpen}
        />
      </Td>
    </tr>
  );
}

function RequestDetail({ lead, canManage, now }: { lead: Lead; canManage: boolean; now: number }) {
  const t = useTranslations("admin.serviceRequests");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const [notes, setNotes] = useState(lead.internal_notes ?? "");
  const assignees = useQuery({ queryKey: ["admin", "service-requests", "assignees"], queryFn: () => must(browserApi.GET("/api/v1/staff/service-requests/assignees")), enabled: canManage });
  const update = useMutation({
    mutationFn: (body: components["schemas"]["ServiceRequestUpdate"]) => must(browserApi.PATCH("/api/v1/staff/service-requests/{request_id}", { params: { path: { request_id: lead.id } }, body })),
    onSuccess: () => {
      toast.show(tc("saved"));
      void client.invalidateQueries({ queryKey: ["admin", "service-requests"] });
      void client.invalidateQueries({ queryKey: ["admin", "count", "service-requests-new"] });
    },
    onError: () => toast.show(tc("saveError"), "error"),
  });
  const notesChanged = notes.trim() !== (lead.internal_notes ?? "");
  const next = NEXT[lead.status];
  const TypeIcon = CLIENT_ICON[lead.client_type];

  return (
    <div className="flex flex-col gap-5 p-5">
      {/* Who and when */}
      <DrawerHeader
        name={lead.full_name}
        badges={
          <>
            <Badge tone={STATUS_TONE[lead.status]}>{t(`status.${lead.status}`)}</Badge>
            <CopyChip value={lead.reference} label={t("copyReference", { reference: lead.reference })} />
          </>
        }
        meta={t("receivedAgo", { ago: timeAgo(lead.created_at, now), date: formatDate(lead.created_at, "dateTime") })}
        phone={lead.phone}
        phoneText={formatPhone(lead.phone)}
        whatsapp={whatsappHref(lead.phone, t("whatsappMessage", { name: lead.full_name, reference: lead.reference, service: lead.service.name }))}
        email={lead.email}
      />

      {/* Progress */}
      <Section title={t("progressTitle")}>
        {lead.status === "cancelled" ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-subtle px-4 py-3">
            <span className="inline-flex items-center gap-2 text-sm text-tx2">
              <CircleX size={16} aria-hidden="true" />
              {t("cancelledNote")}
            </span>
            {canManage && (
              <Button variant="neutral" size="sm" disabled={update.isPending} onClick={() => update.mutate({ status: "new" })}>
                <RotateCcw size={14} aria-hidden="true" />
                {t("reopen")}
              </Button>
            )}
          </div>
        ) : (
          <>
            <Stepper
              label={t("progressTitle")}
              steps={PIPELINE.map((s) => ({ key: s, label: t(`status.${s}`) }))}
              at={PIPELINE.indexOf(lead.status as (typeof PIPELINE)[number])}
              finished={lead.status === "completed"}
            />
            {canManage && (
              <div className="flex flex-wrap items-center gap-2">
                {next && (
                  <Button size="sm" disabled={update.isPending} onClick={() => update.mutate({ status: next })}>
                    {t(`next.${lead.status as "new" | "contacted" | "scheduled"}`)}
                    <ArrowRight size={15} aria-hidden="true" />
                  </Button>
                )}
                <Button variant="ghost" size="sm" className="text-err hover:text-err" disabled={update.isPending} onClick={() => update.mutate({ status: "cancelled" })}>
                  {t("cancelRequest")}
                </Button>
              </div>
            )}
          </>
        )}
      </Section>

      {/* What was asked */}
      <Section title={t("detailsTitle")}>
        <dl className={FACTS}>
          <Fact Icon={Wrench} label={t("columns.service")}>
            {lead.service.name}
          </Fact>
          <Fact Icon={TypeIcon} label={t("columns.type")}>
            {t(`clientTypes.${lead.client_type}`)}
          </Fact>
          <Fact Icon={MapPin} label={t("location")}>
            {lead.location || <span className="text-tx2 italic">{t("notGiven")}</span>}
          </Fact>
          <Fact Icon={CalendarDays} label={t("preferredDate")}>
            {lead.preferred_date ? formatDate(lead.preferred_date, "date") : <span className="text-tx2 italic">{t("anyDay")}</span>}
          </Fact>
          {lead.locale === "rw" && (
            <Fact Icon={Languages} label={t("language")}>
              {t("prefersRw")}
            </Fact>
          )}
        </dl>
        {lead.message && (
          <figure className="m-0 flex gap-3 rounded-xl border border-bd bg-white p-4">
            <MessageSquareText size={18} aria-hidden="true" className="mt-0.5 flex-none text-pri" />
            <blockquote className="m-0 flex flex-col gap-1">
              <span className="text-cap font-semibold text-tx2">{t("messageTitle")}</span>
              <p className="m-0 break-words whitespace-pre-line text-tx">{lead.message}</p>
            </blockquote>
          </figure>
        )}
      </Section>

      {/* Follow-up */}
      {canManage ? (
        <Section title={t("manageTitle")}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("columns.status")}>
              {(c) => (
                <Select {...c} value={lead.status} disabled={update.isPending} onChange={(e) => update.mutate({ status: e.target.value as Status })}>
                  {REQUEST_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {t(`status.${s}`)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("columns.assigned")}>
              {(c) => (
                <Select {...c} value={lead.assigned_to?.id ?? ""} disabled={update.isPending || !assignees.data} onChange={(e) => update.mutate({ assigned_to_user_id: e.target.value || null })}>
                  <option value="">{t("unassigned")}</option>
                  {(assignees.data ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                  {lead.assigned_to && !assignees.data?.some((a) => a.id === lead.assigned_to!.id) && <option value={lead.assigned_to.id}>{lead.assigned_to.name}</option>}
                </Select>
              )}
            </Field>
          </div>
          <Field label={t("notes")} help={t("notesHelp")}>
            {(c) => <Textarea {...c} rows={4} maxLength={4000} value={notes} onChange={(e) => setNotes(e.target.value)} />}
          </Field>
          <Button className="self-end" size="sm" disabled={!notesChanged || update.isPending} onClick={() => update.mutate({ internal_notes: notes.trim() || null })}>
            {t("saveNotes")}
          </Button>
        </Section>
      ) : (
        <Section title={t("manageTitle")}>
          <dl className={FACTS}>
            <Fact Icon={UserRound} label={t("columns.assigned")}>
              {lead.assigned_to?.name ?? <span className="text-tx2 italic">{t("unassigned")}</span>}
            </Fact>
          </dl>
          {lead.internal_notes && (
            <div className="flex flex-col gap-1">
              <span className="text-cap font-semibold text-tx2">{t("notes")}</span>
              <p className="m-0 whitespace-pre-line">{lead.internal_notes}</p>
            </div>
          )}
        </Section>
      )}

      {/* Activity */}
      <Section title={t("activityTitle")}>
        <Timeline>
          <TimelineItem Icon={Inbox} label={t("activity.received")} at={lead.created_at} />
          {lead.status_changed_at && <TimelineItem Icon={History} label={t("activity.statusChanged", { status: t(`status.${lead.status}`) })} at={lead.status_changed_at} />}
          {lead.updated_at !== lead.created_at && lead.updated_at !== lead.status_changed_at && <TimelineItem Icon={RotateCcw} label={t("activity.updated")} at={lead.updated_at} />}
        </Timeline>
      </Section>
    </div>
  );
}
