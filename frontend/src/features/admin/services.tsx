"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Pencil, Plus, Trash2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Select, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { Toggle } from "@/components/ui/toggle";
import { useToast } from "@/components/ui/toast";
import { ServiceIcon, SERVICE_ICON_KEYS, type ServiceIconKey } from "@/features/services/service-icon";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { useStaffAccess } from "./access";
import { ImagePicker, moveItem } from "./categories";
import { bodyFieldErrors, LoadError, must, PageHeader, Thumb } from "./ui";

type Service = components["schemas"]["StaffService"];
type Item = components["schemas"]["StaffServiceItem"];

const KEY = ["admin", "services"] as const;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const SERVICE_ITEMS_MAX = 30;
const ICON_BUTTON =
  "flex size-8 flex-none cursor-pointer items-center justify-center rounded-lg border border-bd bg-white text-tx2 transition-colors duration-150 hover:border-pri hover:bg-light hover:text-pri-h disabled:cursor-default disabled:opacity-40 disabled:hover:border-bd disabled:hover:bg-white disabled:hover:text-tx2 motion-reduce:transition-none";

function useServices() {
  return useQuery({ queryKey: KEY, queryFn: () => must(browserApi.GET("/api/v1/staff/services")) });
}

/** Technical services (ADR-013): the storefront's /services cards in order (arrows reorder),
 * shown or hidden, each edited in a dialog (texts in English and optional Kinyarwanda, icon,
 * image and the "What we offer" items). A service with requests cannot be deleted; hide it. */
export function ServicesView() {
  const canManage = useStaffAccess().can("services:manage");
  const t = useTranslations("admin.services");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const list = useServices();
  const [editing, setEditing] = useState<Service | "new" | null>(null);
  const services = list.data ?? [];
  const reorder = useMutation({
    mutationFn: (ids: string[]) => must(browserApi.PUT("/api/v1/staff/services/order", { body: { service_ids: ids } })),
    onSuccess: () => void client.invalidateQueries({ queryKey: KEY }),
    onError: () => {
      toast.show(tc("saveError"), "error");
      void client.invalidateQueries({ queryKey: KEY });
    },
  });
  const move = (index: number, step: -1 | 1) => {
    const ids = moveItem(services.map((s) => s.id), index, step);
    // Shown at once; the server's order replaces it.
    client.setQueryData<Service[]>(KEY, (old) => (old ? ids.map((id) => old.find((s) => s.id === id)!) : old));
    reorder.mutate(ids);
  };

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canManage && (
            <Button onClick={() => setEditing("new")}>
              <Plus size={16} aria-hidden="true" />
              {t("add")}
            </Button>
          )
        }
      />
      <section aria-label={t("listLabel")} className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-4" />
        ) : !list.data ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : services.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-12 items-center justify-center rounded-full bg-subtle text-tx2">
              <Wrench size={22} />
            </span>
            <p className="m-0 text-tx2">{t("empty")}</p>
          </div>
        ) : (
          <ol className="m-0 flex list-none flex-col p-0">
            {services.map((s, index) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 border-b border-bd px-4 py-3 last:border-b-0">
                {canManage && (
                  <span className="flex flex-col gap-1">
                    <button type="button" aria-label={t("moveUp", { name: s.name_en })} title={t("moveUp", { name: s.name_en })} disabled={index === 0 || reorder.isPending} onClick={() => move(index, -1)} className={cx(ICON_BUTTON, "size-7")}>
                      <ChevronUp size={14} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label={t("moveDown", { name: s.name_en })}
                      title={t("moveDown", { name: s.name_en })}
                      disabled={index === services.length - 1 || reorder.isPending}
                      onClick={() => move(index, 1)}
                      className={cx(ICON_BUTTON, "size-7")}
                    >
                      <ChevronDown size={14} aria-hidden="true" />
                    </button>
                  </span>
                )}
                {s.image ? (
                  <Thumb image={{ url: s.image.url, width: s.image.width, height: s.image.height, alt: "", position: 0 }} size={48} />
                ) : (
                  <span aria-hidden="true" className="flex size-12 flex-none items-center justify-center rounded-lg bg-light text-pri">
                    <ServiceIcon icon={s.icon} size={22} />
                  </span>
                )}
                <span className="flex min-w-0 flex-[1_1_220px] flex-col">
                  <b className="truncate font-semibold">{s.name_en}</b>
                  <span className="truncate text-cap text-tx2">/services/{s.slug}</span>
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="soft-neutral">{t("itemCount", { count: s.items.length })}</Badge>
                  <Badge tone={s.request_count ? "soft-info" : "soft-neutral"}>{t("requestCount", { count: s.request_count })}</Badge>
                  {!s.name_rw && <Badge tone="soft-warn">{t("noRw")}</Badge>}
                </span>
                <span className="ml-auto flex items-center gap-3">
                  {canManage ? <ActiveToggle service={s} /> : <Badge tone={s.is_active ? "soft-ok" : "soft-neutral"}>{s.is_active ? tc("active") : tc("hidden")}</Badge>}
                  {canManage && (
                    <Button variant="neutral" size="sm" onClick={() => setEditing(s)}>
                      <Pencil size={14} aria-hidden="true" />
                      {tc("edit")}
                      <span className="sr-only"> {s.name_en}</span>
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
      {editing && <ServiceDialog service={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ActiveToggle({ service }: { service: Service }) {
  const t = useTranslations("admin.services");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const change = useMutation({
    mutationFn: (is_active: boolean) => must(browserApi.PATCH("/api/v1/staff/services/{service_id}", { params: { path: { service_id: service.id } }, body: { is_active } })),
    onSuccess: (saved) => {
      toast.show(t(saved.is_active ? "shown" : "hidden", { name: saved.name_en }));
      void client.invalidateQueries({ queryKey: KEY });
    },
    onError: () => toast.show(tc("saveError"), "error"),
  });
  return (
    <Toggle
      checked={service.is_active}
      disabled={change.isPending}
      onChange={(next) => change.mutate(next)}
      label={
        <>
          <span aria-hidden="true" className={cx("text-sm font-medium", service.is_active ? "text-ok-tx" : "text-tx2")}>
            {service.is_active ? tc("active") : tc("hidden")}
          </span>
          <span className="sr-only">{t("showService", { name: service.name_en })}</span>
        </>
      }
    />
  );
}

type Draft = {
  name_en: string;
  name_rw: string;
  slug: string;
  short_description_en: string;
  short_description_rw: string;
  intro_en: string;
  intro_rw: string;
  icon: ServiceIconKey;
  is_active: boolean;
};

const draftOf = (s: Service | null): Draft => ({
  name_en: s?.name_en ?? "",
  name_rw: s?.name_rw ?? "",
  slug: s?.slug ?? "",
  short_description_en: s?.short_description_en ?? "",
  short_description_rw: s?.short_description_rw ?? "",
  intro_en: s?.intro_en ?? "",
  intro_rw: s?.intro_rw ?? "",
  icon: s?.icon ?? "wrench",
  is_active: s?.is_active ?? true,
});

/** The fields of the draft that differ from the saved service (all of them for a new one), as
 * the API wants them: blank Kinyarwanda texts are null, a blank slug is generated. */
export function serviceChanges(draft: Draft, saved: Service | null): Record<string, string | boolean | null> {
  const value = (k: keyof Draft) => {
    const v = draft[k];
    if (typeof v === "boolean") return v;
    const trimmed = v.trim();
    return k.endsWith("_rw") || k === "slug" ? trimmed || null : trimmed;
  };
  const out: Record<string, string | boolean | null> = {};
  for (const k of Object.keys(draft) as (keyof Draft)[]) {
    const v = value(k);
    if (!saved) {
      if (v !== null) out[k] = v;
      continue;
    }
    if (k === "slug" && v === null) continue; // the slug cannot be cleared
    if (v !== ((saved[k as keyof Service] as string | boolean | null) ?? null)) out[k] = v;
  }
  return out;
}

function ServiceDialog({ service, onClose }: { service: Service | null; onClose: () => void }) {
  const t = useTranslations("admin.services");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<Draft>(() => draftOf(service));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [tab, setTab] = useState("details");
  // The latest copy, so items and the image show changes at once.
  const live = useServices().data?.find((s) => s.id === service?.id) ?? service;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const refresh = () => void client.invalidateQueries({ queryKey: KEY });

  const save = useMutation({
    mutationFn: () => {
      const body = serviceChanges(draft, service);
      if (!service) return must(browserApi.POST("/api/v1/staff/services", { body: body as components["schemas"]["ServiceCreateRequest"] }));
      return must(browserApi.PATCH("/api/v1/staff/services/{service_id}", { params: { path: { service_id: service.id } }, body: body as components["schemas"]["ServiceUpdateRequest"] }));
    },
    onSuccess: () => {
      toast.show(tc("saved"));
      refresh();
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "slug_taken") setErrors({ slug: t("errors.slugTaken") });
      else if (error instanceof ApiError && error.status === 422) setErrors(bodyFieldErrors(error));
      else toast.show(tc("saveError"), "error");
      setTab("details");
    },
  });
  const remove = useMutation({
    mutationFn: () => must(browserApi.DELETE("/api/v1/staff/services/{service_id}", { params: { path: { service_id: service!.id } } })),
    onSuccess: () => {
      toast.show(t("deleted", { name: service!.name_en }));
      refresh();
      onClose();
    },
    onError: (error) => toast.show(error instanceof ApiError && error.code === "service_has_requests" ? t("errors.hasRequests") : tc("saveError"), "error"),
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (draft.name_en.trim().length < 2) found.name_en = t("errors.text");
    if (draft.short_description_en.trim().length < 2) found.short_description_en = t("errors.text");
    if (draft.intro_en.trim().length < 2) found.intro_en = t("errors.text");
    if (draft.slug.trim() && !SLUG.test(draft.slug.trim())) found.slug = t("errors.slug");
    setErrors(found);
    if (Object.keys(found).length) return setTab("details");
    if (service && Object.keys(serviceChanges(draft, service)).length === 0) return onClose();
    save.mutate();
  };

  const text = (k: keyof Draft, label: string, max: number, rows?: number, help?: string) => (
    <Field label={label} error={errors[k]} help={help}>
      {(c) =>
        rows ? (
          <Textarea {...c} rows={rows} maxLength={max} value={draft[k] as string} onChange={(e) => set(k, e.target.value as never)} />
        ) : (
          <Input {...c} maxLength={max} value={draft[k] as string} onChange={(e) => set(k, (k === "slug" ? e.target.value.toLowerCase() : e.target.value) as never)} />
        )
      }
    </Field>
  );
  const details = (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {text("name_en", t("nameEn"), 120)}
        {text("name_rw", t("nameRw"), 120, undefined, tc("optional"))}
      </div>
      {text("slug", t("slug"), 80, undefined, service ? undefined : t("slugHelp"))}
      <div className="grid gap-4 sm:grid-cols-2">
        {text("short_description_en", t("shortEn"), 240, 3)}
        {text("short_description_rw", t("shortRw"), 240, 3, tc("optional"))}
      </div>
      {text("intro_en", t("introEn"), 3000, 5)}
      {text("intro_rw", t("introRw"), 3000, 5, tc("optional"))}
      <Field label={t("icon")} error={errors.icon}>
        {(c) => (
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="flex size-11 flex-none items-center justify-center rounded-lg bg-light text-pri">
              <ServiceIcon icon={draft.icon} size={20} />
            </span>
            <Select {...c} value={draft.icon} onChange={(e) => set("icon", e.target.value as ServiceIconKey)}>
              {SERVICE_ICON_KEYS.map((key) => (
                <option key={key} value={key}>
                  {t(`icons.${key}`)}
                </option>
              ))}
            </Select>
          </div>
        )}
      </Field>
      <Checkbox label={t("activeService")} checked={draft.is_active} onChange={(e) => set("is_active", e.target.checked)} />
      {service && service.request_count > 0 && <p className="m-0 text-cap text-tx2">{t("deleteHint", { count: service.request_count })}</p>}
    </div>
  );

  return (
    <Dialog
      open
      onClose={onClose}
      title={service ? t("editOf", { name: service.name_en }) : t("add")}
      closeLabel={tc("close")}
      className="max-w-[680px]"
      footer={
        <>
          {service && (
            <Button variant="danger-outline" className="mr-auto" disabled={remove.isPending || service.request_count > 0} onClick={() => remove.mutate()}>
              {tc("delete")}
            </Button>
          )}
          <Button variant="neutral" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            {tc("save")}
          </Button>
        </>
      }
    >
      {live ? (
        <Tabs
          label={t("tabsLabel")}
          value={tab}
          onChange={setTab}
          items={[
            { id: "details", label: t("tabs.details"), content: details },
            { id: "items", label: t("tabs.items", { count: live.items.length }), content: <ItemsEditor service={live} /> },
            {
              id: "image",
              label: t("tabs.image"),
              content: (
                <ImagePicker
                  label={t("image")}
                  image={live.image}
                  uploadPath={`staff/services/${live.id}/image`}
                  onRemove={() => must(browserApi.DELETE("/api/v1/staff/services/{service_id}/image", { params: { path: { service_id: live.id } } }))}
                  onChanged={refresh}
                />
              ),
            },
          ]}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {details}
          <p className="m-0 text-cap text-tx2">{t("itemsAfterSave")}</p>
        </div>
      )}
    </Dialog>
  );
}

/** "What we offer": the service's items, each saved as it changes (add, edit, move, delete). */
function ItemsEditor({ service }: { service: Service }) {
  const t = useTranslations("admin.services");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const [en, setEn] = useState("");
  const [rw, setRw] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [editing, setEditing] = useState<string | null>(null);
  const refresh = () => void client.invalidateQueries({ queryKey: KEY });
  const failed = () => toast.show(tc("saveError"), "error");
  const path = { service_id: service.id };
  const add = useMutation({
    mutationFn: () => must(browserApi.POST("/api/v1/staff/services/{service_id}/items", { params: { path }, body: { title_en: en.trim(), title_rw: rw.trim() || null } })),
    onSuccess: () => {
      setEn("");
      setRw("");
      refresh();
    },
    onError: (e) => (e instanceof ApiError && e.status === 422 ? setError(Object.values(bodyFieldErrors(e))[0] ?? t("errors.text")) : failed()),
  });
  const reorder = useMutation({
    mutationFn: (ids: string[]) => must(browserApi.PUT("/api/v1/staff/services/{service_id}/items/order", { params: { path }, body: { item_ids: ids } })),
    onSettled: refresh,
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: (id: string) => must(browserApi.DELETE("/api/v1/staff/services/{service_id}/items/{item_id}", { params: { path: { ...path, item_id: id } } })),
    onSuccess: refresh,
    onError: failed,
  });
  const items = service.items;
  const full = items.length >= SERVICE_ITEMS_MAX;
  const submit = () => {
    if (en.trim().length < 2) return setError(t("errors.text"));
    setError(undefined);
    add.mutate();
  };

  return (
    <div className="flex flex-col gap-4">
      {items.length === 0 ? (
        <p className="m-0 rounded-lg border border-dashed border-bd2 px-4 py-3 text-sm text-tx2">{t("noItems")}</p>
      ) : (
        <ol aria-label={t("itemsLabel")} className="m-0 flex list-none flex-col gap-1.5 p-0">
          {items.map((item, index) =>
            editing === item.id ? (
              <li key={item.id}>
                <ItemEdit service={service} item={item} onDone={() => setEditing(null)} />
              </li>
            ) : (
              <li key={item.id} className="flex items-center gap-2 rounded-lg border border-bd bg-white px-3 py-2">
                <span className="w-5 flex-none text-cap text-tx2">{index + 1}</span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-sm break-words">{item.title_en}</span>
                  {item.title_rw && (
                    <span lang="rw" className="text-cap break-words text-tx2">
                      {item.title_rw}
                    </span>
                  )}
                </span>
                <button type="button" aria-label={t("moveItemUp", { name: item.title_en })} title={t("moveItemUp", { name: item.title_en })} disabled={index === 0 || reorder.isPending} onClick={() => reorder.mutate(moveItem(items.map((i) => i.id), index, -1))} className={ICON_BUTTON}>
                  <ChevronUp size={15} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label={t("moveItemDown", { name: item.title_en })}
                  title={t("moveItemDown", { name: item.title_en })}
                  disabled={index === items.length - 1 || reorder.isPending}
                  onClick={() => reorder.mutate(moveItem(items.map((i) => i.id), index, 1))}
                  className={ICON_BUTTON}
                >
                  <ChevronDown size={15} aria-hidden="true" />
                </button>
                <button type="button" aria-label={t("editItem", { name: item.title_en })} title={t("editItem", { name: item.title_en })} onClick={() => setEditing(item.id)} className={ICON_BUTTON}>
                  <Pencil size={14} aria-hidden="true" />
                </button>
                <button type="button" aria-label={t("deleteItem", { name: item.title_en })} title={t("deleteItem", { name: item.title_en })} disabled={remove.isPending} onClick={() => remove.mutate(item.id)} className={ICON_BUTTON}>
                  <Trash2 size={14} aria-hidden="true" />
                </button>
              </li>
            ),
          )}
        </ol>
      )}
      {full ? (
        <p className="m-0 text-cap text-tx2">{t("itemsFull", { max: SERVICE_ITEMS_MAX })}</p>
      ) : (
        <div className="flex flex-col gap-3 rounded-lg bg-page p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("itemEn")} error={error}>
              {(c) => <Input {...c} maxLength={200} value={en} onChange={(e) => setEn(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), submit())} />}
            </Field>
            <Field label={t("itemRw")} help={tc("optional")}>
              {(c) => <Input {...c} maxLength={200} value={rw} onChange={(e) => setRw(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), submit())} />}
            </Field>
          </div>
          <Button variant="outline" size="sm" className="self-start" disabled={add.isPending} onClick={submit}>
            <Plus size={16} aria-hidden="true" />
            {t("addItem")}
          </Button>
        </div>
      )}
    </div>
  );
}

function ItemEdit({ service, item, onDone }: { service: Service; item: Item; onDone: () => void }) {
  const t = useTranslations("admin.services");
  const tc = useTranslations("admin.common");
  const client = useQueryClient();
  const toast = useToast();
  const [en, setEn] = useState(item.title_en);
  const [rw, setRw] = useState(item.title_rw ?? "");
  const [error, setError] = useState<string | undefined>();
  const save = useMutation({
    mutationFn: () =>
      must(
        browserApi.PATCH("/api/v1/staff/services/{service_id}/items/{item_id}", {
          params: { path: { service_id: service.id, item_id: item.id } },
          body: { title_en: en.trim(), title_rw: rw.trim() || null },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: KEY });
      onDone();
    },
    onError: () => toast.show(tc("saveError"), "error"),
  });
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-pri bg-light p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("itemEn")} error={error}>
          {(c) => <Input {...c} maxLength={200} value={en} onChange={(e) => setEn(e.target.value)} />}
        </Field>
        <Field label={t("itemRw")} help={tc("optional")}>
          {(c) => <Input {...c} maxLength={200} value={rw} onChange={(e) => setRw(e.target.value)} />}
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="neutral" size="sm" onClick={onDone}>
          {tc("cancel")}
        </Button>
        <Button
          size="sm"
          disabled={save.isPending}
          onClick={() => {
            if (en.trim().length < 2) return setError(t("errors.text"));
            save.mutate();
          }}
        >
          {tc("save")}
        </Button>
      </div>
    </div>
  );
}
