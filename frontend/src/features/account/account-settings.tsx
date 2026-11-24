"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, KeyRound, LogOut, Plus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Input, PhoneInput, Select } from "@/components/ui/form";
import { GoogleIcon } from "@/components/ui/google-icon";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { FormAlert, PasswordInput } from "@/features/auth/auth-forms";
import { startGoogle, useGoogleMessage, useResetWhenRestored } from "@/features/auth/google-sign-in";
import { useProfile, useSavedAddresses } from "@/features/checkout/use-checkout";
import { useZones } from "@/features/checkout/use-zones";
import { SESSION_KEY } from "@/features/session/use-session";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api/errors";
import { passwordOk } from "@/lib/auth";
import { localPhone, NAME_MAX, NOTE_MAX, splitName, STREET_MAX, TEXT_MAX } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { formatPhone } from "@/lib/format";
import { useAddressMutations, useChangePassword, useSignInMethods, useUpdateProfile, type Address } from "./use-account";

/** Addresses.dc.html and Profile.dc.html. Profile adds Connected accounts (Continue with Google,
 * ADR-006 amendment 2026-11-11) in the same card style. */

function focusFirstError(form: HTMLFormElement | null) {
  requestAnimationFrame(() => form?.querySelector<HTMLElement>("[aria-invalid=true]")?.focus());
}

function spacedPhone(value: string | null | undefined): string {
  const local = localPhone(value ?? "");
  return local ? `${local.slice(0, 3)} ${local.slice(3, 6)} ${local.slice(6)}` : "";
}

// ---- Addresses.dc.html -------------------------------------------------------------------------

type AddressDraft = { label: string; name: string; phone: string; district: string; sector: string; street: string; landmark: string; isDefault: boolean };
type DraftErrors = Partial<Record<"name" | "phone" | "district" | "street", string>>;

function draftFrom(address: Address | null, fallbackName: string, fallbackPhone: string, first: boolean): AddressDraft {
  return {
    label: address?.label ?? "",
    name: address?.recipient_name ?? fallbackName,
    phone: spacedPhone(address?.phone ?? fallbackPhone),
    district: address?.district ?? "",
    sector: address?.sector ?? "",
    street: address?.street_address ?? "",
    landmark: address?.delivery_instructions ?? "",
    isDefault: address?.is_default ?? first,
  };
}

export function AddressesView() {
  const t = useTranslations("store.account");
  const tc = useTranslations("store.checkout");
  const toast = useToast();
  const addresses = useSavedAddresses(true);
  const profile = useProfile(true);
  const { data: zones } = useZones();
  const { remove, makeDefault } = useAddressMutations();
  const [editing, setEditing] = useState<Address | "new" | null>(null);
  const [deleting, setDeleting] = useState<Address | null>(null);
  const list = addresses.data ?? [];
  const inZone = (a: Address) => (zones?.items ?? []).some((z) => z.district === a.district);
  const linkButton = "cursor-pointer border-0 bg-transparent p-0 text-sm font-medium";

  function failed(error: unknown) {
    toast.show(t(error instanceof ApiError && error.status === 409 ? "addressConflict" : "saveFailed"), "error");
  }

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="t-h1 text-head">{t("addressesTitle")}</h1>
        <Button size="sm" onClick={() => setEditing("new")}>
          <Plus size={16} aria-hidden="true" />
          {t("addAddress")}
        </Button>
      </div>
      <div className="flex flex-wrap items-start gap-5">
        <div className="flex flex-[1_1_340px] flex-col gap-3.5">
          {addresses.isPending ? (
            [0, 1].map((i) => <Skeleton key={i} className="h-32 w-full rounded-xl" />)
          ) : addresses.isError ? (
            <Card padding={20} role="alert" className="flex flex-col items-start gap-3">
              <p className="text-tx2">{t("loadFailed")}</p>
              <Button variant="outline" size="sm" onClick={() => addresses.refetch()}>
                {t("retry")}
              </Button>
            </Card>
          ) : list.length === 0 ? (
            <Card padding={20}>
              <p className="text-tx2">{t("noAddresses")}</p>
            </Card>
          ) : (
            list.map((a) => (
              <article
                key={a.id}
                aria-label={a.label || tc("addressFallback")}
                className={cx("flex flex-col gap-1.5 rounded-xl bg-card", a.is_default ? "border-2 border-pri p-[19px]" : "border border-bd p-5")}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <b className="font-semibold">{a.label || tc("addressFallback")}</b>
                  {a.is_default && <Badge tone="soft-info">{tc("default")}</Badge>}
                </div>
                <span className="text-sm text-tx2">
                  {a.recipient_name} · {formatPhone(a.phone)}
                </span>
                <span className="text-sm text-tx2">{[a.street_address, a.sector, a.district].filter(Boolean).join(", ")}</span>
                {a.delivery_instructions && <span className="text-cap text-tx2">{t("landmarkLine", { text: a.delivery_instructions })}</span>}
                {zones && !inZone(a) && (
                  <Badge tone="soft-warn" className="self-start">
                    {tc("outsideZones")}
                  </Badge>
                )}
                <div className="flex flex-wrap gap-4 pt-1.5">
                  <button type="button" className={cx(linkButton, "text-pri-fg")} onClick={() => setEditing(a)}>
                    {t("edit")}
                    <span className="sr-only"> {a.label || tc("addressFallback")}</span>
                  </button>
                  <button type="button" className={cx(linkButton, "text-err-fg")} onClick={() => setDeleting(a)}>
                    {t("delete")}
                    <span className="sr-only"> {a.label || tc("addressFallback")}</span>
                  </button>
                  {!a.is_default && (
                    <button
                      type="button"
                      className={cx(linkButton, "text-tx2")}
                      disabled={makeDefault.isPending}
                      onClick={() => makeDefault.mutate(a.id, { onSuccess: () => toast.show(t("defaultSet")), onError: failed })}
                    >
                      {t("setDefault")}
                      <span className="sr-only"> ({a.label || tc("addressFallback")})</span>
                    </button>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      </div>
      {/* Adding or editing an address opens the form in a popup; saving or closing it closes the
       * popup. A click outside does not, so a half-filled form is never lost. */}
      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={t(editing === "new" ? "newAddress" : "editAddress")}
        closeLabel={t("close")}
        className="max-h-[calc(100dvh-32px)] max-w-[560px]! overflow-y-auto"
      >
        {editing && (
          <AddressForm
            key={editing === "new" ? "new" : editing.id}
            address={editing === "new" ? null : editing}
            first={list.length === 0}
            fallbackName={profile.data?.full_name ?? ""}
            fallbackPhone={profile.data?.phone ?? ""}
            districts={[...new Set((zones?.items ?? []).map((z) => z.district as string))]}
            onDone={() => setEditing(null)}
            onFailed={failed}
          />
        )}
      </Dialog>
      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title={t("deleteTitle")}
        closeLabel={t("close")}
        footer={
          <>
            <Button variant="neutral" onClick={() => setDeleting(null)}>
              {t("cancel")}
            </Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() =>
                deleting &&
                remove.mutate(deleting.id, {
                  onSuccess: () => {
                    if (editing !== "new" && editing?.id === deleting.id) setEditing(null);
                    setDeleting(null);
                    toast.show(t("deleted"));
                  },
                  onError: (error) => (setDeleting(null), failed(error)),
                })
              }
            >
              {t("delete")}
            </Button>
          </>
        }
      >
        <p className="text-tx2">{deleting && t("deleteText", { label: deleting.label || tc("addressFallback") })}</p>
      </Dialog>
    </>
  );
}

function AddressForm({
  address,
  first,
  fallbackName,
  fallbackPhone,
  districts,
  onDone,
  onFailed,
}: {
  address: Address | null;
  first: boolean;
  fallbackName: string;
  fallbackPhone: string;
  districts: string[];
  onDone: () => void;
  onFailed: (error: unknown) => void;
}) {
  const t = useTranslations("store.account");
  const tc = useTranslations("store.checkout");
  const toast = useToast();
  const { create, update } = useAddressMutations();
  const form = useRef<HTMLFormElement>(null);
  const [draft, setDraft] = useState(() => draftFrom(address, fallbackName, fallbackPhone, first));
  const [errors, setErrors] = useState<DraftErrors>({});
  const set = (key: keyof AddressDraft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [key]: e.target.value }));
  // An address outside the delivery zones keeps its district as an option, so editing it works.
  const options = address?.district && !districts.includes(address.district) ? [...districts, address.district] : districts;
  const pending = create.isPending || update.isPending;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: DraftErrors = {};
    if (draft.name.trim().length < 2) found.name = t("nameRequired");
    const local = localPhone(draft.phone);
    if (!local) found.phone = t(draft.phone.trim() ? "phoneInvalid" : "phoneRequired");
    if (!draft.district) found.district = tc("errors.district.required");
    if (draft.street.trim().length < 3) found.street = tc(draft.street.trim() ? "errors.street.invalid" : "errors.street.required");
    setErrors(found);
    if (Object.keys(found).length) return focusFirstError(form.current);
    const optional = (value: string) => value.trim() || null;
    const body = {
      label: optional(draft.label),
      recipient_name: draft.name.trim(),
      phone: `0${local}`,
      district: draft.district,
      sector: optional(draft.sector),
      street_address: draft.street.trim(),
      delivery_instructions: optional(draft.landmark),
    };
    const done = { onSuccess: () => (toast.show(t("saved")), onDone()), onError: onFailed };
    if (address) {
      // The current default cannot be un-set (another address is made default instead).
      const isDefault = address.is_default ? undefined : draft.isDefault;
      update.mutate({ id: address.id, body: { ...body, is_default: isDefault } }, done);
    } else create.mutate({ ...body, is_default: draft.isDefault }, done);
  }

  return (
    <form ref={form} onSubmit={onSubmit} noValidate aria-label={t(address ? "editAddress" : "newAddress")} className="flex flex-col gap-3.5">
      <Field label={t("label")} help={t("labelHelp")}>
        {(c) => <Input {...c} value={draft.label} onChange={set("label")} maxLength={80} />}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("recipient")} error={errors.name}>
          {(c) => <Input {...c} value={draft.name} onChange={set("name")} maxLength={NAME_MAX * 2} autoComplete="name" />}
        </Field>
        <Field label={t("phone")} error={errors.phone}>
          {(c) => <PhoneInput {...c} value={draft.phone} onChange={set("phone")} maxLength={16} placeholder="788 000 111" />}
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={tc("district")} error={errors.district}>
          {(c) => (
            <Select {...c} value={draft.district} onChange={set("district")} autoComplete="address-level2">
              <option value="">{tc("chooseDistrict")}</option>
              {options.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={tc("sector")}>
          {(c) => <Input {...c} value={draft.sector} onChange={set("sector")} maxLength={TEXT_MAX} autoComplete="address-level3" />}
        </Field>
      </div>
      <Field label={t("street")} error={errors.street}>
        {(c) => <Input {...c} value={draft.street} onChange={set("street")} maxLength={STREET_MAX} autoComplete="street-address" />}
      </Field>
      <Field label={tc("landmark")}>
        {(c) => <Input {...c} value={draft.landmark} onChange={set("landmark")} maxLength={NOTE_MAX} />}
      </Field>
      <Checkbox
        checked={draft.isDefault}
        disabled={Boolean(address?.is_default) || first}
        onChange={(e) => setDraft((d) => ({ ...d, isDefault: e.target.checked }))}
        label={t("useDefault")}
      />
      <div className="flex gap-2.5">
        <Button type="submit" className="flex-1" disabled={pending}>
          {t("saveAddress")}
        </Button>
        <Button variant="neutral" onClick={onDone}>
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}

// ---- Profile.dc.html ---------------------------------------------------------------------------

export function ProfileView() {
  const t = useTranslations("store.account");
  const profile = useProfile(true);
  const methods = useSignInMethods();
  return (
    <div className="flex max-w-[820px] flex-col gap-4">
      <h1 className="t-h1 text-head">{t("profileTitle")}</h1>
      {profile.isPending ? (
        <Skeleton className="h-64 w-full rounded-xl" />
      ) : profile.isError || !profile.data ? (
        <Card padding={24} role="alert" className="flex flex-col items-start gap-3">
          <p className="text-tx2">{t("loadFailed")}</p>
          <Button variant="outline" size="sm" onClick={() => profile.refetch()}>
            {t("retry")}
          </Button>
        </Card>
      ) : (
        <DetailsForm fullName={profile.data.full_name ?? ""} phone={profile.data.phone ?? ""} email={profile.data.email ?? ""} />
      )}
      <ConnectedAccounts methods={methods} />
      {/* A customer created with Google has no current password to type: they set one first. */}
      {methods.data?.has_password === false ? <SetPassword /> : <PasswordForm />}
      <LogoutEverywhere />
    </div>
  );
}

function DetailsForm({ fullName, phone: initialPhone, email }: { fullName: string; phone: string; email: string }) {
  const t = useTranslations("store.account");
  const ta = useTranslations("store.auth");
  const save = useUpdateProfile();
  const form = useRef<HTMLFormElement>(null);
  const [name] = useState(() => splitName(fullName));
  const [first, setFirst] = useState(name.firstName);
  const [last, setLast] = useState(name.lastName);
  const [phone, setPhone] = useState(spacedPhone(initialPhone));
  const [errors, setErrors] = useState<Partial<Record<"first" | "last" | "phone", string>>>({});
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    if (!first.trim()) found.first = ta("firstNameRequired");
    if (!last.trim()) found.last = ta("lastNameRequired");
    const local = localPhone(phone);
    if (phone.trim() && !local) found.phone = ta("phoneInvalid");
    if (!phone.trim() && initialPhone) found.phone = ta("phoneRequired");
    setErrors(found);
    setSaved(false);
    setFailure(null);
    if (Object.keys(found).length) return focusFirstError(form.current);
    const body: { full_name: string; phone?: string } = { full_name: `${first.trim()} ${last.trim()}` };
    if (local && `0${local}` !== `0${localPhone(initialPhone) ?? ""}`) body.phone = `0${local}`;
    save.mutate(body, {
      onSuccess: () => setSaved(true),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 409) {
          setErrors({ phone: ta("phoneTaken") });
          focusFirstError(form.current);
        } else setFailure(t("saveFailed"));
      },
    });
  }

  return (
    <form ref={form} onSubmit={onSubmit} noValidate aria-labelledby="details-title" className="flex flex-col gap-4 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
      <h2 id="details-title" className="t-h3">
        {t("personalDetails")}
      </h2>
      {failure && <FormAlert>{failure}</FormAlert>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={ta("firstName")} error={errors.first}>
          {(c) => <Input {...c} value={first} onChange={(e) => (setFirst(e.target.value), setSaved(false))} maxLength={NAME_MAX} autoComplete="given-name" />}
        </Field>
        <Field label={ta("lastName")} error={errors.last}>
          {(c) => <Input {...c} value={last} onChange={(e) => (setLast(e.target.value), setSaved(false))} maxLength={NAME_MAX} autoComplete="family-name" />}
        </Field>
        <Field label={ta("phone")} error={errors.phone}>
          {(c) => <PhoneInput {...c} value={phone} onChange={(e) => (setPhone(e.target.value), setSaved(false))} maxLength={16} placeholder="788 000 111" />}
        </Field>
        <Field label={ta("email")} help={t("emailFixed")}>
          {(c) => <Input {...c} type="email" value={email} readOnly disabled />}
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <Button type="submit" disabled={save.isPending}>
          {t("saveChanges")}
        </Button>
        <span role="status" className="flex items-center gap-1.5 text-sm text-ok-tx">
          {saved && (
            <>
              <CircleCheck size={16} aria-hidden="true" />
              {t("savedShort")}
            </>
          )}
        </span>
      </div>
    </form>
  );
}

function PasswordForm() {
  const t = useTranslations("store.account");
  const ta = useTranslations("store.auth");
  const change = useChangePassword();
  const form = useRef<HTMLFormElement>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Partial<Record<"current" | "next" | "confirm", string>>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    if (!current) found.current = t("currentRequired");
    if (!passwordOk(next)) found.next = ta("passwordRule");
    if (confirm !== next) found.confirm = ta("confirmMismatch");
    setErrors(found);
    setFailure(null);
    setDone(false);
    if (Object.keys(found).length) return focusFirstError(form.current);
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
          setDone(true);
        },
        onError: (error) => {
          const code = error instanceof ApiError ? error.code : "";
          if (code === "current_password_invalid") {
            setErrors({ current: t("currentInvalid") });
            focusFirstError(form.current);
          } else if (code === "rate_limited") setFailure(t("passwordLimited"));
          else if (error instanceof ApiError && error.status === 422) setErrors({ next: ta("passwordRule") });
          else setFailure(t("saveFailed"));
        },
      },
    );
  }

  return (
    <form ref={form} onSubmit={onSubmit} noValidate aria-labelledby="password-title" className="flex flex-col gap-4 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
      <h2 id="password-title" className="t-h3">
        {t("changePassword")}
      </h2>
      {failure && <FormAlert>{failure}</FormAlert>}
      {done && <FormAlert tone="ok">{t("passwordChanged")}</FormAlert>}
      <Field label={t("currentPassword")} error={errors.current} className="max-w-[420px]">
        {(c) => <PasswordInput control={c} value={current} onChange={setCurrent} autoComplete="current-password" />}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={ta("newPassword")} error={errors.next} help={ta("passwordRule")}>
          {(c) => <PasswordInput control={c} value={next} onChange={setNext} autoComplete="new-password" />}
        </Field>
        <Field label={ta("confirmPassword")} error={errors.confirm}>
          {(c) => <PasswordInput control={c} value={confirm} onChange={setConfirm} autoComplete="new-password" />}
        </Field>
      </div>
      <div>
        <Button type="submit" variant="outline" disabled={change.isPending}>
          {t("updatePassword")}
        </Button>
      </div>
    </form>
  );
}

/** Connected accounts: whether Google is linked, a Connect action when it is not, and whether the
 * account also has a password. Unlinking is not offered (the backend has no such operation). The
 * link callback comes back here with ?google=linked or ?google_error=<code>. */
function ConnectedAccounts({ methods }: { methods: ReturnType<typeof useSignInMethods> }) {
  const t = useTranslations("store.account");
  const params = useSearchParams();
  const locale = useLocale();
  const client = useQueryClient();
  const googleMessage = useGoogleMessage();
  const [failure, setFailure] = useState<string | null>(() => params.get("google_error"));
  const [pending, setPending] = useState(false);
  useResetWhenRestored(setPending);
  const linkedNow = params.get("google") === "linked" && !failure;

  async function connect() {
    setPending(true);
    setFailure(null);
    const code = await startGoogle("/api/auth/google/link/start", { locale, returnTo: "/account/profile" });
    setPending(false);
    setFailure(code);
    if (code === "google_already_linked") await methods.refetch();
    // The session ended: the account area then sends the visitor to sign in.
    if (code === "token_missing" || code === "session_invalid") await client.invalidateQueries({ queryKey: SESSION_KEY });
  }

  const data = methods.data;
  return (
    <section aria-labelledby="connected-title" className="flex flex-col gap-4 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
      <h2 id="connected-title" className="t-h3">
        {t("connectedTitle")}
      </h2>
      {linkedNow && <FormAlert tone="ok">{t("googleLinkedNow")}</FormAlert>}
      {failure && <FormAlert tone={failure === "google_already_linked" ? "ok" : "err"}>{googleMessage(failure)}</FormAlert>}
      {methods.isPending ? (
        <Skeleton className="h-28 w-full rounded-lg" />
      ) : methods.isError || !data ? (
        <div role="alert" className="flex flex-col items-start gap-3">
          <p className="text-tx2">{t("loadFailed")}</p>
          <Button variant="outline" size="sm" onClick={() => methods.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          <li className="flex flex-wrap items-center justify-between gap-3 border-b border-bd pb-4">
            <span className="flex min-w-0 items-center gap-3">
              <GoogleIcon size={24} className="flex-none" />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-2">
                  <b className="font-semibold">{t("googleName")}</b>
                  <Badge tone={data.google_linked ? "soft-ok" : "soft-neutral"} pill>
                    {t(data.google_linked ? "connected" : "notConnected")}
                  </Badge>
                </span>
                <span className="text-sm text-tx2">{t(data.google_linked ? "googleConnectedText" : "googleNotConnectedText")}</span>
              </span>
            </span>
            {!data.google_linked && (
              <Button variant="outline" size="sm" disabled={pending} aria-busy={pending || undefined} onClick={connect}>
                {pending ? t("connectingGoogle") : t("connectGoogle")}
              </Button>
            )}
          </li>
          <li className="flex flex-wrap items-center justify-between gap-3 pt-4">
            <span className="flex min-w-0 items-center gap-3">
              <KeyRound size={24} aria-hidden="true" className="flex-none text-tx2" />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-2">
                  <b className="font-semibold">{t("passwordName")}</b>
                  <Badge tone={data.has_password ? "soft-ok" : "soft-neutral"} pill>
                    {t(data.has_password ? "passwordSet" : "passwordNotSet")}
                  </Badge>
                </span>
                <span className="text-sm text-tx2">{t(data.has_password ? "passwordSetText" : "passwordNotSetText")}</span>
              </span>
            </span>
          </li>
        </ul>
      )}
    </section>
  );
}

/** For a customer created with Google: no current password exists, so the change form would
 * mislead. They set one with a reset code, the existing forgot-password flow. */
function SetPassword() {
  const t = useTranslations("store.account");
  return (
    <section aria-labelledby="set-password-title" className="flex flex-col items-start gap-3 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
      <h2 id="set-password-title" className="t-h3">
        {t("setPasswordTitle")}
      </h2>
      <p className="text-sm text-tx2">{t("setPasswordText")}</p>
      <Link href="/forgot-password" className={buttonClasses({ variant: "outline" })}>
        {t("setPassword")}
      </Link>
    </section>
  );
}

function LogoutEverywhere() {
  const t = useTranslations("store.account");
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  async function onClick() {
    setPending(true);
    await fetch("/api/auth/logout-all", { method: "POST" }).catch(() => undefined);
    // The account area then sends the visitor to sign in.
    client.removeQueries({ queryKey: ["customer"] });
    client.setQueryData(SESSION_KEY, null);
    await client.invalidateQueries();
  }
  return (
    <section aria-labelledby="logout-all-title" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-err-bd bg-card p-6 max-sm:p-4">
      <span className="flex flex-col gap-0.5">
        <b id="logout-all-title" className="font-semibold">
          {t("logoutAllTitle")}
        </b>
        <span className="text-sm text-tx2">{t("logoutAllText")}</span>
      </span>
      <Button variant="danger-outline" size="sm" disabled={pending} onClick={onClick}>
        <LogOut size={16} aria-hidden="true" />
        {t("logoutAll")}
      </Button>
    </section>
  );
}
