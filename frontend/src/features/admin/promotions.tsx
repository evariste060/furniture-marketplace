"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, CalendarRange, CirclePause, Clock, Pencil, Percent, Plus, Tag, TicketPercent, Zap, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, RadioOption, Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate, formatMoney, KIGALI_TIME_ZONE } from "@/lib/format";
import { useStaffAccess } from "./access";
import { groupDigits, parseAmount } from "./numbers";
import { bodyFieldErrors, LoadError, must, PageHeader, useListParams } from "./ui";

type Promotion = components["schemas"]["PromotionResponse"];
type Phase = "active" | "scheduled" | "expired" | "off";

const CODE = /^[A-Z0-9][A-Z0-9_-]*$/;
const PHASES = ["active", "scheduled", "expired", "off"] as const;

/** Where a promotion stands now: off (draft or disabled), scheduled, active or expired. */
export function promotionPhase(p: Pick<Promotion, "status" | "starts_at" | "ends_at">, now: number): Phase {
  if (p.status !== "active") return "off";
  if (p.starts_at && Date.parse(p.starts_at) > now) return "scheduled";
  if (p.ends_at && Date.parse(p.ends_at) <= now) return "expired";
  return "active";
}

/** "2026-11-30" (the last valid day) ↔ the API's exclusive end, midnight Kigali time the day after. */
export function endFromDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  const next = new Date(Date.UTC(y, m - 1, d + 1));
  return `${next.toISOString().slice(0, 10)}T00:00:00`;
}
export function dayFromEnd(endsAt: string): string {
  return kigaliDay(new Date(Date.parse(endsAt) - 1000));
}
export function kigaliDay(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: KIGALI_TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

const PHASE_TONE: Record<Phase, BadgeTone> = { active: "soft-ok", scheduled: "soft-info", expired: "soft-neutral", off: "soft-warn" };
/** The phase tiles above the table: icon and its colours. */
const PHASE_TILE: Record<Phase, { Icon: LucideIcon; tone: string }> = {
  active: { Icon: Zap, tone: "bg-ok-bg text-ok-tx" },
  scheduled: { Icon: Clock, tone: "bg-light text-pri-h" },
  expired: { Icon: CalendarDays, tone: "bg-subtle text-tx2" },
  off: { Icon: CirclePause, tone: "bg-warn-bg text-warn-tx" },
};

async function allPromotions(): Promise<Promotion[]> {
  const out: Promotion[] = [];
  for (let page = 1; page <= 50; page += 1) {
    const data = await must(browserApi.GET("/api/v1/staff/promotions", { params: { query: { page, size: 100 } } }));
    out.push(...data.items);
    if (out.length >= data.total || data.items.length === 0) break;
  }
  return out;
}

/** Promotions.dc.html: phase tiles that filter the table, and the create/edit form in a dialog.
 * `?new=1` (the dashboard's "New promotion" quick action) opens the form for a new one. */
export function PromotionsView() {
  const t = useTranslations("admin.promotions");
  const { can } = useStaffAccess();
  const manage = can("promotions:manage");
  const { get, set } = useListParams();
  const query = useQuery({ queryKey: ["admin", "promotions"], queryFn: allPromotions });
  const categories = useQuery({ queryKey: ["admin", "categories"], queryFn: () => must(browserApi.GET("/api/v1/staff/categories")), enabled: can("catalog:read"), staleTime: 60_000 });
  const brands = useQuery({ queryKey: ["admin", "brands"], queryFn: () => must(browserApi.GET("/api/v1/staff/brands")), enabled: can("catalog:read"), staleTime: 60_000 });
  const [phase, setPhase] = useState<Phase>("active");
  const [form, setForm] = useState<Promotion | "new" | null>(() => (manage && get("new") === "1" ? "new" : null));
  const [now] = useState(() => Date.now());
  const all = query.data ?? [];
  const count = (p: Phase) => all.filter((x) => promotionPhase(x, now) === p).length;
  const rows = all.filter((x) => promotionPhase(x, now) === phase);
  const names = new Map<string, string>([...(categories.data?.items ?? []).map((c) => [c.id, c.name] as const), ...(brands.data?.items ?? []).map((b) => [b.id, b.name] as const)]);

  const appliesTo = (p: Promotion) => {
    if (p.applies_to === "all") return t("allProducts");
    const target = p.targets[0];
    if (p.targets.length === 1 && target.category_id) return t("categoryTarget", { name: names.get(target.category_id) ?? "…" });
    if (p.targets.length === 1 && target.brand_id) return t("brandTarget", { name: names.get(target.brand_id) ?? "…" });
    return t("targets", { count: p.targets.length });
  };
  const close = () => {
    setForm(null);
    if (get("new")) set({ new: null });
  };
  const newButton = (
    <Button size="sm" onClick={() => setForm("new")} className="gap-1.5">
      <Plus size={16} aria-hidden="true" />
      {t("new")}
    </Button>
  );

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} actions={manage && newButton} />

      {/* The phases: each tile filters the table below (toggle buttons, like the other admin tabs). */}
      <div role="group" aria-label={t("tabsLabel")} className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {PHASES.map((p) => {
          const on = p === phase;
          const { Icon, tone } = PHASE_TILE[p];
          return (
            <button
              key={p}
              type="button"
              aria-pressed={on}
              onClick={() => setPhase(p)}
              className={cx(
                "flex cursor-pointer items-center gap-3 rounded-xl border p-4 text-left shadow-sh transition-[border-color,box-shadow,background-color] duration-150 motion-reduce:transition-none",
                on ? "border-pri bg-light ring-1 ring-pri" : "border-bd bg-card hover:border-bd2 hover:shadow-sh2",
              )}
            >
              <span aria-hidden="true" className={cx("flex size-10 flex-none items-center justify-center rounded-lg", tone)}>
                <Icon size={20} />
              </span>
              <span className="flex min-w-0 flex-col">
                <span className={cx("truncate text-sm font-medium", on ? "text-pri-h" : "text-tx2")}>{t(`tiles.${p}`)}</span>
                {query.data ? <b className="t-h2 tabular-nums">{count(p)}</b> : <Skeleton className="mt-1 h-7 w-8" />}
              </span>
            </button>
          );
        })}
      </div>

      <section className="min-w-0 overflow-hidden rounded-xl border border-bd bg-card shadow-sh">
        {query.isError ? (
          <LoadError onRetry={() => query.refetch()} className="m-5" />
        ) : query.data && rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <TicketPercent size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{t(`empty.${phase}`)}</p>
            {manage && newButton}
          </div>
        ) : (
          <Table aria-busy={query.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.name")}</Th>
                <Th>{t("columns.value")}</Th>
                <Th>{t("columns.appliesTo")}</Th>
                <Th>{t("columns.valid")}</Th>
                <Th>{t("columns.used")}</Th>
                <Th>{t("columns.status")}</Th>
                {manage && (
                  <Th>
                    <span className="sr-only">{t("edit")}</span>
                  </Th>
                )}
              </tr>
            </thead>
            <tbody>
              {!query.data
                ? Array.from({ length: 4 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={manage ? 7 : 6}>
                        <Skeleton className="h-10 w-full" />
                      </Td>
                    </tr>
                  ))
                : rows.map((p) => {
                    const limit = p.usage_limit_total;
                    const percent = limit ? Math.min(100, Math.round((p.active_redemptions / limit) * 100)) : 0;
                    const status = promotionPhase(p, now);
                    return (
                      <tr key={p.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                        <Td>
                          <span className="flex items-center gap-3">
                            <span aria-hidden="true" className="flex size-10 flex-none items-center justify-center rounded-lg bg-err-bg text-err-tx">
                              {p.kind === "percent" ? <Percent size={18} /> : <Tag size={18} />}
                            </span>
                            <span className="flex min-w-0 flex-col items-start gap-1">
                              {manage ? (
                                <button type="button" onClick={() => setForm(p)} className="cursor-pointer border-0 bg-transparent p-0 text-left font-semibold text-tx hover:text-pri-h">
                                  {p.name}
                                </button>
                              ) : (
                                <b className="font-semibold">{p.name}</b>
                              )}
                              <span className="rounded-md border border-dashed border-bd2 bg-page px-1.5 py-px font-mono text-cap font-semibold tracking-wide text-tx">
                                <span className="sr-only">{t("codeType")}: </span>
                                {p.code}
                              </span>
                            </span>
                          </span>
                        </Td>
                        <Td>
                          <span className="inline-flex rounded-full bg-err-bg px-2.5 py-1 text-sm font-semibold whitespace-nowrap text-err-tx">
                            {t("off", { value: p.kind === "percent" ? `${p.percent_off}%` : formatMoney(p.amount_off ?? 0) })}
                          </span>
                        </Td>
                        <Td className="text-tx2">{appliesTo(p)}</Td>
                        <Td>
                          <span className="flex items-center gap-1.5 text-sm whitespace-nowrap text-tx2">
                            <CalendarRange size={15} aria-hidden="true" className="flex-none" />
                            {!p.starts_at && !p.ends_at
                              ? t("ongoing")
                              : `${p.starts_at ? formatDate(p.starts_at, "date") : t("now")} – ${p.ends_at ? formatDate(new Date(Date.parse(p.ends_at) - 1000), "date") : t("noEnd")}`}
                          </span>
                        </Td>
                        <Td>
                          <span className="flex min-w-[100px] flex-col gap-1.5">
                            <span className="text-cap font-medium tabular-nums">{limit ? t("usedOf", { used: p.active_redemptions, limit }) : t("used", { used: p.active_redemptions })}</span>
                            {limit ? (
                              <span className="h-1.5 overflow-hidden rounded-full bg-subtle">
                                <span className={cx("block h-full rounded-full", percent >= 90 ? "bg-err" : "bg-pri")} style={{ width: `${percent}%` }} />
                              </span>
                            ) : null}
                          </span>
                        </Td>
                        <Td>
                          <Badge tone={PHASE_TONE[status]}>{status === "off" ? t(`status.${p.status}`) : t(`phase.${status}`)}</Badge>
                        </Td>
                        {manage && (
                          <Td className="text-right">
                            <Button variant="neutral" size="sm" onClick={() => setForm(p)} aria-label={t("editNamed", { name: p.name })} className="gap-1.5">
                              <Pencil size={14} aria-hidden="true" />
                              {t("editShort")}
                            </Button>
                          </Td>
                        )}
                      </tr>
                    );
                  })}
            </tbody>
          </Table>
        )}
      </section>

      {manage && form && (
        <PromotionForm
          key={form === "new" ? "new" : form.id}
          promotion={form === "new" ? null : form}
          categories={categories.data?.items ?? []}
          brands={brands.data?.items ?? []}
          onClose={close}
        />
      )}
    </>
  );
}

type Target = "all" | `category:${string}` | `brand:${string}` | "keep";

function PromotionForm({
  promotion,
  categories,
  brands,
  onClose,
}: {
  promotion: Promotion | null;
  categories: components["schemas"]["StaffCategoryItem"][];
  brands: components["schemas"]["StaffBrandItem"][];
  onClose: () => void;
}) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const formId = useId();
  const first = promotion?.targets[0];
  const initialTarget: Target = !promotion
    ? "all"
    : promotion.applies_to === "all"
      ? "all"
      : promotion.targets.length === 1 && first?.category_id
        ? `category:${first.category_id}`
        : promotion.targets.length === 1 && first?.brand_id
          ? `brand:${first.brand_id}`
          : "keep";
  const [name, setName] = useState(promotion?.name ?? "");
  const [code, setCode] = useState(promotion?.code ?? "");
  const [kind, setKind] = useState<"percent" | "fixed">(promotion?.kind ?? "percent");
  const [value, setValue] = useState(promotion ? String(promotion.kind === "percent" ? promotion.percent_off : groupDigits(promotion.amount_off ?? 0)) : "");
  const [target, setTarget] = useState<Target>(initialTarget);
  const [starts, setStarts] = useState(promotion?.starts_at ? kigaliDay(new Date(promotion.starts_at)) : "");
  const [ends, setEnds] = useState(promotion?.ends_at ? dayFromEnd(promotion.ends_at) : "");
  const [minOrder, setMinOrder] = useState(promotion?.min_subtotal ? groupDigits(promotion.min_subtotal) : "");
  const [limit, setLimit] = useState(promotion?.usage_limit_total ? String(promotion.usage_limit_total) : "");
  const [onePerPhone, setOnePerPhone] = useState(promotion ? promotion.usage_limit_per_customer === 1 : true);
  const [status, setStatus] = useState<Promotion["status"]>(promotion?.status ?? "active");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => {
      const amount = kind === "percent" ? Number(value.trim()) : parseAmount(value);
      const body = {
        name: name.trim(),
        code: code.trim().toUpperCase(),
        kind,
        percent_off: kind === "percent" ? amount : null,
        amount_off: kind === "fixed" ? amount : null,
        status,
        starts_at: starts ? `${starts}T00:00:00` : null,
        ends_at: ends ? endFromDay(ends) : null,
        min_subtotal: minOrder.trim() ? (parseAmount(minOrder) ?? 0) : 0,
        usage_limit_total: limit.trim() ? Number(limit.trim()) : null,
        usage_limit_per_customer: onePerPhone ? 1 : null,
        ...(target === "keep"
          ? {}
          : target === "all"
            ? { applies_to: "all" as const, targets: [] }
            : {
                applies_to: "targets" as const,
                targets: [target.startsWith("category:") ? { category_id: target.slice(9) } : { brand_id: target.slice(6) }],
              }),
      };
      if (!promotion) return must(browserApi.POST("/api/v1/staff/promotions", { body: { applies_to: "all", ...body } }));
      return must(browserApi.PATCH("/api/v1/staff/promotions/{promotion_id}", { params: { path: { promotion_id: promotion.id } }, body }));
    },
    onSuccess: () => {
      toast.show(promotion ? t("common.saved") : t("promotions.created"));
      void client.invalidateQueries({ queryKey: ["admin", "promotions"] });
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "promotion_code_taken") setErrors({ code: t("promotions.errors.codeTaken") });
      else if (error instanceof ApiError && error.code === "invalid_status_transition") setErrors({ status: t("promotions.errors.backToDraft") });
      else if (error instanceof ApiError && error.status === 422) setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
    },
  });

  const submit = () => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = t("catalogue.errors.name");
    if (!CODE.test(code.trim().toUpperCase())) found.code = t("promotions.errors.code");
    if (kind === "percent" ? !/^\d+$/.test(value.trim()) || Number(value) < 1 || Number(value) > 100 : !parseAmount(value)) found.value = t(kind === "percent" ? "promotions.errors.percent" : "promotions.errors.amount");
    if (starts && ends && ends < starts) found.ends_at = t("promotions.errors.dates");
    if (minOrder.trim() && parseAmount(minOrder) === null) found.min_subtotal = t("editor.errors.price");
    if (limit.trim() && (!/^\d+$/.test(limit.trim()) || Number(limit) < 1)) found.usage_limit_total = t("promotions.errors.limit");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={promotion ? t("promotions.edit") : t("promotions.new")}
      closeLabel={t("common.close")}
      className="max-w-[640px]"
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={save.isPending}>
            {promotion ? t("common.saveChanges") : t("promotions.create")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        aria-label={promotion ? t("promotions.edit") : t("promotions.new")}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="-mx-6 flex max-h-[calc(100dvh-210px)] flex-col divide-y divide-bd overflow-y-auto overscroll-contain border-y border-bd"
      >
        <FormSection title={t("promotions.sections.details")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("promotions.name")} error={errors.name}>
              {(c) => <Input {...c} maxLength={160} value={name} onChange={(e) => setName(e.target.value)} />}
            </Field>
            <Field label={t("promotions.code")} error={errors.code} help={errors.code ? undefined : t("promotions.codeHelp")}>
              {(c) => <Input {...c} maxLength={40} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} className="font-mono uppercase" />}
            </Field>
          </div>
        </FormSection>

        <FormSection title={t("promotions.sections.discount")}>
          <div role="radiogroup" aria-label={t("promotions.kind")} className="grid grid-cols-2 gap-2.5">
            {(["percent", "fixed"] as const).map((k) => (
              <RadioOption
                key={k}
                name="kind"
                checked={kind === k}
                onChange={() => {
                  setKind(k);
                  setValue("");
                }}
                className="px-3 py-2.5 has-checked:px-[11px] has-checked:py-[9px]"
                label={
                  <span className="flex items-center gap-2 text-sm font-medium">
                    {k === "percent" ? <Percent size={16} aria-hidden="true" /> : <Tag size={16} aria-hidden="true" />}
                    {t(`promotions.kinds.${k}`)}
                  </span>
                }
              />
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("promotions.discount")} error={errors.value ?? errors.percent_off ?? errors.amount_off}>
              {(c) => (
                <div className="flex h-11 items-center overflow-hidden rounded-lg border border-bd bg-card focus-within:border-pri focus-within:shadow-focus">
                  {kind === "fixed" && <span className="flex h-full items-center border-r border-bd bg-page px-3 text-sm font-medium text-tx2">RWF</span>}
                  <input {...c} inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} className="h-full min-w-0 flex-1 border-0 px-3.5 text-base outline-none" />
                  {kind === "percent" && <span className="flex h-full items-center border-l border-bd bg-page px-3 text-sm font-medium text-tx2">%</span>}
                </div>
              )}
            </Field>
            <Field label={t("promotions.appliesTo")} error={errors.targets}>
              {(c) => (
                <Select {...c} value={target} onChange={(e) => setTarget(e.target.value as Target)}>
                  <option value="all">{t("promotions.allProducts")}</option>
                  {target === "keep" && <option value="keep">{t("promotions.keepTargets")}</option>}
                  <optgroup label={t("promotions.categories")}>
                    {categories.map((cat) => (
                      <option key={cat.id} value={`category:${cat.id}`}>
                        {t("promotions.categoryTarget", { name: cat.name })}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label={t("promotions.brands")}>
                    {brands.map((b) => (
                      <option key={b.id} value={`brand:${b.id}`}>
                        {t("promotions.brandTarget", { name: b.name })}
                      </option>
                    ))}
                  </optgroup>
                </Select>
              )}
            </Field>
          </div>
        </FormSection>

        <FormSection title={t("promotions.sections.schedule")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("promotions.starts")} error={errors.starts_at}>
              {(c) => <Input {...c} type="date" value={starts} onChange={(e) => setStarts(e.target.value)} />}
            </Field>
            <Field label={t("promotions.ends")} error={errors.ends_at}>
              {(c) => <Input {...c} type="date" value={ends} min={starts || undefined} onChange={(e) => setEnds(e.target.value)} />}
            </Field>
          </div>
        </FormSection>

        <FormSection title={t("promotions.sections.limits")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("promotions.minOrder")} error={errors.min_subtotal}>
              {(c) => <Input {...c} inputMode="numeric" placeholder="RWF 0" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} />}
            </Field>
            <Field label={t("promotions.limit")} error={errors.usage_limit_total}>
              {(c) => <Input {...c} inputMode="numeric" placeholder={t("promotions.noLimit")} value={limit} onChange={(e) => setLimit(e.target.value)} />}
            </Field>
          </div>
          <Checkbox label={t("promotions.onePerPhone")} checked={onePerPhone} onChange={(e) => setOnePerPhone(e.target.checked)} />
        </FormSection>

        <FormSection title={t("promotions.sections.status")}>
          <Field label={t("promotions.statusLabel")} error={errors.status} className="sm:max-w-[calc(50%-6px)]">
            {(c) => (
              <Select {...c} value={status} onChange={(e) => setStatus(e.target.value as Promotion["status"])}>
                {(promotion && promotion.status !== "draft" ? (["active", "disabled"] as const) : (["active", "draft", "disabled"] as const)).map((s) => (
                  <option key={s} value={s}>
                    {t(`promotions.status.${s}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </FormSection>
      </form>
    </Dialog>
  );
}

/** A titled group of fields in the promotion dialog. */
function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 px-6 py-4">
      <legend className="t-over float-left mb-1 p-0 text-tx2">{title}</legend>
      {children}
    </fieldset>
  );
}
