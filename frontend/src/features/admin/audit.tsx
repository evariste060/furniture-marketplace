"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  FileText,
  History,
  MessageSquare,
  Package,
  Settings,
  ShieldAlert,
  ShieldCheck,
  ShoppingCart,
  Tag,
  Truck,
  User,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import { useStaffAccess } from "./access";
import { kigaliDay } from "./promotions";
import { ListFooter, LoadError, must, PageHeader, useListParams } from "./ui";

type AuditEntry = components["schemas"]["AuditRecordResponse"];

const PAGE_SIZE = 25;
const DAY = 24 * 60 * 60 * 1000;
const PERIODS = ["7", "30", "90", "all"] as const;

/** The entity types the backend writes (grep entity_type= in backend/app), in menu order. The
 * API filters on one exact entity type. */
export const AUDIT_AREAS = [
  "order",
  "product",
  "product_variant",
  "product_image",
  "category",
  "brand",
  "import_job",
  "job",
  "inventory",
  "product_review",
  "promotion",
  "delivery_zone",
  "banner",
  "settings",
  "user",
  "session",
  "login_identifier",
  "address",
  "cart",
  "support_thread",
  "service",
  "service_request",
  "endpoint",
] as const;

/** The timeline icon for each area: orders blue, catalogue purple, stock green, security amber. */
const CATALOGUE = { Icon: Package, tone: "bg-pur-bg text-pur" };
const SECURITY = { Icon: ShieldCheck, tone: "bg-warn-bg text-warn-tx" };
const AREA_ICON: Record<string, { Icon: LucideIcon; tone: string }> = {
  order: { Icon: ShoppingCart, tone: "bg-light text-pri-h" },
  product: CATALOGUE,
  product_variant: CATALOGUE,
  product_image: CATALOGUE,
  category: CATALOGUE,
  brand: CATALOGUE,
  import_job: CATALOGUE,
  job: CATALOGUE,
  inventory: { Icon: Boxes, tone: "bg-ok-bg text-ok-tx" },
  product_review: { Icon: MessageSquare, tone: "bg-light text-pri-h" },
  promotion: { Icon: Tag, tone: "bg-err-bg text-err-tx" },
  delivery_zone: { Icon: Truck, tone: "bg-ok-bg text-ok-tx" },
  banner: { Icon: Settings, tone: "bg-subtle text-tx2" },
  settings: { Icon: Settings, tone: "bg-subtle text-tx2" },
  page: { Icon: FileText, tone: "bg-subtle text-tx2" },
  quote_request: { Icon: FileText, tone: "bg-light text-pri-h" },
  service: { Icon: Wrench, tone: "bg-light text-pri-h" },
  service_request: { Icon: Wrench, tone: "bg-light text-pri-h" },
  user: SECURITY,
  session: SECURITY,
  login_identifier: SECURITY,
  endpoint: SECURITY,
  address: { Icon: User, tone: "bg-subtle text-tx2" },
  cart: { Icon: ShoppingCart, tone: "bg-subtle text-tx2" },
};
const FALLBACK_ICON = { Icon: Activity, tone: "bg-subtle text-tx2" };

/** Bookkeeping keys that say nothing about the change itself. */
const NOISE = new Set(["status", "ip_address", "user_agent", "sha256", "new_sha256", "image_ref", "new_media_id", "movement_id", "attempt_id", "job_id", "cart_id", "guest_cart_id", "product_id"]);

const show = (value: unknown): string => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

/** A one-line reading of change_summary, the Change column: "status: draft → active",
 * "received → cancelled", or the first few meaningful values. */
export function changeLine(summary: Record<string, unknown>, max = 160): string {
  let text: string;
  const changes = summary.changes;
  if (changes && typeof changes === "object" && !Array.isArray(changes)) {
    text = Object.entries(changes as Record<string, unknown>)
      .map(([key, v]) => {
        const pair = v && typeof v === "object" ? (v as { from?: unknown; to?: unknown }) : {};
        return `${key}: ${show(pair.from)} → ${show(pair.to)}`;
      })
      .join("; ");
  } else if ("from_status" in summary || "to_status" in summary) {
    text = `${show(summary.from_status)} → ${show(summary.to_status)}`;
  } else if ("from" in summary && "to" in summary) {
    text = `${show(summary.from)} → ${show(summary.to)}`;
  } else if ("on_hand_before" in summary && "on_hand_after" in summary) {
    text = `${show(summary.on_hand_before)} → ${show(summary.on_hand_after)}${summary.reason ? ` (${show(summary.reason)})` : ""}`;
  } else {
    text = Object.entries(summary)
      .filter(([key, v]) => !NOISE.has(key) && v !== null && typeof v !== "object")
      .slice(0, 4)
      .map(([key, v]) => `${key}: ${show(v)}`)
      .join(" · ");
  }
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** "catalog.product_update" → "Product update"; the action code is shown as well. */
export function actionLabel(action: string): string {
  const tail = action.includes(".") ? action.slice(action.indexOf(".") + 1) : action;
  const words = tail.replace(/[._]/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : action;
}

/** Audit.dc.html, read as a timeline: filters, then the entries grouped by Kigali day, newest
 * first (the API's order). Failed and denied attempts are marked in red. */
export function AuditView() {
  const t = useTranslations("admin");
  const { can } = useStaffAccess();
  const { get, page, set, hrefWith } = useListParams();
  const days = (PERIODS as readonly string[]).includes(get("days")) ? get("days") : "7";
  const area = (AUDIT_AREAS as readonly string[]).includes(get("area")) ? get("area") : "";
  const actor = /^[0-9a-f-]{36}$/.test(get("who")) ? get("who") : "";
  const [now] = useState(() => Math.floor(Date.now() / 60_000) * 60_000);
  const from = days === "all" ? undefined : new Date(now - Number(days) * DAY).toISOString();
  // Names for the Who column; roles without staff:read see the sign-in name the record kept.
  const staff = useQuery({
    queryKey: ["admin", "staff", "all"],
    queryFn: () => must(browserApi.GET("/api/v1/staff", { params: { query: { size: 100 } } })),
    enabled: can("staff:read"),
    staleTime: 60_000,
  });
  const people = new Map((staff.data?.items ?? []).map((s) => [s.id, s]));
  const list = useQuery({
    queryKey: ["admin", "audit", { from, area, actor, page }],
    queryFn: () =>
      must(browserApi.GET("/api/v1/audit-logs", { params: { query: { from, entity_type: area || undefined, actor_user_id: actor || undefined, page, size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
  });
  const filtered = Boolean(area || actor || days !== "7");

  const who = (r: AuditEntry) => {
    const person = r.actor_user_id ? people.get(r.actor_user_id) : undefined;
    if (person) return { name: person.full_name || person.email || person.phone || "—", role: t(`shell.roles.${person.role}`) };
    if (r.actor_user_id) return { name: r.actor_identifier_snapshot || t("audit.unknown"), role: null };
    return { name: t("audit.system"), role: null };
  };
  const areaName = (type: string) => (t.has(`audit.areas.${type}`) ? t(`audit.areas.${type as (typeof AUDIT_AREAS)[number]}`) : type);
  const today = kigaliDay(new Date(now));
  const yesterday = kigaliDay(new Date(now - DAY));
  const dayLabel = (day: string, iso: string) => (day === today ? t("audit.today") : day === yesterday ? t("audit.yesterday") : formatDate(iso, "date"));

  // Consecutive entries of the same Kigali day share a heading.
  const groups: { day: string; label: string; items: AuditEntry[] }[] = [];
  for (const r of list.data?.items ?? []) {
    const day = kigaliDay(new Date(r.created_at));
    const last = groups[groups.length - 1];
    if (last?.day === day) last.items.push(r);
    else groups.push({ day, label: dayLabel(day, r.created_at), items: [r] });
  }

  return (
    <>
      <PageHeader title={t("audit.title")} description={t("audit.description")} />

      <section className="flex flex-wrap items-end gap-3 rounded-xl border border-bd bg-card p-4 shadow-sh">
        {can("staff:read") && (
          <Filter label={t("audit.whoLabel")}>
            {(id) => (
              <Select id={id} value={actor} onChange={(e) => set({ who: e.target.value })} className="h-10 text-sm">
                <option value="">{t("audit.allStaff")}</option>
                {(staff.data?.items ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.full_name || s.email || s.phone}
                  </option>
                ))}
              </Select>
            )}
          </Filter>
        )}
        <Filter label={t("audit.areaLabel")}>
          {(id) => (
            <Select id={id} value={area} onChange={(e) => set({ area: e.target.value })} className="h-10 text-sm">
              <option value="">{t("audit.allAreas")}</option>
              {AUDIT_AREAS.map((a) => (
                <option key={a} value={a}>
                  {t(`audit.areas.${a}`)}
                </option>
              ))}
            </Select>
          )}
        </Filter>
        <Filter label={t("audit.periodLabel")} className="sm:w-44">
          {(id) => (
            <Select id={id} value={days} onChange={(e) => set({ days: e.target.value === "7" ? null : e.target.value })} className="h-10 text-sm">
              {PERIODS.map((p) => (
                <option key={p} value={p}>
                  {t(`orders.periods.${p}`)}
                </option>
              ))}
            </Select>
          )}
        </Filter>
        <div className="ml-auto flex items-center gap-3 max-sm:w-full max-sm:justify-between">
          {list.data && (
            <span aria-live="polite" className="text-sm text-tx2 tabular-nums">
              {t("audit.count", { count: list.data.total })}
            </span>
          )}
          {filtered && (
            <Button variant="neutral" size="sm" onClick={() => set({ who: null, area: null, days: null })} className="gap-1.5">
              <X size={14} aria-hidden="true" />
              {t("audit.clearFilters")}
            </Button>
          )}
        </div>
      </section>

      <section aria-label={t("audit.title")} aria-busy={list.isFetching} className="overflow-hidden rounded-xl border border-bd bg-card shadow-sh">
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : !list.data ? (
          <div className="flex flex-col gap-3 p-5">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : list.data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <History size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{t("audit.empty")}</p>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.day}>
              <h2 className="m-0 border-b border-bd bg-page px-5 py-2 text-cap font-semibold tracking-wide text-tx2 uppercase max-sm:px-4">
                {group.label}
              </h2>
              <ol className="m-0 list-none p-0">
                {group.items.map((r) => (
                  <Entry key={r.id} entry={r} person={who(r)} area={areaName(r.entity_type)} />
                ))}
              </ol>
            </div>
          ))
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
    </>
  );
}

/** A labelled filter dropdown. */
function Filter({ label, className, children }: { label: string; className?: string; children: (id: string) => ReactNode }) {
  const id = `audit-filter-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className={cx("flex min-w-0 flex-col gap-1 max-sm:flex-1 sm:w-56", className)}>
      <label htmlFor={id} className="text-cap font-semibold text-tx2">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/** One timeline entry: time, area icon, who did what, and the change. */
function Entry({ entry: r, person, area }: { entry: AuditEntry; person: { name: string; role: string | null }; area: string }) {
  const t = useTranslations("admin.audit");
  const outcome = typeof r.change_summary.status === "string" ? r.change_summary.status : "success";
  const failed = outcome === "failure" || outcome === "denied";
  const { Icon, tone } = failed ? { Icon: ShieldAlert, tone: "bg-err-bg text-err-tx" } : (AREA_ICON[r.entity_type] ?? FALLBACK_ICON);
  const change = changeLine(r.change_summary);
  return (
    <li
      className={cx(
        "relative flex gap-4 border-b border-bd px-5 py-4 transition-colors duration-150 last:border-b-0 hover:bg-page motion-reduce:transition-none max-sm:gap-3 max-sm:px-4",
        failed && "bg-err-bg/30 before:absolute before:inset-y-0 before:left-0 before:w-1 before:bg-err before:content-['']",
      )}
    >
      <time dateTime={r.created_at} className="w-12 flex-none pt-2 font-mono text-cap text-tx2 tabular-nums">
        {formatDate(r.created_at, "time")}
      </time>
      <span aria-hidden="true" className={cx("flex size-9 flex-none items-center justify-center rounded-full", tone)}>
        <Icon size={17} />
      </span>
      <div className="flex min-w-0 grow flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <b className="font-semibold break-all text-tx">{person.name}</b>
          {person.role && <span className="text-cap text-tx2">· {person.role}</span>}
          <span className="text-tx2">—</span>
          <span className="font-medium text-tx">{actionLabel(r.action)}</span>
          {failed && <Badge tone="soft-err">{t(`outcome.${outcome as "failure" | "denied"}`)}</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="soft-neutral">{area}</Badge>
          <span className="font-mono text-cap text-tx2">{r.action}</span>
        </div>
        {change && <p className="m-0 w-fit max-w-full rounded-md bg-subtle px-2.5 py-1.5 font-mono text-cap break-words text-tx">{change}</p>}
        {r.note && <p className="m-0 text-sm text-tx">{r.note}</p>}
      </div>
    </li>
  );
}
