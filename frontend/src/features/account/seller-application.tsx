"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Lock, Store, TriangleAlert, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { FormAlert } from "@/features/auth/auth-forms";
import { NewLinkForm } from "@/features/auth/email-verification";
import { useProfile } from "@/features/checkout/use-checkout";
import { applicationBody, canEditApplication, checkStoreForm, storeForm, type StoreForm, type StoreFormErrors } from "@/features/seller/store-form";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";

type Application = components["schemas"]["SellerStoreResponse"];
type Status = Application["status"];
export const APPLICATION_KEY = ["customer", "seller-application"] as const;

/** The caller's own application, or null when they have not applied (404). */
export function useSellerApplication() {
  return useQuery({
    queryKey: APPLICATION_KEY,
    queryFn: async (): Promise<Application | null> => {
      const { data, error, response } = await browserApi.GET("/api/v1/seller/application");
      if (response.status === 404) return null;
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
}

const STATUS_VIEW: Record<Status, { Icon: LucideIcon; tone: string }> = {
  pending: { Icon: Clock, tone: "bg-light text-pri-h" },
  approved: { Icon: CheckCircle2, tone: "bg-ok-bg text-ok-tx" },
  rejected: { Icon: TriangleAlert, tone: "bg-warn-bg text-warn-tx" },
  suspended: { Icon: Lock, tone: "bg-err-bg text-err-tx" },
};

/** /account/seller (ADR-014 phase 4): apply to sell, follow the application, edit or resubmit it,
 * and open the seller dashboard once approved. The backend decides who may apply. */
export function SellerApplicationView() {
  const t = useTranslations("store.account.seller");
  const query = useSellerApplication();
  if (query.isError)
    return (
      <section className="rounded-xl border border-bd bg-white p-6">
        <FormAlert tone="err">{t("errors.failed")}</FormAlert>
      </section>
    );
  if (query.isPending) return <Skeleton className="h-96 w-full rounded-xl" />;
  const application = query.data;
  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-col gap-2 rounded-xl border border-bd bg-white p-6 max-sm:p-4">
        <h1 className="t-h2">{t("title")}</h1>
        <p className="m-0 text-tx2">{t("intro")}</p>
      </section>
      {application && <StatusCard application={application} />}
      {canEditApplication(application?.status ?? null) && <ApplicationForm key={application?.submitted_at ?? "new"} application={application} />}
    </div>
  );
}

function StatusCard({ application }: { application: Application }) {
  const t = useTranslations("store.account.seller");
  const { Icon, tone } = STATUS_VIEW[application.status];
  return (
    <section aria-label={t("statusLabel")} className="flex items-start gap-4 rounded-xl border border-bd bg-white p-6 max-sm:p-4">
      <span aria-hidden="true" className={cx("flex size-12 flex-none items-center justify-center rounded-full", tone)}>
        <Icon size={22} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="text-cap font-semibold text-tx2 uppercase">{t("statusLabel")}</span>
        <b className="t-h3">{t(`status.${application.status}`)}</b>
        <p className="m-0 text-tx2">{t(`statusText.${application.status}`, { store: application.name })}</p>
        {application.status_reason && <p className="m-0 rounded-lg bg-page px-4 py-3 text-sm">{t("reason", { reason: application.status_reason })}</p>}
        {application.status === "approved" && (
          // The dashboard is outside the storefront's locale routing: a full page load.
          <a href="/seller" className={buttonClasses({ className: "w-fit" })}>
            <Store size={16} aria-hidden="true" />
            {t("openDashboard")}
          </a>
        )}
      </div>
    </section>
  );
}

function ApplicationForm({ application }: { application: Application | null }) {
  const t = useTranslations("store.account.seller");
  const client = useQueryClient();
  const { data: profile } = useProfile(true);
  const [form, setForm] = useState<StoreForm>(() => storeForm(application));
  const [errors, setErrors] = useState<StoreFormErrors>({});
  const [failure, setFailure] = useState<"verify" | "closed" | "exists" | "failed" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const update = <K extends keyof StoreForm>(key: K, value: StoreForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const resubmitting = application?.status === "rejected";

  const send = useMutation({
    mutationFn: async () => {
      const body = applicationBody(form);
      const call = application ? browserApi.PUT("/api/v1/seller/application", { body }) : browserApi.POST("/api/v1/seller/application", { body });
      const { data, error, response } = await call;
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (saved) => {
      setFailure(null);
      setDone(application && !resubmitting ? t("saved") : t("sent"));
      client.setQueryData(APPLICATION_KEY, saved);
    },
    onError: (error) => {
      setDone(null);
      const code = error instanceof ApiError ? error.code : null;
      if (code === "store_name_taken" || code === "store_slug_conflict") setErrors({ name: t("errors.nameTaken") });
      else if (code === "email_verification_required") setFailure("verify");
      else if (code === "store_application_closed") setFailure("closed");
      else if (code === "store_exists") setFailure("exists");
      else setFailure("failed");
      if (code === "store_application_closed" || code === "store_exists") void client.invalidateQueries({ queryKey: APPLICATION_KEY });
    },
  });

  const submit = () => {
    const found = checkStoreForm(form);
    setErrors(Object.fromEntries(Object.entries(found).map(([key, code]) => [key, t(`errors.${code}`)])));
    if (Object.keys(found).length === 0) send.mutate();
  };
  const optional = <span className="font-normal text-tx2">{t("optional")}</span>;

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col gap-4 rounded-xl border border-bd bg-white p-6 max-sm:p-4"
    >
      <h2 className="t-h3">{t("formTitle")}</h2>
      {done && <FormAlert tone="ok">{done}</FormAlert>}
      {failure === "verify" ? (
        <div className="flex flex-col gap-3">
          <FormAlert tone="err">{t("verifyFirst")}</FormAlert>
          {profile?.email && <NewLinkForm email={profile.email} nested />}
        </div>
      ) : (
        failure && <FormAlert tone="err">{t(`errors.${failure}`)}</FormAlert>
      )}
      <Field label={t("name")} error={errors.name} help={t("nameHelp")}>
        {(c) => <Input {...c} maxLength={120} autoComplete="organization" value={form.name} onChange={(e) => update("name", e.target.value)} />}
      </Field>
      <Field
        label={
          <>
            {t("about")} {optional}
          </>
        }
        error={errors.description}
      >
        {(c) => <Textarea {...c} rows={4} maxLength={2000} value={form.description} onChange={(e) => update("description", e.target.value)} />}
      </Field>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("email")} error={errors.email}>
          {(c) => <Input {...c} type="email" maxLength={254} autoComplete="email" value={form.email} onChange={(e) => update("email", e.target.value)} />}
        </Field>
        <Field label={t("phone")} error={errors.phone}>
          {(c) => <Input {...c} type="tel" inputMode="tel" autoComplete="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} />}
        </Field>
        <Field label={t("district")} error={errors.district}>
          {(c) => <Input {...c} maxLength={120} value={form.district} onChange={(e) => update("district", e.target.value)} />}
        </Field>
        <Field
          label={
            <>
              {t("sector")} {optional}
            </>
          }
          error={errors.sector}
        >
          {(c) => <Input {...c} maxLength={120} value={form.sector} onChange={(e) => update("sector", e.target.value)} />}
        </Field>
      </div>
      <Field
        label={
          <>
            {t("street")} {optional}
          </>
        }
        error={errors.street}
      >
        {(c) => <Input {...c} maxLength={240} autoComplete="street-address" value={form.street} onChange={(e) => update("street", e.target.value)} />}
      </Field>
      <Button type="submit" disabled={send.isPending} className="w-fit">
        {!application ? t("submit") : resubmitting ? t("resubmit") : t("save")}
      </Button>
    </form>
  );
}
