"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarRange, FileText, Image as ImageIcon, Megaphone, Pencil, Plus, Receipt, Share2, Store, Truck, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { SOCIAL_HOSTS, SOCIAL_NAMES, SOCIAL_NETWORKS, SocialIcon, type SocialNetwork } from "@/components/ui/social-icons";
import { Toggle } from "@/components/ui/toggle";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import { useStaffAccess } from "./access";
import { ImagePicker } from "./categories";
import { numberSetting, THRESHOLD_KEY } from "./delivery";
import { PagesSummary, PagesTab } from "./pages";
import { groupDigits, parseAmount } from "./numbers";
import { dayFromEnd, endFromDay, kigaliDay } from "./promotions";
import {
  ANNOUNCEMENT_KEYS,
  CONTACT_KEYS,
  SOCIAL_KEYS,
  socialChanges,
  socialNetworkOf,
  STORE_LIMITS,
  storeChanges,
  storeFieldOf,
  type ContactField,
  type SocialLinks,
  type StoreTexts,
} from "./store-settings";
import { bodyFieldErrors, FilterTabs, LoadError, must, PageHeader, Thumb, useListParams } from "./ui";

type Banner = components["schemas"]["StaffBannerResponse"];
type Settings = components["schemas"]["SettingResponse"][];

const SELLER = { name: "seller.legal_name", tin: "seller.tin", address: "seller.address" } as const;
/** The backend's seller rules (app/schemas/settings.py). */
const LEGAL_NAME_MAX = 200;
const ADDRESS_MAX = 500;
const TIN = /^[A-Za-z0-9][A-Za-z0-9 -]{0,39}$/;
/** The backend's banner limits (app/models/content.py) and link rule (app/schemas/banners.py). */
const BANNER_MAX = { title: 80, overline: 40, subtitle: 160, cta_label: 30, cta_url: 200 } as const;
const CTA_PATH = /^\/(?![/\\])[A-Za-z0-9\-._~/%?=&#]*$/;
const TAB_ICON = { store: Store, banners: ImageIcon, pages: FileText } as const;

export function textSetting(items: Settings | undefined, key: string): string {
  const value = items?.find((i) => i.key === key)?.value;
  return typeof value === "string" ? value : "";
}

/** A banner link must stay on this site: one leading "/", no "//", no spaces. */
export function ctaPathOk(value: string): boolean {
  return value.length <= BANNER_MAX.cta_url && !value.includes("//") && CTA_PATH.test(value);
}

/** Settings.dc.html: the Store tab, the Homepage banners tab and the Policy pages tab, chosen with
 * a segmented control (toggle buttons that set ?tab=, like the other admin tabs). */
export function SettingsView() {
  const t = useTranslations("admin.settings");
  const { can } = useStaffAccess();
  const { get, set } = useListParams();
  const tabs = [...(can("settings:read") ? (["store"] as const) : []), ...(can("content:manage") ? (["banners", "pages"] as const) : [])];
  const tab = tabs.find((x) => x === get("tab")) ?? tabs[0];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      {tabs.length > 1 && (
        <div role="group" aria-label={t("tabsLabel")} className="flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl border border-bd bg-card p-1 shadow-sh">
          {tabs.map((id) => {
            const on = id === tab;
            const Icon = TAB_ICON[id];
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                onClick={() => set({ tab: id, page: null })}
                className={cx(
                  "flex h-10 cursor-pointer items-center gap-2 rounded-lg border-0 px-4 text-sm font-semibold whitespace-nowrap transition-colors duration-150 motion-reduce:transition-none",
                  on ? "bg-pri text-white shadow-sh" : "bg-transparent text-tx2 hover:bg-page hover:text-tx",
                )}
              >
                <Icon size={16} aria-hidden="true" />
                {t(`tabs.${id}`)}
              </button>
            );
          })}
        </div>
      )}
      {tab === "store" ? <StoreTab /> : tab === "pages" ? <PagesTab /> : <BannersTab />}
    </>
  );
}

/** A settings group: icon, title and a one-line explanation over its fields. */
function SettingsCard({ Icon, tone, title, description, aside, children }: { Icon: LucideIcon; tone: string; title: string; description?: ReactNode; aside?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="rounded-xl border border-bd bg-card shadow-sh">
      <div className="flex items-start gap-3.5 border-b border-bd px-6 py-4 max-sm:px-4">
        <span aria-hidden="true" className={cx("flex size-10 flex-none items-center justify-center rounded-lg", tone)}>
          <Icon size={20} />
        </span>
        <div className="flex min-w-0 grow flex-col gap-0.5">
          <h2 id={id} className="t-h4">
            {title}
          </h2>
          {description && <p className="m-0 text-sm text-tx2">{description}</p>}
        </div>
        {aside && <div className="flex-none self-center">{aside}</div>}
      </div>
      <div className="flex flex-col gap-4 p-6 max-sm:p-4">{children}</div>
    </section>
  );
}

function StoreTab() {
  const t = useTranslations("admin");
  const { can } = useStaffAccess();
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => must(browserApi.GET("/api/v1/staff/settings")) });
  const form = settings.isError ? (
    <LoadError onRetry={() => settings.refetch()} />
  ) : !settings.data ? (
    <Skeleton className="h-[420px] w-full rounded-xl" />
  ) : (
    <StoreForm key={settings.dataUpdatedAt} items={settings.data.items} manage={can("settings:manage")} t={t} />
  );
  return (
    <div className="flex flex-wrap items-start gap-5">
      <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-5">{form}</div>
      {can("content:manage") && (
        <div className="flex min-w-0 flex-[1_1_300px] lg:sticky lg:top-[88px]">
          <PagesSummary />
        </div>
      )}
    </div>
  );
}

function StoreForm({ items, manage, t }: { items: Settings; manage: boolean; t: ReturnType<typeof useTranslations<"admin">> }) {
  const client = useQueryClient();
  const toast = useToast();
  const initial = {
    name: textSetting(items, SELLER.name),
    tin: textSetting(items, SELLER.tin),
    address: textSetting(items, SELLER.address),
    threshold: numberSetting(items, THRESHOLD_KEY),
  };
  const initialTexts: StoreTexts = {
    name: textSetting(items, CONTACT_KEYS.name),
    phone: textSetting(items, CONTACT_KEYS.phone),
    whatsapp: textSetting(items, CONTACT_KEYS.whatsapp),
    email: textSetting(items, CONTACT_KEYS.email),
    address: textSetting(items, CONTACT_KEYS.address),
    hours: textSetting(items, CONTACT_KEYS.hours),
    announceEn: textSetting(items, ANNOUNCEMENT_KEYS.en),
    announceRw: textSetting(items, ANNOUNCEMENT_KEYS.rw),
  };
  const initialEnabled = items.find((i) => i.key === ANNOUNCEMENT_KEYS.enabled)?.value === true;
  const initialLinks = Object.fromEntries(SOCIAL_NETWORKS.map((n) => [n, textSetting(items, SOCIAL_KEYS[n])])) as SocialLinks;
  const [name, setName] = useState(initial.name);
  const [tin, setTin] = useState(initial.tin);
  const [address, setAddress] = useState(initial.address);
  const [threshold, setThreshold] = useState(initial.threshold === null ? "" : groupDigits(initial.threshold));
  const [texts, setTexts] = useState(initialTexts);
  const [enabled, setEnabled] = useState(initialEnabled);
  const [lang, setLang] = useState<"en" | "rw">("en");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [storeErrors, setStoreErrors] = useState<Record<string, string>>({});
  const [links, setLinks] = useState(initialLinks);
  const [socialErrors, setSocialErrors] = useState<Partial<Record<SocialNetwork, string>>>({});
  const missing = !initial.name || !initial.tin || !initial.address;

  const showStoreErrors = (found: Record<string, string>) => {
    setStoreErrors(found);
    if (found.announceEn || found.announceRw) setLang(found.announceEn ? "en" : "rw");
  };

  const save = useMutation({
    mutationFn: (body: Record<string, string | number | boolean>) => must(browserApi.PATCH("/api/v1/staff/settings", { body })),
    onSuccess: () => {
      toast.show(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["admin", "settings"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        const found = bodyFieldErrors(error);
        setErrors({ name: found[SELLER.name], tin: found[SELLER.tin], address: found[SELLER.address], threshold: found[THRESHOLD_KEY] });
        const store: Record<string, string> = {};
        const social: Partial<Record<SocialNetwork, string>> = {};
        for (const [key, message] of Object.entries(found)) {
          const network = socialNetworkOf(key);
          if (network) social[network] = message;
          const field = key === ANNOUNCEMENT_KEYS.enabled ? "announceEn" : storeFieldOf(key);
          if (field) store[field] = message;
        }
        showStoreErrors(store);
        setSocialErrors(social);
      } else toast.show(t("common.saveError"), "error");
    },
  });

  const submit = () => {
    const found: Record<string, string> = {};
    const body: Record<string, string | number | boolean> = {};
    const fields = [
      ["name", SELLER.name, name.trim(), initial.name],
      ["tin", SELLER.tin, tin.trim(), initial.tin],
      ["address", SELLER.address, address.trim(), initial.address],
    ] as const;
    for (const [id, key, value, before] of fields) {
      if (value === before) continue;
      // The API has no way to clear a seller detail (null is refused), so a set one stays set.
      if (!value) found[id] = t("common.required");
      else body[key] = value;
    }
    if (body[SELLER.tin] !== undefined && !TIN.test(tin.trim())) found.tin = t("settings.errors.tin");
    const amount = threshold.trim() ? parseAmount(threshold) : null;
    if (threshold.trim() && amount === null) found.threshold = t("editor.errors.price");
    else if (!threshold.trim() && initial.threshold !== null) found.threshold = t("common.required");
    else if (amount !== null && amount !== initial.threshold) body[THRESHOLD_KEY] = amount;
    const store = storeChanges(texts, initialTexts, enabled, initialEnabled);
    const storeFound = Object.fromEntries(
      Object.entries(store.errors).map(([field, key]) => [field, key === "required" ? t("common.required") : t(`settings.errors.${key as "phone"}`)]),
    );
    const social = socialChanges(links, initialLinks);
    const socialFound = Object.fromEntries(social.errors.map((n) => [n, t("settings.errors.social", { network: SOCIAL_NAMES[n] })]));
    setErrors(found);
    showStoreErrors(storeFound);
    setSocialErrors(socialFound);
    if (Object.keys(found).length > 0 || Object.keys(storeFound).length > 0 || social.errors.length > 0) return;
    Object.assign(body, store.body, social.body);
    if (Object.keys(body).length === 0) return toast.show(t("settings.nothingChanged"));
    save.mutate(body);
  };

  const contactField = (field: ContactField, label: string, props: { maxLength: number; inputMode?: "tel" | "email"; help?: string; placeholder?: string }) => (
    <Field label={label} error={storeErrors[field]} help={props.help}>
      {(c) => (
        <Input
          {...c}
          disabled={!manage}
          maxLength={props.maxLength}
          inputMode={props.inputMode}
          type={props.inputMode === "email" ? "email" : "text"}
          placeholder={props.placeholder}
          value={texts[field]}
          onChange={(e) => setTexts((s) => ({ ...s, [field]: e.target.value }))}
        />
      )}
    </Field>
  );
  const announceField = lang === "en" ? "announceEn" : "announceRw";
  const preview = texts[announceField].trim();

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col gap-5"
    >
      <SettingsCard Icon={Store} tone="bg-light text-pri-h" title={t("settings.contact")} description={t("settings.contactDesc")}>
        <div className="grid gap-4 md:grid-cols-2">
          {contactField("name", t("settings.storeName"), { maxLength: STORE_LIMITS.name[1] })}
          {contactField("phone", t("settings.phone"), { maxLength: 22, inputMode: "tel", placeholder: "+250 788 123 456" })}
          {contactField("whatsapp", t("settings.whatsapp"), { maxLength: 22, inputMode: "tel", placeholder: "+250 788 123 456", help: t("settings.whatsappHelp") })}
          {contactField("email", t("settings.email"), { maxLength: STORE_LIMITS.email, inputMode: "email" })}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {contactField("address", t("settings.storeAddress"), { maxLength: STORE_LIMITS.address[1] })}
          {contactField("hours", t("settings.hours"), { maxLength: STORE_LIMITS.hours[1] })}
        </div>
      </SettingsCard>

      {/* Social media (owner, 2026-11-18): each link becomes an icon in the store footer. */}
      <SettingsCard Icon={Share2} tone="bg-light text-pri-h" title={t("settings.social")} description={t("settings.socialDesc")}>
        <div className="grid gap-4 md:grid-cols-2">
          {SOCIAL_NETWORKS.map((network) => (
            <Field key={network} label={SOCIAL_NAMES[network]} error={socialErrors[network]}>
              {(c) => (
                <div className="flex h-11 items-center overflow-hidden rounded-lg border border-bd bg-card focus-within:border-pri focus-within:shadow-focus">
                  <span className="flex h-full w-11 flex-none items-center justify-center border-r border-bd bg-page text-tx2" aria-hidden="true">
                    <SocialIcon network={network} size={17} />
                  </span>
                  <input
                    {...c}
                    type="url"
                    inputMode="url"
                    autoComplete="off"
                    spellCheck={false}
                    disabled={!manage}
                    maxLength={300}
                    placeholder={`https://www.${SOCIAL_HOSTS[network][0]}/…`}
                    value={links[network]}
                    onChange={(e) => setLinks((s) => ({ ...s, [network]: e.target.value }))}
                    className="h-full min-w-0 flex-1 border-0 px-3.5 text-base outline-none disabled:bg-subtle"
                  />
                </div>
              )}
            </Field>
          ))}
        </div>
      </SettingsCard>

      <SettingsCard
        Icon={Megaphone}
        tone="bg-warn-bg text-warn-tx"
        title={t("settings.announcement")}
        description={t("settings.announcementDesc")}
        aside={<Toggle checked={enabled} disabled={!manage} onChange={setEnabled} label={<span className="sr-only">{t("settings.showAnnouncement")}</span>} />}
      >
        <div className="-mx-6 -mt-6 max-sm:-mx-4 max-sm:-mt-4">
          <FilterTabs label={t("settings.announcementLang")} value={lang} onChange={(id) => setLang(id === "rw" ? "rw" : "en")} items={(["en", "rw"] as const).map((id) => ({ id, label: t(`settings.lang.${id}`) }))} />
        </div>
        <Field key={announceField} label={t("settings.message")} error={storeErrors[announceField]} help={t("settings.announcementHelp")}>
          {(c) => (
            <Input
              {...c}
              lang={lang}
              disabled={!manage}
              maxLength={STORE_LIMITS.announce[1]}
              value={texts[announceField]}
              onChange={(e) => setTexts((s) => ({ ...s, [announceField]: e.target.value }))}
            />
          )}
        </Field>
        {(storeErrors.announceEn || storeErrors.announceRw) && storeErrors[announceField] === undefined && (
          <p role="alert" className="text-cap text-err-tx">
            {t("settings.errors.otherLanguage", { lang: t(`settings.lang.${lang === "en" ? "rw" : "en"}`) })}
          </p>
        )}
        {/* How the bar reads at the top of the store (the store header's navy announcement bar). */}
        <div className="flex flex-col gap-1.5">
          <span className="text-cap font-semibold text-tx2">{t("settings.preview")}</span>
          <div aria-hidden="true" className={cx("rounded-lg bg-navy px-4 py-2.5 text-center text-sm font-medium text-white transition-opacity", !enabled && "opacity-50")}>
            {preview || <span className="text-odm italic">{t("settings.previewEmpty")}</span>}
          </div>
          {!enabled && <span className="text-cap text-tx2">{t("settings.previewOff")}</span>}
        </div>
      </SettingsCard>

      <SettingsCard Icon={Receipt} tone="bg-pur-bg text-pur" title={t("settings.seller")} description={t("settings.sellerHelp")}>
        {missing && (
          <p role="status" className="m-0 flex items-start gap-2.5 rounded-lg border border-warn/40 bg-warn-bg px-3.5 py-2.5 text-sm text-warn-tx">
            <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 flex-none" />
            {t("settings.sellerMissing")}
          </p>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={t("settings.legalName")} error={errors.name}>
            {(c) => <Input {...c} disabled={!manage} maxLength={LEGAL_NAME_MAX} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label={t("settings.tin")} error={errors.tin}>
            {(c) => <Input {...c} disabled={!manage} maxLength={40} value={tin} onChange={(e) => setTin(e.target.value)} className="font-mono" />}
          </Field>
        </div>
        <Field label={t("settings.address")} error={errors.address}>
          {(c) => <Textarea {...c} disabled={!manage} rows={3} maxLength={ADDRESS_MAX} value={address} onChange={(e) => setAddress(e.target.value)} />}
        </Field>
      </SettingsCard>

      <SettingsCard Icon={Truck} tone="bg-ok-bg text-ok-tx" title={t("settings.delivery")} description={t("delivery.thresholdHelp")}>
        <Field label={t("delivery.threshold")} error={errors.threshold} className="w-[300px] max-w-full">
          {(c) => (
            <div className="flex h-11 items-center overflow-hidden rounded-lg border border-bd bg-card focus-within:border-pri focus-within:shadow-focus">
              <span className="flex h-full items-center border-r border-bd bg-page px-3 text-sm font-medium text-tx2">RWF</span>
              <input
                {...c}
                inputMode="numeric"
                disabled={!manage}
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                className="h-full min-w-0 flex-1 border-0 px-3.5 text-base outline-none disabled:bg-subtle"
              />
            </div>
          )}
        </Field>
      </SettingsCard>

      {/* Save stays in reach while scrolling through the groups. */}
      {manage ? (
        <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bd bg-card px-5 py-3 shadow-sh2">
          <span className="text-sm text-tx2">{t("settings.saveHint")}</span>
          <Button type="submit" disabled={save.isPending}>
            {t("common.saveChanges")}
          </Button>
        </div>
      ) : (
        <p className="m-0 rounded-xl border border-bd bg-card px-5 py-3 text-sm text-tx2">{t("settings.readOnly")}</p>
      )}
    </form>
  );
}

type BannerPhase = "live" | "scheduled" | "ended" | "hidden";

/** Where a banner stands now; "live" is the API's own shown_now. */
export function bannerPhase(b: Pick<Banner, "is_active" | "shown_now" | "starts_at" | "ends_at">, now: number): BannerPhase {
  if (b.shown_now) return "live";
  if (!b.is_active) return "hidden";
  if (b.ends_at && Date.parse(b.ends_at) <= now) return "ended";
  return "scheduled";
}

const BANNER_TONE: Record<BannerPhase, BadgeTone> = { live: "soft-ok", scheduled: "soft-info", ended: "soft-neutral", hidden: "soft-warn" };

/** Homepage banners, built from the Promotions.dc.html pattern (no design of its own): the list,
 * and the create/edit form in a dialog. */
function BannersTab() {
  const t = useTranslations("admin.settings");
  const list = useQuery({ queryKey: ["admin", "banners"], queryFn: () => must(browserApi.GET("/api/v1/staff/banners")) });
  const [form, setForm] = useState<string | "new" | null>(null);
  const [now] = useState(() => Date.now());
  const banners = list.data?.items ?? [];
  const editing = form && form !== "new" ? banners.find((b) => b.id === form) : undefined;
  const newButton = (
    <Button size="sm" onClick={() => setForm("new")} className="gap-1.5">
      <Plus size={16} aria-hidden="true" />
      {t("newBanner")}
    </Button>
  );

  return (
    <>
      <section className="min-w-0 overflow-hidden rounded-xl border border-bd bg-card shadow-sh">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-bd px-6 py-4 max-sm:px-4">
          <div className="flex min-w-0 items-start gap-3.5">
            <span aria-hidden="true" className="flex size-10 flex-none items-center justify-center rounded-lg bg-light text-pri-h">
              <ImageIcon size={20} />
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
              <h2 className="t-h4">{t("tabs.banners")}</h2>
              <p className="m-0 text-sm text-tx2">{t("bannersHelp")}</p>
            </div>
          </div>
          {newButton}
        </div>
        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && banners.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <ImageIcon size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{t("noBanners")}</p>
            {newButton}
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("columns.banner")}</Th>
                <Th>{t("columns.link")}</Th>
                <Th>{t("columns.valid")}</Th>
                <Th className="text-center">{t("columns.position")}</Th>
                <Th>{t("columns.status")}</Th>
                <Th>
                  <span className="sr-only">{t("editShort")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 3 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={6}>
                        <Skeleton className="h-12 w-full" />
                      </Td>
                    </tr>
                  ))
                : banners.map((b) => {
                    const phase = bannerPhase(b, now);
                    return (
                      <tr key={b.id} className="transition-colors duration-150 hover:bg-page motion-reduce:transition-none">
                        <Td>
                          <span className="flex items-center gap-3">
                            <Thumb image={b.image ? { url: b.image.url, width: b.image.width, height: b.image.height, alt: "", position: 0 } : null} size={52} />
                            <span className="flex min-w-0 flex-col items-start">
                              <button type="button" onClick={() => setForm(b.id)} className="cursor-pointer border-0 bg-transparent p-0 text-left font-semibold text-tx hover:text-pri-h">
                                {b.title_en}
                              </button>
                              <span lang="rw" className="text-cap text-tx2">
                                {b.title_rw}
                              </span>
                            </span>
                          </span>
                        </Td>
                        <Td className="text-tx2">
                          {b.cta_url ? <span className="rounded-md bg-page px-1.5 py-0.5 font-mono text-cap break-all text-tx">{b.cta_url}</span> : <span className="italic">{t("noLink")}</span>}
                        </Td>
                        <Td>
                          <span className="flex items-center gap-1.5 text-sm whitespace-nowrap text-tx2">
                            <CalendarRange size={15} aria-hidden="true" className="flex-none" />
                            {!b.starts_at && !b.ends_at
                              ? t("always")
                              : `${b.starts_at ? formatDate(b.starts_at, "date") : t("now")} – ${b.ends_at ? formatDate(new Date(Date.parse(b.ends_at) - 1000), "date") : t("noEnd")}`}
                          </span>
                        </Td>
                        <Td className="text-center">
                          <span className="inline-flex size-7 items-center justify-center rounded-full bg-subtle text-cap font-semibold tabular-nums">{b.position}</span>
                        </Td>
                        <Td>
                          <Badge tone={BANNER_TONE[phase]}>{t(`phase.${phase}`)}</Badge>
                          {!b.image && (
                            <span className="mt-1 flex items-center gap-1 text-cap text-warn-tx">
                              <AlertTriangle size={12} aria-hidden="true" />
                              {t("needsImage")}
                            </span>
                          )}
                        </Td>
                        <Td className="text-right">
                          <Button variant="neutral" size="sm" onClick={() => setForm(b.id)} aria-label={t("editNamed", { name: b.title_en })} className="gap-1.5">
                            <Pencil size={14} aria-hidden="true" />
                            {t("editShort")}
                          </Button>
                        </Td>
                      </tr>
                    );
                  })}
            </tbody>
          </Table>
        )}
      </section>
      {form === "new" && <BannerForm key="new" banner={null} onSaved={(id) => setForm(id)} onClose={() => setForm(null)} />}
      {editing && <BannerForm key={editing.id} banner={editing} onSaved={() => undefined} onClose={() => setForm(null)} />}
    </>
  );
}

const TEXT_FIELDS = ["title", "overline", "subtitle", "cta_label"] as const;
type TextField = (typeof TEXT_FIELDS)[number];
type Texts = Record<`${TextField}_${"en" | "rw"}`, string>;

function BannerForm({ banner, onSaved, onClose }: { banner: Banner | null; onSaved: (id: string) => void; onClose: () => void }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const formId = useId();
  const [texts, setTexts] = useState<Texts>(() => {
    const out = {} as Texts;
    for (const f of TEXT_FIELDS) for (const lang of ["en", "rw"] as const) out[`${f}_${lang}`] = banner?.[`${f}_${lang}`] ?? "";
    return out;
  });
  const [link, setLink] = useState(banner?.cta_url ?? "");
  const [position, setPosition] = useState(String(banner?.position ?? 0));
  const [starts, setStarts] = useState(banner?.starts_at ? kigaliDay(new Date(banner.starts_at)) : "");
  const [ends, setEnds] = useState(banner?.ends_at ? dayFromEnd(banner.ends_at) : "");
  const [active, setActive] = useState(banner?.is_active ?? false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const refresh = () => void client.invalidateQueries({ queryKey: ["admin", "banners"] });

  const save = useMutation({
    mutationFn: () => {
      const optional = (v: string) => v.trim() || null;
      const body = {
        title_en: texts.title_en.trim(),
        title_rw: texts.title_rw.trim(),
        overline_en: optional(texts.overline_en),
        overline_rw: optional(texts.overline_rw),
        subtitle_en: optional(texts.subtitle_en),
        subtitle_rw: optional(texts.subtitle_rw),
        cta_label_en: optional(texts.cta_label_en),
        cta_label_rw: optional(texts.cta_label_rw),
        cta_url: optional(link),
        position: Number(position),
        starts_at: starts ? `${starts}T00:00:00` : null,
        ends_at: ends ? endFromDay(ends) : null,
      };
      if (!banner) return must(browserApi.POST("/api/v1/staff/banners", { body }));
      return must(browserApi.PATCH("/api/v1/staff/banners/{banner_id}", { params: { path: { banner_id: banner.id } }, body: { ...body, is_active: active } }));
    },
    onSuccess: (saved) => {
      toast.show(banner ? t("common.saved") : t("settings.bannerCreated"));
      refresh();
      onSaved(saved.id);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "banner_needs_image") setErrors({ active: t("settings.errors.needsImage") });
      else if (error instanceof ApiError && error.status === 422) {
        const found = bodyFieldErrors(error);
        setErrors(Object.keys(found).length > 0 ? found : { form: error.message });
      } else toast.show(t("common.saveError"), "error");
    },
  });
  const remove = useMutation({
    mutationFn: () => must(browserApi.DELETE("/api/v1/staff/banners/{banner_id}", { params: { path: { banner_id: banner!.id } } })),
    onSuccess: () => {
      toast.show(t("settings.bannerDeleted"));
      refresh();
      onClose();
    },
    onError: () => toast.show(t("common.saveError"), "error"),
  });

  const submit = () => {
    const found: Record<string, string> = {};
    if (!texts.title_en.trim()) found.title_en = t("common.required");
    if (!texts.title_rw.trim()) found.title_rw = t("common.required");
    if (link.trim()) {
      if (!ctaPathOk(link.trim())) found.cta_url = t("settings.errors.link");
      if (!texts.cta_label_en.trim()) found.cta_label_en = t("settings.errors.label");
      if (!texts.cta_label_rw.trim()) found.cta_label_rw = t("settings.errors.label");
    }
    if (!/^\d{1,9}$/.test(position.trim())) found.position = t("editor.errors.threshold");
    if (starts && ends && ends < starts) found.ends_at = t("promotions.errors.dates");
    if (active && !banner?.image) found.active = t("settings.errors.needsImage");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };

  const text = (field: TextField, lang: "en" | "rw") => {
    const key = `${field}_${lang}` as const;
    return (
      <Field key={key} label={t(`settings.fields.${field}`, { lang: t(`settings.lang.${lang}`) })} error={errors[key]}>
        {(c) => <Input {...c} lang={lang} maxLength={BANNER_MAX[field]} value={texts[key]} onChange={(e) => setTexts((s) => ({ ...s, [key]: e.target.value }))} />}
      </Field>
    );
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={banner ? t("settings.editBanner") : t("settings.newBanner")}
      closeLabel={t("common.close")}
      className="max-w-[720px]"
      footer={
        <>
          {banner && (
            <Button type="button" variant="danger-outline" disabled={remove.isPending} onClick={() => remove.mutate()} className="mr-auto">
              {t("common.delete")}
            </Button>
          )}
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={save.isPending}>
            {banner ? t("common.saveChanges") : t("settings.createBanner")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        aria-label={banner ? t("settings.editBanner") : t("settings.newBanner")}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="-mx-6 flex max-h-[calc(100dvh-210px)] flex-col divide-y divide-bd overflow-y-auto overscroll-contain border-y border-bd"
      >
        <FormSection title={t("settings.sections.text")}>
          {TEXT_FIELDS.map((field) => (
            <div key={field} className="grid gap-3 sm:grid-cols-2">
              {text(field, "en")}
              {text(field, "rw")}
            </div>
          ))}
        </FormSection>

        <FormSection title={t("settings.sections.link")}>
          <Field label={t("settings.fields.link")} error={errors.cta_url} help={t("settings.linkHelp")}>
            {(c) => <Input {...c} maxLength={BANNER_MAX.cta_url} placeholder="/category/phones" value={link} onChange={(e) => setLink(e.target.value)} className="font-mono" />}
          </Field>
        </FormSection>

        <FormSection title={t("settings.sections.schedule")}>
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_160px]">
            <Field label={t("settings.starts")} error={errors.starts_at}>
              {(c) => <Input {...c} type="date" value={starts} onChange={(e) => setStarts(e.target.value)} />}
            </Field>
            <Field label={t("settings.ends")} error={errors.ends_at}>
              {(c) => <Input {...c} type="date" value={ends} min={starts || undefined} onChange={(e) => setEnds(e.target.value)} />}
            </Field>
            <Field label={t("settings.position")} error={errors.position}>
              {(c) => <Input {...c} inputMode="numeric" value={position} onChange={(e) => setPosition(e.target.value)} />}
            </Field>
          </div>
          <span className="text-cap text-mut">{t("settings.positionHelp")}</span>
        </FormSection>

        <FormSection title={t("settings.sections.image")}>
          {banner ? (
            <>
              <ImagePicker
                label={t("settings.image")}
                image={banner.image ?? null}
                uploadPath={`staff/banners/${banner.id}/image`}
                onRemove={() => must(browserApi.DELETE("/api/v1/staff/banners/{banner_id}/image", { params: { path: { banner_id: banner.id } } }))}
                onChanged={refresh}
              />
              <div className="flex flex-col gap-1">
                <Checkbox label={t("settings.showOnHome")} checked={active} onChange={(e) => setActive(e.target.checked)} />
                {errors.active && <span className="text-cap text-err-tx">{errors.active}</span>}
              </div>
            </>
          ) : (
            <p className="m-0 rounded-lg bg-light px-3.5 py-2.5 text-sm text-pri-h">{t("settings.imageAfterSave")}</p>
          )}
          {errors.form && (
            <p role="alert" className="m-0 text-sm text-err-tx">
              {errors.form}
            </p>
          )}
        </FormSection>
      </form>
    </Dialog>
  );
}

/** A titled group of fields in the banner dialog. */
function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-3 border-0 px-6 py-4">
      <legend className="t-over float-left mb-1 p-0 text-tx2">{title}</legend>
      {children}
    </fieldset>
  );
}
