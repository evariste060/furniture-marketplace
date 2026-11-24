"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, Clock, Lock, Pencil, Send, Store, TriangleAlert, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, useRef, useState } from "react";
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

/** The caller's own application, or null when they have not applied (404). `enabled` is false
 * until a customer is signed in (the account menus ask before the session is known). */
export function useSellerApplication(enabled = true) {
  return useQuery({
    queryKey: APPLICATION_KEY,
    enabled,
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
 * and open the seller dashboard once approved. The backend decides who may apply. The form is a
 * step-by-step wizard (SC-08). */
export function SellerApplicationView() {
  const t = useTranslations("store.account.seller");
  const query = useSellerApplication();
  if (query.isError)
    return (
      <section className="rounded-xl border border-bd bg-card p-6">
        <FormAlert tone="err">{t("errors.failed")}</FormAlert>
      </section>
    );
  if (query.isPending) return <Skeleton className="h-96 w-full rounded-xl" />;
  const application = query.data;
  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-col gap-2 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
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
    <section aria-label={t("statusLabel")} className="flex items-start gap-4 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
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

/** The application's steps (SC-08): each holds some of the store fields, checked with the same
 * rules as before (checkStoreForm) before the next step opens. Review shows everything once more. */
const STEPS = [
  { key: "store", fields: ["name", "description"] },
  { key: "contact", fields: ["email", "phone"] },
  { key: "location", fields: ["district", "sector", "street"] },
  { key: "review", fields: [] },
] as const satisfies readonly { key: string; fields: readonly (keyof StoreForm)[] }[];
type StepIndex = 0 | 1 | 2 | 3;
const REVIEW: StepIndex = 3;

/** The step that holds a field, for sending the shopper back to what needs fixing. */
function stepOf(field: keyof StoreForm): StepIndex {
  return STEPS.findIndex((s) => (s.fields as readonly (keyof StoreForm)[]).includes(field)) as StepIndex;
}

/** The application as a wizard (SC-08): Step n of 4 with a progress bar, Next and Back, and Submit
 * on the review step. Each step is checked before moving on; the answers are kept while moving
 * back and forth. The same backend calls as before: POST for a new application, PUT to edit a
 * pending one or resubmit a rejected one. A store name the backend refuses brings the shopper
 * back to the first step with the message. */
function ApplicationForm({ application }: { application: Application | null }) {
  const t = useTranslations("store.account.seller");
  const client = useQueryClient();
  const { data: profile } = useProfile(true);
  const [form, setForm] = useState<StoreForm>(() => storeForm(application));
  const [errors, setErrors] = useState<StoreFormErrors>({});
  const [step, setStep] = useState<StepIndex>(0);
  const [failure, setFailure] = useState<"verify" | "closed" | "exists" | "failed" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const update = <K extends keyof StoreForm>(key: K, value: StoreForm[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };
  const resubmitting = application?.status === "rejected";
  const current = STEPS[step];

  const goTo = (next: StepIndex) => {
    setStep(next);
    // Focus the new step's title, so keyboard and screen reader users start at the top of it.
    requestAnimationFrame(() => heading.current?.focus());
  };

  /** The problems in the given fields, as messages; shown, and true when there are none. */
  const check = (fields: readonly (keyof StoreForm)[]) => {
    const found = checkStoreForm(form);
    const mine = Object.fromEntries(Object.entries(found).filter(([key]) => fields.includes(key as keyof StoreForm)).map(([key, code]) => [key, t(`errors.${code}`)]));
    setErrors(mine);
    return Object.keys(mine).length === 0;
  };

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
      if (code === "store_name_taken" || code === "store_slug_conflict") {
        setErrors({ name: t("errors.nameTaken") });
        goTo(0);
      } else if (code === "email_verification_required") setFailure("verify");
      else if (code === "store_application_closed") setFailure("closed");
      else if (code === "store_exists") setFailure("exists");
      else setFailure("failed");
      if (code === "store_application_closed" || code === "store_exists") void client.invalidateQueries({ queryKey: APPLICATION_KEY });
    },
  });

  const next = () => {
    if (step === REVIEW) {
      // Everything once more: a problem sends the shopper to its step.
      const found = checkStoreForm(form);
      const first = (Object.keys(found) as (keyof StoreForm)[])[0];
      if (first) {
        setErrors(Object.fromEntries(Object.entries(found).map(([key, code]) => [key, t(`errors.${code}`)])));
        goTo(stepOf(first));
        return;
      }
      send.mutate();
      return;
    }
    if (check(current.fields)) {
      setDone(null);
      goTo((step + 1) as StepIndex);
    }
  };
  const back = () => {
    setErrors({});
    goTo((step - 1) as StepIndex);
  };
  const optional = <span className="font-normal text-tx2">{t("optional")}</span>;
  const submitLabel = !application ? t("submit") : resubmitting ? t("resubmit") : t("save");

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        next();
      }}
      className="flex flex-col gap-5 rounded-xl border border-bd bg-card p-6 max-sm:p-4"
    >
      <Progress step={step} />
      <h2 ref={heading} tabIndex={-1} className="t-h3 outline-none">
        {t(`steps.${current.key}.title`)}
      </h2>
      <p className="-mt-3 m-0 text-sm text-tx2">{t(`steps.${current.key}.text`)}</p>
      {done && <FormAlert tone="ok">{done}</FormAlert>}
      {failure === "verify" ? (
        <div className="flex flex-col gap-3">
          <FormAlert tone="err">{t("verifyFirst")}</FormAlert>
          {profile?.email && <NewLinkForm email={profile.email} nested />}
        </div>
      ) : (
        failure && <FormAlert tone="err">{t(`errors.${failure}`)}</FormAlert>
      )}

      {step === 0 && (
        <>
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
        </>
      )}
      {step === 1 && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={t("email")} error={errors.email}>
            {(c) => <Input {...c} type="email" maxLength={254} autoComplete="email" value={form.email} onChange={(e) => update("email", e.target.value)} />}
          </Field>
          <Field label={t("phone")} error={errors.phone}>
            {(c) => <Input {...c} type="tel" inputMode="tel" autoComplete="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} />}
          </Field>
        </div>
      )}
      {step === 2 && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
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
        </>
      )}
      {step === REVIEW && (
        <div className="flex flex-col gap-3">
          {STEPS.slice(0, REVIEW).map((s, i) => (
            <section key={s.key} aria-labelledby={`review-${s.key}`} className="rounded-lg border border-bd p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 id={`review-${s.key}`} className="m-0 text-sm font-semibold">
                  {t(`steps.${s.key}.title`)}
                </h3>
                <button
                  type="button"
                  onClick={() => goTo(i as StepIndex)}
                  aria-label={t("editStep", { step: t(`steps.${s.key}.title`) })}
                  className="flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-sm font-semibold text-pri-h hover:text-pri-fg"
                >
                  <Pencil size={14} aria-hidden="true" />
                  {t("edit")}
                </button>
              </div>
              <dl className="m-0 mt-2 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[160px_1fr]">
                {s.fields.map((field) => (
                  <Fragment key={field}>
                    <dt className="text-tx2">{t(FIELD_LABEL[field])}</dt>
                    <dd className="m-0 break-words whitespace-pre-line">{form[field].trim() || <span className="text-mut">{t("notGiven")}</span>}</dd>
                  </Fragment>
                ))}
              </dl>
            </section>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bd pt-4">
        {step > 0 ? (
          <Button type="button" variant="neutral" onClick={back} disabled={send.isPending}>
            <ArrowLeft size={16} aria-hidden="true" />
            {t("back")}
          </Button>
        ) : (
          <span />
        )}
        <Button type="submit" disabled={send.isPending}>
          {step === REVIEW ? (
            <>
              <Send size={16} aria-hidden="true" />
              {submitLabel}
            </>
          ) : (
            <>
              {t("next")}
              <ArrowRight size={16} aria-hidden="true" />
            </>
          )}
        </Button>
      </div>
    </form>
  );
}

const FIELD_LABEL: Record<keyof StoreForm, "name" | "about" | "email" | "phone" | "district" | "sector" | "street"> = {
  name: "name",
  description: "about",
  email: "email",
  phone: "phone",
  district: "district",
  sector: "sector",
  street: "street",
};

/** "Step 2 of 4 · Contact" with a bar per step: done and current ones filled. */
function Progress({ step }: { step: StepIndex }) {
  const t = useTranslations("store.account.seller");
  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-cap font-semibold text-tx2" aria-live="polite">
        {t("stepOf", { step: step + 1, total: STEPS.length })} · <span className="text-pri-h">{t(`steps.${STEPS[step].key}.title`)}</span>
      </p>
      <ol className="m-0 grid list-none grid-cols-4 gap-1.5 p-0" aria-label={t("progress")}>
        {STEPS.map((s, i) => (
          <li key={s.key} aria-current={i === step ? "step" : undefined} className="flex flex-col gap-1.5">
            <span className={cx("h-1.5 rounded-full transition-colors duration-200 motion-reduce:transition-none", i <= step ? "bg-pri" : "bg-bd")} />
            <span className={cx("text-xs max-sm:sr-only", i === step ? "font-semibold text-tx" : "text-tx2")}>{t(`steps.${s.key}.title`)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
