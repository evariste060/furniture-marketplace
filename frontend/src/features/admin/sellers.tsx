"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Store } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { EarningsCard } from "@/features/seller/dashboard";
import { percent } from "@/features/seller/store-context";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { formatDate, formatPhone } from "@/lib/format";
import { useStaffAccess } from "./access";
import { FilterBar, FilterTabs, ListFooter, LoadError, PageHeader, SearchBox, Thumb, must, useListParams } from "./ui";

type StoreSummary = components["schemas"]["StaffStoreSummary"];
type StoreDetail = components["schemas"]["StaffStoreDetail"];
export type StoreStatus = StoreSummary["status"];
export type StoreDecision = "approved" | "rejected" | "suspended";

export const STORE_STATUSES: readonly StoreStatus[] = ["pending", "approved", "rejected", "suspended"];
const PAGE_SIZE = 20;
const COLUMNS = 6;
export const REASON_MIN = 10;
export const REASON_MAX = 500;

export const STORE_TONE: Record<StoreStatus, BadgeTone> = {
  pending: "soft-warn",
  approved: "soft-ok",
  rejected: "soft-err",
  suspended: "soft-purple",
};

/** The administrator's decisions from each status, as the backend allows them
 * (store_service.STORE_TRANSITIONS); anything else is 409 invalid_store_transition. */
export function storeDecisions(status: StoreStatus): StoreDecision[] {
  if (status === "pending") return ["approved", "rejected"];
  if (status === "approved") return ["suspended"];
  if (status === "suspended") return ["approved"];
  return [];
}

/** Rejecting and suspending need a reason the seller sees (10-500 characters); approving and
 * reinstating take an optional note kept in the history. */
export function reasonProblem(decision: StoreDecision, reason: string): "required" | "short" | null {
  const text = reason.trim();
  const needed = decision !== "approved";
  if (!text) return needed ? "required" : null;
  return text.length < REASON_MIN ? "short" : null;
}

/** A commission override typed as a percentage (up to two decimals, 0-100) in whole basis points;
 * null when the text is not one. */
export function percentToBps(value: string): number | null {
  const text = value.trim().replace(",", ".");
  if (!/^\d{1,3}(\.\d{1,2})?$/.test(text)) return null;
  const bps = Math.round(Number(text) * 100);
  return bps <= 10000 ? bps : null;
}

const isStoreStatus = (value: string): value is StoreStatus => (STORE_STATUSES as readonly string[]).includes(value);

export function StoreStatusBadge({ status }: { status: StoreStatus }) {
  const t = useTranslations("admin.sellers.status");
  return <Badge tone={STORE_TONE[status]}>{t(status)}</Badge>;
}

/** /admin/sellers (ADR-014 phase 5): stores and applications, newest submission first, filtered
 * by status and by store, address or owner (both in the URL). */
export function SellersView() {
  const t = useTranslations("admin.sellers");
  const { get, page, set, hrefWith } = useListParams();
  const raw = get("status");
  const status = isStoreStatus(raw) ? raw : "";
  const q = get("q");
  const list = useQuery({
    queryKey: ["admin", "sellers", { status, q, page }],
    placeholderData: keepPreviousData,
    queryFn: () =>
      must(browserApi.GET("/api/v1/staff/sellers", { params: { query: { status: status || undefined, q: q || undefined, page, size: PAGE_SIZE } } })),
  });
  const rows = list.data?.items ?? [];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <section className="overflow-hidden rounded-xl border border-bd bg-card shadow-sh">
        <FilterTabs
          label={t("statusLabel")}
          items={[{ id: "", label: t("allStatuses") }, ...STORE_STATUSES.map((s) => ({ id: s, label: t(`status.${s}`) }))]}
          value={status}
          onChange={(id) => set({ status: id || null })}
        />
        <FilterBar>
          <SearchBox label={t("searchLabel")} placeholder={t("searchPlaceholder")} value={q} onSearch={(value) => set({ q: value })} />
          {list.data && (
            <span aria-live="polite" className="ml-auto text-sm text-tx2 tabular-nums">
              {t("count", { count: list.data.total })}
            </span>
          )}
        </FilterBar>
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <Store size={26} />
            </span>
            <p className="m-0 max-w-96 text-tx2">{status || q ? t("emptyFiltered") : t("empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.store")}</Th>
                <Th>{t("columns.owner")}</Th>
                <Th>{t("columns.district")}</Th>
                <Th>{t("columns.submitted")}</Th>
                <Th>{t("columns.reviewed")}</Th>
                <Th>{t("columns.status")}</Th>
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={COLUMNS}>
                        <Skeleton className="h-10 w-full" />
                      </Td>
                    </tr>
                  ))
                : rows.map((row) => (
                    <tr key={row.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                      <Td>
                        <NextLink href={`/admin/sellers/${row.id}`} className="font-semibold">
                          {row.name}
                        </NextLink>
                      </Td>
                      <Td>
                        <span className="flex flex-col">
                          <span>{row.owner.full_name ?? t("noName")}</span>
                          {row.owner.email && <span className="text-cap text-tx2">{row.owner.email}</span>}
                        </span>
                      </Td>
                      <Td>{row.district}</Td>
                      <Td className="whitespace-nowrap text-tx2">{formatDate(row.submitted_at)}</Td>
                      <Td className="whitespace-nowrap text-tx2">{row.reviewed_at ? formatDate(row.reviewed_at) : "—"}</Td>
                      <Td>
                        <StoreStatusBadge status={row.status} />
                      </Td>
                    </tr>
                  ))}
            </tbody>
          </Table>
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
    </>
  );
}

const detailKey = (id: string) => ["admin", "sellers", "detail", id] as const;

/** /admin/sellers/[id]: a store's application, profile, owner, commission, earnings and history,
 * with the decisions its status allows (sellers:manage). */
export function SellerDetailView({ id }: { id: string }) {
  const t = useTranslations("admin.sellers");
  const td = useTranslations("admin.seller.dashboard");
  const { can } = useStaffAccess();
  const manage = can("sellers:manage");
  const [decision, setDecision] = useState<StoreDecision | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const query = useQuery({
    queryKey: detailKey(id),
    retry: (count, error) => !(error instanceof ApiError && [404, 422].includes(error.status)) && count < 2,
    queryFn: () => must(browserApi.GET("/api/v1/staff/sellers/{store_id}", { params: { path: { store_id: id } } })),
  });
  const earnings = useQuery({
    queryKey: [...detailKey(id), "earnings"],
    enabled: query.isSuccess,
    queryFn: () => must(browserApi.GET("/api/v1/staff/sellers/{store_id}/earnings", { params: { path: { store_id: id } } })),
  });

  if (query.isError) {
    if (query.error instanceof ApiError && [404, 422].includes(query.error.status))
      return (
        <Card padding={32} className="flex flex-col items-start gap-3">
          <h1 className="t-h2">{t("notFound")}</h1>
          <NextLink href="/admin/sellers" className={buttonClasses({ variant: "neutral", size: "sm" })}>
            {t("back")}
          </NextLink>
        </Card>
      );
    return <LoadError onRetry={() => query.refetch()} />;
  }
  const store = query.data;
  if (!store) return <Skeleton className="h-[520px] w-full rounded-xl" />;
  const decisions = manage ? storeDecisions(store.status) : [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={store.name}
        back={{ label: t("back"), href: "/admin/sellers" }}
        badges={<StoreStatusBadge status={store.status} />}
        description={t("submitted", { date: formatDate(store.submitted_at) })}
        actions={
          <>
            {store.status === "approved" && (
              // The public store page is in the storefront: a new tab, full page load.
              <a href={`/store/${store.slug}`} target="_blank" rel="noopener" className={buttonClasses({ variant: "neutral", size: "sm" })}>
                <ExternalLink size={16} aria-hidden="true" />
                {t("viewStore")}
              </a>
            )}
            {decisions.map((d) => (
              <Button key={d} size="sm" variant={d === "approved" ? "primary" : d === "rejected" ? "danger-outline" : "danger"} onClick={() => setDecision(d)}>
                {t(`decide.${store.status === "suspended" ? "reinstate" : d}`)}
              </Button>
            ))}
          </>
        }
      />
      {notice && (
        <p role="alert" className="m-0 rounded-lg bg-err-bg px-4 py-3 text-sm text-err-tx">
          {notice}
        </p>
      )}
      {store.status_reason && (
        <p className="m-0 rounded-lg bg-warn-bg px-4 py-3 text-sm text-warn-tx">{t("currentReason", { reason: store.status_reason })}</p>
      )}
      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <StoreCard store={store} />
          <HistoryCard store={store} />
        </div>
        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
          <OwnerCard store={store} />
          <CommissionCard store={store} manage={manage} />
          {store.approved_at && (
            <>
              <EarningsCard title={td("pending")} hint={t("pendingHint")} bucket={earnings.data?.pending} netLabel={t("sellerShare")} />
              <EarningsCard title={td("earned")} hint={t("earnedHint")} bucket={earnings.data?.earned} netLabel={t("sellerShare")} />
            </>
          )}
        </div>
      </div>
      {decision && <DecisionDialog store={store} decision={decision} onClose={() => setDecision(null)} onError={setNotice} />}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
      <dt className="w-36 flex-none text-tx2">{label}</dt>
      <dd className="m-0 min-w-0 break-words">{children}</dd>
    </div>
  );
}

function StoreCard({ store }: { store: StoreDetail }) {
  const t = useTranslations("admin.sellers");
  const address = [store.street_address, store.sector, store.district].filter(Boolean).join(", ");
  return (
    <Card padding={24} className="flex flex-col gap-4">
      <h2 className="t-h3">{t("storeTitle")}</h2>
      <div className="flex items-center gap-4">
        <Thumb image={store.logo} size={64} alt={t("logo")} />
        {store.cover && <Thumb image={store.cover} size={64} alt={t("cover")} />}
      </div>
      <dl className="m-0 flex flex-col gap-3 text-sm">
        <Row label={t("fields.slug")}>{store.slug}</Row>
        <Row label={t("fields.description")}>{store.description ? <span className="whitespace-pre-line">{store.description}</span> : "—"}</Row>
        <Row label={t("fields.address")}>{address}</Row>
        <Row label={t("fields.email")}>
          <a href={`mailto:${store.contact_email}`}>{store.contact_email}</a>
        </Row>
        <Row label={t("fields.phone")}>
          <a href={`tel:${store.contact_phone}`}>{formatPhone(store.contact_phone)}</a>
        </Row>
        <Row label={t("fields.approved")}>{store.approved_at ? formatDate(store.approved_at) : "—"}</Row>
      </dl>
    </Card>
  );
}

function OwnerCard({ store }: { store: StoreDetail }) {
  const t = useTranslations("admin.sellers");
  const { owner } = store;
  return (
    <Card padding={24} className="flex flex-col gap-3">
      <h2 className="t-h3">{t("ownerTitle")}</h2>
      <dl className="m-0 flex flex-col gap-3 text-sm">
        <Row label={t("fields.name")}>{owner.full_name ?? t("noName")}</Row>
        <Row label={t("fields.email")}>{owner.email ?? "—"}</Row>
        <Row label={t("fields.phone")}>{owner.phone ? formatPhone(owner.phone) : "—"}</Row>
      </dl>
    </Card>
  );
}

function HistoryCard({ store }: { store: StoreDetail }) {
  const t = useTranslations("admin.sellers");
  return (
    <Card padding="none" className="overflow-hidden">
      <h2 className="t-h3 px-6 pt-5 pb-3">{t("historyTitle")}</h2>
      <Table>
        <thead>
          <tr>
            <Th>{t("history.when")}</Th>
            <Th>{t("history.status")}</Th>
            <Th>{t("history.by")}</Th>
            <Th>{t("history.reason")}</Th>
          </tr>
        </thead>
        <tbody>
          {store.history.map((entry, i) => (
            <tr key={i}>
              <Td className="whitespace-nowrap text-tx2">{formatDate(entry.created_at, "dateTime")}</Td>
              <Td>
                <StoreStatusBadge status={entry.status} />
              </Td>
              <Td>{entry.actor ? (entry.actor.full_name ?? t("noName")) : t("history.owner")}</Td>
              <Td className="text-tx2">{entry.reason ?? "—"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

function CommissionCard({ store, manage }: { store: StoreDetail; manage: boolean }) {
  const t = useTranslations("admin.sellers.commission");
  const client = useQueryClient();
  const toast = useToast();
  const [value, setValue] = useState(store.commission_rate_bps === null ? "" : percent(store.commission_rate_bps));
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (bps: number | null) =>
      must(browserApi.PATCH("/api/v1/staff/sellers/{store_id}/commission", { params: { path: { store_id: store.id } }, body: { commission_rate_bps: bps } })),
    onSuccess: (saved) => {
      client.setQueryData(detailKey(store.id), saved);
      setValue(saved.commission_rate_bps === null ? "" : percent(saved.commission_rate_bps));
      setError(null);
      toast.show(t("saved", { rate: percent(saved.effective_commission_rate_bps) }));
    },
    onError: () => setError(t("failed")),
  });
  const submit = () => {
    if (!value.trim()) return save.mutate(null);
    const bps = percentToBps(value);
    if (bps === null) return setError(t("invalid"));
    save.mutate(bps);
  };
  return (
    <Card padding={24} className="flex flex-col gap-3">
      <h2 className="t-h3">{t("title")}</h2>
      <p className="m-0 text-sm">
        {t(store.commission_rate_bps === null ? "inherits" : "override", { rate: percent(store.effective_commission_rate_bps) })}
      </p>
      {manage && (
        <form
          noValidate
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field label={t("label")} help={t("help")} error={error ?? undefined}>
            {(c) => <Input {...c} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} className="max-w-32" />}
          </Field>
          <Button type="submit" size="sm" variant="neutral" disabled={save.isPending} className="w-fit">
            {t("save")}
          </Button>
        </form>
      )}
    </Card>
  );
}

function DecisionDialog({ store, decision, onClose, onError }: { store: StoreDetail; decision: StoreDecision; onClose: () => void; onError: (message: string | null) => void }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<"required" | "short" | null>(null);
  const action = store.status === "suspended" ? "reinstate" : decision;
  const label = t(`sellers.decide.${action}`);
  const move = useMutation({
    mutationFn: () =>
      must(
        browserApi.PATCH("/api/v1/staff/sellers/{store_id}/status", {
          params: { path: { store_id: store.id } },
          body: { status: decision, reason: reason.trim() || null },
        }),
      ),
    onSuccess: (saved) => {
      client.setQueryData(detailKey(store.id), saved);
      void client.invalidateQueries({ queryKey: ["admin", "sellers"] });
      void client.invalidateQueries({ queryKey: ["admin", "count", "sellers-pending"] });
      onError(null);
      toast.show(t("sellers.decided", { store: saved.name, status: t(`sellers.status.${saved.status}`) }));
      onClose();
    },
    onError: (e) => {
      const stale = e instanceof ApiError && e.code === "invalid_store_transition";
      onError(t(stale ? "sellers.errors.stale" : "sellers.errors.failed"));
      if (stale) void client.invalidateQueries({ queryKey: detailKey(store.id) });
      onClose();
    },
  });
  const submit = () => {
    const found = reasonProblem(decision, reason);
    setProblem(found);
    if (!found) move.mutate();
  };
  const needed = decision !== "approved";
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("sellers.confirmTitle", { action: label, store: store.name })}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant={decision === "approved" ? "primary" : "danger"} disabled={move.isPending} onClick={submit}>
            {label}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="m-0 text-tx2">{t(`sellers.confirmBody.${action}`)}</p>
        <Field
          label={
            <>
              {t(needed ? "sellers.reasonLabel" : "sellers.noteLabel")} {!needed && <span className="font-normal text-tx2">{t("common.optional")}</span>}
            </>
          }
          help={t(needed ? "sellers.reasonHelp" : "sellers.noteHelp")}
          error={problem ? t(`sellers.errors.${problem}`) : undefined}
        >
          {(c) => <Textarea {...c} rows={3} maxLength={REASON_MAX} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
    </Dialog>
  );
}
