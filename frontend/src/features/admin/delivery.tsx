"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { Toggle } from "@/components/ui/toggle";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { formatDate, formatMoney } from "@/lib/format";
import { useStaffAccess } from "./access";
import { groupDigits, parseAmount } from "./numbers";
import { bodyFieldErrors, EmptyRow, LoadError, must, PageHeader } from "./ui";

type Zone = components["schemas"]["StaffDeliveryZone"];
type District = Zone["district"];

export const DISTRICTS: District[] = ["Gasabo", "Kicukiro", "Nyarugenge"];
export const THRESHOLD_KEY = "delivery.free_delivery_threshold";
const CODE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** A setting's value from GET /staff/settings, if it is a number. */
export function numberSetting(items: readonly { key: string; value: unknown }[] | undefined, key: string): number | null {
  const value = items?.find((i) => i.key === key)?.value;
  return typeof value === "number" ? value : null;
}

/** Delivery.dc.html */
export function DeliveryView() {
  const t = useTranslations("admin.delivery");
  const { can } = useStaffAccess();
  const manage = can("delivery:manage");
  const zones = useQuery({ queryKey: ["admin", "zones"], queryFn: () => must(browserApi.GET("/api/v1/staff/delivery/zones")) });
  const [editing, setEditing] = useState<Zone | "new" | null>(null);
  const items = zones.data?.items ?? [];
  const free = DISTRICTS.filter((d) => !items.some((z) => z.district === d));
  const columns = manage ? 6 : 5;

  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          manage &&
          zones.data &&
          free.length > 0 && (
            <Button size="sm" onClick={() => setEditing("new")}>
              {t("addZone")}
            </Button>
          )
        }
      />
      {can("settings:read") && <ThresholdCard />}
      <section className="overflow-hidden rounded-xl border border-bd bg-card">
        {zones.isError ? (
          <LoadError onRetry={() => zones.refetch()} className="m-5" />
        ) : (
          <Table aria-busy={zones.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.zone")}</Th>
                <Th>{t("columns.district")}</Th>
                <Th>{t("columns.fee")}</Th>
                <Th>{t("columns.cod")}</Th>
                <Th>{t("columns.active")}</Th>
                {manage && (
                  <Th>
                    <span className="sr-only">{t("columns.actions")}</span>
                  </Th>
                )}
              </tr>
            </thead>
            <tbody>
              {!zones.data ? (
                Array.from({ length: 3 }, (_, i) => (
                  <tr key={i}>
                    <Td colSpan={columns}>
                      <Skeleton className="h-8 w-full" />
                    </Td>
                  </tr>
                ))
              ) : items.length === 0 ? (
                <EmptyRow colSpan={columns}>{t("empty")}</EmptyRow>
              ) : (
                items.map((zone) => (
                  <tr key={zone.id}>
                    <Td>
                      <span className="flex flex-col">
                        <b className="font-medium">{zone.name}</b>
                        <span className="text-cap text-tx2">{zone.code}</span>
                      </span>
                    </Td>
                    <Td className="text-tx2">{zone.district}</Td>
                    <Td className="font-medium whitespace-nowrap">{zone.fee === null ? "—" : zone.fee === 0 ? t("free") : formatMoney(zone.fee)}</Td>
                    <Td>
                      <Badge tone={zone.cod_available ? "soft-ok" : "soft-neutral"}>{zone.cod_available ? t("codOn") : t("codOff")}</Badge>
                    </Td>
                    <Td>
                      <ZoneToggle zone={zone} disabled={!manage} />
                    </Td>
                    {manage && (
                      <Td>
                        <button
                          type="button"
                          aria-label={t("editOf", { name: zone.name })}
                          onClick={() => setEditing(zone)}
                          className="flex size-[30px] cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-tx2 hover:bg-page"
                        >
                          <Pencil size={15} aria-hidden="true" />
                        </button>
                      </Td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </Table>
        )}
      </section>
      <p className="text-sm text-tx2">{t("outsideNote")}</p>
      {editing && <ZoneDialog zone={editing === "new" ? null : editing} districts={editing === "new" ? free : DISTRICTS} onClose={() => setEditing(null)} />}
    </>
  );
}

function ThresholdCard() {
  const t = useTranslations("admin");
  const { can } = useStaffAccess();
  const client = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => must(browserApi.GET("/api/v1/staff/settings")) });
  const current = numberSetting(settings.data?.items, THRESHOLD_KEY);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const value = text ?? (current === null ? "" : groupDigits(current));
  const save = useMutation({
    mutationFn: (amount: number) => must(browserApi.PATCH("/api/v1/staff/settings", { body: { [THRESHOLD_KEY]: amount } })),
    onSuccess: () => {
      toast.show(t("common.saved"));
      setText(null);
      void client.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
    onError: () => toast.show(t("common.saveError"), "error"),
  });
  const manage = can("settings:manage");
  return (
    <Card padding={20} className="flex flex-wrap items-end gap-5">
      <Field label={t("delivery.threshold")} error={error ?? undefined} help={current === null && settings.data ? t("delivery.thresholdUnset") : t("delivery.thresholdHelp")} className="w-[300px] max-w-full">
        {(c) => (
          <div className="flex h-11 items-center overflow-hidden rounded-lg border border-bd bg-card focus-within:border-pri">
            <span className="flex h-full items-center border-r border-bd bg-page px-3 text-sm font-medium text-tx2">RWF</span>
            <input
              {...c}
              inputMode="numeric"
              disabled={!manage || !settings.data}
              value={value}
              onChange={(e) => setText(e.target.value)}
              className="h-full min-w-0 flex-1 border-0 px-3.5 text-base outline-none disabled:bg-subtle"
            />
          </div>
        )}
      </Field>
      {manage && (
        <Button
          variant="secondary"
          disabled={save.isPending || text === null}
          onClick={() => {
            const amount = parseAmount(value);
            if (amount === null) return setError(t("editor.errors.price"));
            setError(null);
            save.mutate(amount);
          }}
        >
          {t("delivery.saveSettings")}
        </Button>
      )}
    </Card>
  );
}

function ZoneToggle({ zone, disabled }: { zone: Zone; disabled: boolean }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const change = useMutation({
    mutationFn: (is_active: boolean) => must(browserApi.PATCH("/api/v1/staff/delivery/zones/{zone_id}", { params: { path: { zone_id: zone.id } }, body: { is_active } })),
    onSuccess: () => {
      toast.show(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["admin", "zones"] });
    },
    onError: () => toast.show(t("common.saveError"), "error"),
  });
  return (
    <Toggle
      checked={zone.is_active}
      disabled={disabled || change.isPending}
      onChange={(next) => change.mutate(next)}
      label={<span className="sr-only">{t("delivery.activeOf", { name: zone.name })}</span>}
    />
  );
}

function ZoneDialog({ zone, districts, onClose }: { zone: Zone | null; districts: District[]; onClose: () => void }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const [code, setCode] = useState("");
  const [name, setName] = useState(zone?.name ?? "");
  const [district, setDistrict] = useState<District>(zone?.district ?? districts[0]);
  const [fee, setFee] = useState(zone?.fee == null ? "" : groupDigits(zone.fee));
  const [cod, setCod] = useState(zone?.cod_available ?? true);
  const [sortOrder, setSortOrder] = useState(String(zone?.sort_order ?? 0));
  const [active, setActive] = useState(zone?.is_active ?? true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => {
      const common = { name: name.trim(), fee: parseAmount(fee)!, cod_available: cod, sort_order: Number(sortOrder), is_active: active };
      if (!zone) return must(browserApi.POST("/api/v1/staff/delivery/zones", { body: { ...common, code: code.trim(), district } }));
      return must(browserApi.PATCH("/api/v1/staff/delivery/zones/{zone_id}", { params: { path: { zone_id: zone.id } }, body: common }));
    },
    onSuccess: () => {
      toast.show(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["admin", "zones"] });
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) setErrors({ code: t("delivery.errors.taken") });
      else if (error instanceof ApiError && error.status === 422) setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
    },
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (!zone && !CODE.test(code.trim())) found.code = t("delivery.errors.code");
    if (!name.trim()) found.name = t("catalogue.errors.name");
    if (parseAmount(fee) === null) found.fee = t("editor.errors.price");
    if (!/^\d+$/.test(sortOrder.trim())) found.sort_order = t("editor.errors.threshold");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={zone ? t("delivery.editZone") : t("delivery.addZone")}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {!zone && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("delivery.code")} error={errors.code} help={t("delivery.codeHelp")}>
              {(c) => <Input {...c} maxLength={60} value={code} onChange={(e) => setCode(e.target.value.toLowerCase())} />}
            </Field>
            <Field label={t("delivery.columns.district")} error={errors.district}>
              {(c) => (
                <Select {...c} value={district} onChange={(e) => setDistrict(e.target.value as District)}>
                  {districts.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
        )}
        <Field label={t("catalogue.name")} error={errors.name}>
          {(c) => <Input {...c} maxLength={160} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("delivery.feeLabel")} error={errors.fee}>
            {(c) => <Input {...c} inputMode="numeric" value={fee} onChange={(e) => setFee(e.target.value)} />}
          </Field>
          <Field label={t("catalogue.sortOrder")} error={errors.sort_order} help={t("catalogue.sortHelp")}>
            {(c) => <Input {...c} inputMode="numeric" value={sortOrder} onChange={(e) => setSortOrder(e.target.value)} />}
          </Field>
        </div>
        <Checkbox label={t("delivery.codLabel")} checked={cod} onChange={(e) => setCod(e.target.checked)} />
        <Checkbox label={t("delivery.activeLabel")} checked={active} onChange={(e) => setActive(e.target.checked)} />
        {zone && zone.fee_history.length > 1 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">{t("delivery.history")}</span>
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm text-tx2">
              {zone.fee_history.map((rule) => (
                <li key={rule.id} className="flex justify-between gap-3">
                  <span>{formatMoney(rule.fee)}</span>
                  <span>{rule.starts_at ? formatDate(rule.starts_at, "date") : "—"}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Dialog>
  );
}
