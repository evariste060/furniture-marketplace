"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CalendarDays, Check, CircleAlert, CircleCheck, Pencil, Send } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { Fragment, useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Field, Input, PhoneInput, RadioOption, Textarea } from "@/components/ui/form";
import { kigaliDay } from "@/features/contact/quote";
import { useStoreContact } from "@/features/contact/use-store-contact";
import { Link } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { localPhone } from "@/lib/checkout";
import { whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import type { ApiImage } from "@/lib/images";
import {
  CLIENT_TYPES,
  EMPTY_REQUEST,
  firstErrorStep,
  REQUEST_LIMITS,
  REQUEST_STEPS,
  serviceRequestServerErrors,
  stepErrors,
  validateServiceRequest,
  type RequestStep,
  type ServiceRequestBody,
  type ServiceRequestErrors,
  type ServiceRequestForm as Form,
} from "./request";
import { ServiceIcon, type ServiceIconKey } from "./service-icon";
import { ServiceImage } from "./service-image";

const noSubscribe = () => () => {};

/** Today in Kigali once in the browser; null while prerendering. */
function useToday(): string | null {
  return useSyncExternalStore(
    noSubscribe,
    () => kigaliDay(),
    () => null,
  );
}

/** The service being requested, as GET /services/{slug} gives it. */
export type WizardService = {
  slug: string;
  name: string;
  short_description: string;
  icon: ServiceIconKey;
  image: ApiImage | null;
  items: string[];
};

/** The steps a customer moves through (the last, the confirmation, is reached by sending). */
const FORM_STEPS = REQUEST_STEPS.filter((s) => s !== "done");

/** "+250 788 123 456" from what was typed (the number the request is sent with). */
function shownPhone(phone: string): string {
  const local = localPhone(phone);
  return local ? `+250 ${local.slice(0, 3)} ${local.slice(3, 6)} ${local.slice(6)}` : phone;
}

/** "Request this service" as a step-by-step wizard (owner, 2026-11-17; ADR-013): the service, a
 * preferred date, the customer's details, a review, then the confirmation. The fields, their rules
 * (validateServiceRequest) and the request (POST /services/{slug}/requests) are the ones the form
 * had; only the order they are asked in is new. What was typed is kept while moving back and forth;
 * Continue checks the step's own fields first, and Send checks everything again (and goes back to
 * the step with the mistake, also when the server finds one). There are no time slots: the team
 * calls the customer to agree the exact time. */
export function ServiceRequestWizard({ service }: { service: WizardService }) {
  const t = useTranslations("store.services");
  const tw = useTranslations("store.services.wizard");
  const locale = useLocale() === "rw" ? "rw" : "en";
  const formRef = useRef<HTMLFormElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [step, setStep] = useState<RequestStep>("service");
  const [form, setForm] = useState<Form>(EMPTY_REQUEST);
  const [errors, setErrors] = useState<ServiceRequestErrors>({});
  // Focus moves to the step's heading when the step changes (not on the first render).
  const moved = useRef(false);
  useEffect(() => {
    if (!moved.current) return;
    headingRef.current?.focus();
  }, [step]);

  const send = useMutation({
    mutationFn: async (body: ServiceRequestBody) => {
      const { data, error, response } = await browserApi.POST("/api/v1/services/{slug}/requests", { params: { path: { slug: service.slug } }, body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: () => {
      setErrors({});
      go("done");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        const found = serviceRequestServerErrors(error.details);
        setErrors(found);
        const back = firstErrorStep(found);
        if (back) go(back, true);
      }
    },
  });

  function go(next: RequestStep, showErrors = false) {
    moved.current = true;
    setStep(next);
    if (showErrors) focusFirstError();
  }
  function focusFirstError() {
    requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>("[aria-invalid=true]")?.focus());
  }
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));

  /** Continue: the step's own fields must be right; later steps' are not checked yet. */
  function onContinue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step === "review") return submit();
    const mistakes = stepErrors(validateServiceRequest(form, locale).errors, step);
    setErrors(mistakes);
    if (Object.keys(mistakes).length) return focusFirstError();
    send.reset();
    go(FORM_STEPS[FORM_STEPS.indexOf(step as (typeof FORM_STEPS)[number]) + 1] ?? "review");
  }

  function submit() {
    send.reset();
    const result = validateServiceRequest(form, locale);
    setErrors(result.errors);
    if (!result.body) {
      const back = firstErrorStep(result.errors);
      if (back) go(back, true);
      return;
    }
    send.mutate(result.body);
  }

  function back() {
    send.reset();
    setErrors({});
    const index = FORM_STEPS.indexOf(step as (typeof FORM_STEPS)[number]);
    if (index > 0) go(FORM_STEPS[index - 1]!);
  }

  const failure = send.error && !(send.error instanceof ApiError && send.error.status === 422) ? send.error : null;
  const limited = failure instanceof ApiError && failure.status === 429;

  return (
    <div className="flex flex-col gap-6">
      <WizardProgress step={step} />
      {step === "done" && send.data ? (
        <Confirmation service={service} reference={send.data.reference} headingRef={headingRef} />
      ) : (
        <form
          ref={formRef}
          onSubmit={onContinue}
          noValidate
          aria-labelledby="wizard-step-title"
          className="relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-bd bg-white shadow-sh"
        >
          <div className="flex flex-col gap-1 border-b border-bd px-8 pt-7 pb-6 max-sm:px-5 max-sm:pt-5">
            <h2 id="wizard-step-title" ref={headingRef} tabIndex={-1} className="t-h2 outline-none">
              {tw(`${step as Exclude<RequestStep, "done">}Title`)}
            </h2>
            <p className="m-0 text-tx2">
              {tw(`${step as Exclude<RequestStep, "done">}Text`, {
                service: service.name,
              })}
            </p>
          </div>
          <div className="flex flex-col gap-4 px-8 py-6 max-sm:px-5">
            {step === "service" && <ServiceStep service={service} />}
            {step === "date" && <DateStep form={form} errors={errors} set={set} />}
            {step === "details" && <DetailsStep form={form} errors={errors} set={set} />}
            {step === "review" && <ReviewStep service={service} form={form} edit={(s) => go(s)} />}
            {/* The honeypot: hidden from people and screen readers; a bot that fills it is dropped.
             * It stays in the form on every step so its value is kept. */}
            <div aria-hidden="true" className="absolute -left-[9999px] h-px w-px overflow-hidden">
              <label>
                Website
                <input type="text" name="website" tabIndex={-1} autoComplete="off" value={form.website} onChange={(e) => set("website", e.target.value)} />
              </label>
            </div>
            {failure && (
              <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
                <CircleAlert size={18} aria-hidden="true" className="flex-none" />
                {t(limited ? "limited" : "failed")}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bd bg-page px-8 py-4 max-sm:px-5">
            {step === "service" ? (
              <Link href={`/services/${service.slug}`} className={buttonClasses({ variant: "outline", size: "lg" })}>
                <ArrowLeft size={18} aria-hidden="true" />
                {tw("back")}
              </Link>
            ) : (
              <Button type="button" variant="outline" size="lg" onClick={back} disabled={send.isPending}>
                <ArrowLeft size={18} aria-hidden="true" />
                {tw("back")}
              </Button>
            )}
            {step === "review" ? (
              <Button type="submit" size="lg" disabled={send.isPending}>
                <Send size={18} aria-hidden="true" />
                {t("send")}
              </Button>
            ) : (
              <Button type="submit" size="lg">
                {tw("continue")}
                <ArrowRight size={18} aria-hidden="true" />
              </Button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

/** The steps across the top: done ones ticked, the current one blue (as the checkout's steps).
 * Phones get "Step n of 5" and a progress bar. */
function WizardProgress({ step }: { step: RequestStep }) {
  const tw = useTranslations("store.services.wizard");
  const index = REQUEST_STEPS.indexOf(step);
  const total = REQUEST_STEPS.length;
  return (
    <nav aria-label={tw("stepsLabel")}>
      <div className="sm:hidden">
        <div className="mb-1.5 flex items-center justify-between text-cap font-medium">
          <span className="text-tx2">{tw("stepOf", { n: index + 1, total })}</span>
          <span>{tw(`steps.${step}`)}</span>
        </div>
        <div
          role="progressbar"
          aria-label={tw("stepsLabel")}
          aria-valuemin={1}
          aria-valuemax={total}
          aria-valuenow={index + 1}
          className="h-1.5 overflow-hidden rounded bg-bd"
        >
          <span className="block h-full rounded bg-pri transition-[width] duration-300 ease-soft" style={{ width: `${((index + 1) / total) * 100}%` }} />
        </div>
      </div>
      <ol className="m-0 hidden list-none items-center gap-3 p-0 sm:flex">
        {REQUEST_STEPS.map((s, i) => {
          const done = i < index;
          const now = i === index;
          return (
            <Fragment key={s}>
              <li className="flex flex-none items-center gap-2" aria-current={now ? "step" : undefined}>
                <span
                  aria-hidden="true"
                  className={cx(
                    "inline-flex size-8 flex-none items-center justify-center rounded-full text-[13px] font-semibold transition-colors duration-200",
                    done && "bg-ok-tx text-white",
                    now && "bg-pri text-white",
                    !done && !now && "border border-bd2 bg-white text-tx2",
                  )}
                >
                  {done ? <Check size={16} /> : i + 1}
                </span>
                <span className={cx("text-sm", now ? "font-semibold text-navy" : done ? "font-medium text-tx" : "text-tx2")}>
                  {tw(`steps.${s}`)}
                  {done && <span className="sr-only"> {tw("completed")}</span>}
                </span>
              </li>
              {i < total - 1 && <li aria-hidden="true" className={cx("h-px min-w-4 flex-1", done ? "bg-ok-tx" : "bg-bd")} />}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}

function ServiceStep({ service }: { service: WizardService }) {
  const t = useTranslations("store.services");
  const tw = useTranslations("store.services.wizard");
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-5 rounded-xl border border-bd bg-page p-4">
        <ServiceImage image={service.image} icon={service.icon} sizes="160px" iconSize={36} className="aspect-[4/3] w-36 flex-none rounded-lg max-sm:w-full" />
        <div className="flex min-w-0 flex-[1_1_240px] flex-col gap-1.5">
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="flex size-8 items-center justify-center rounded-lg bg-light text-pri">
              <ServiceIcon icon={service.icon} size={16} />
            </span>
            <b className="t-h4 text-navy">{service.name}</b>
          </span>
          <p className="m-0 text-sm text-tx2">{service.short_description}</p>
        </div>
      </div>
      {service.items.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <span className="t-over text-tx2">{t("offerTitle")}</span>
          <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2">
            {service.items.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <CircleCheck size={18} aria-hidden="true" className="mt-px flex-none text-ok" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Link href="/services" className="self-start text-sm font-semibold text-pri-h hover:text-pri">
        {tw("changeService")}
      </Link>
    </div>
  );
}

type StepProps = {
  form: Form;
  errors: ServiceRequestErrors;
  set: <K extends keyof Form>(key: K, value: Form[K]) => void;
};

function useErrorMessage() {
  const t = useTranslations("store.services");
  return (key: string | undefined) => (key ? t(`errors.${key}` as "errors.required") : undefined);
}

function DateStep({ form, errors, set }: StepProps) {
  const t = useTranslations("store.services");
  const tw = useTranslations("store.services.wizard");
  const message = useErrorMessage();
  const today = useToday();
  return (
    <div className="flex flex-col gap-4">
      <Field label={t("preferredDate")} help={t("optional")} error={message(errors.preferredDate)} className="sm:max-w-xs">
        {(p) => (
          <Input
            {...p}
            type="date"
            value={form.preferredDate}
            min={today ?? undefined}
            max={today ? kigaliDay(new Date(`${today}T12:00:00+02:00`), REQUEST_LIMITS.dateDays) : undefined}
            onChange={(e) => set("preferredDate", e.target.value)}
          />
        )}
      </Field>
      <p className="m-0 flex items-start gap-2.5 rounded-xl bg-light px-4 py-3 text-sm text-navy">
        <CalendarDays size={18} aria-hidden="true" className="mt-px flex-none text-pri-h" />
        {tw("timeNote")}
      </p>
    </div>
  );
}

function DetailsStep({ form, errors, set }: StepProps) {
  const t = useTranslations("store.services");
  const message = useErrorMessage();
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("fullName")} error={message(errors.fullName)}>
          {(p) => (
            <Input
              {...p}
              value={form.fullName}
              onChange={(e) => set("fullName", e.target.value)}
              maxLength={REQUEST_LIMITS.name}
              autoComplete="name"
              placeholder={t("fullNamePlaceholder")}
            />
          )}
        </Field>
        <Field label={t("phone")} error={message(errors.phone)}>
          {(p) => <PhoneInput {...p} value={form.phone} onChange={(e) => set("phone", e.target.value)} maxLength={16} placeholder={t("phonePlaceholder")} />}
        </Field>
        <Field label={t("email")} help={t("optional")} error={message(errors.email)}>
          {(p) => (
            <Input
              {...p}
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              maxLength={REQUEST_LIMITS.email}
              autoComplete="email"
              placeholder={t("emailPlaceholder")}
            />
          )}
        </Field>
        <Field label={t("location")} help={t("optional")} error={message(errors.location)}>
          {(p) => (
            <Input
              {...p}
              value={form.location}
              onChange={(e) => set("location", e.target.value)}
              maxLength={REQUEST_LIMITS.location}
              placeholder={t("locationPlaceholder")}
            />
          )}
        </Field>
      </div>
      <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
        <legend className="mb-2 text-sm font-medium text-tx">{t("clientType")}</legend>
        <div className="grid gap-2.5 sm:grid-cols-3">
          {CLIENT_TYPES.map((type) => (
            <RadioOption
              key={type}
              name="client_type"
              value={type}
              checked={form.clientType === type}
              onChange={() => set("clientType", type)}
              aria-invalid={errors.clientType ? true : undefined}
              label={<span className="text-sm font-medium">{t(`clientTypes.${type}`)}</span>}
            />
          ))}
        </div>
        {errors.clientType && (
          <span role="alert" className="text-cap text-err">
            {message(errors.clientType)}
          </span>
        )}
      </fieldset>
      <Field label={t("message")} help={t("optional")} error={message(errors.message)}>
        {(p) => (
          <Textarea
            {...p}
            value={form.message}
            onChange={(e) => set("message", e.target.value)}
            maxLength={REQUEST_LIMITS.message}
            placeholder={t("messagePlaceholder")}
          />
        )}
      </Field>
    </div>
  );
}

function ReviewStep({ service, form, edit }: { service: WizardService; form: Form; edit: (step: RequestStep) => void }) {
  const t = useTranslations("store.services");
  const tw = useTranslations("store.services.wizard");
  const format = useFormatter();
  const none = <span className="text-tx2">{tw("notGiven")}</span>;
  const date = form.preferredDate
    ? format.dateTime(new Date(`${form.preferredDate}T12:00:00+02:00`), {
        dateStyle: "full",
        timeZone: "Africa/Kigali",
      })
    : null;
  return (
    <div className="flex flex-col gap-4">
      <ReviewSection title={tw("steps.service")} onEdit={() => edit("service")}>
        <Row label={tw("steps.service")}>{service.name}</Row>
      </ReviewSection>
      <ReviewSection title={tw("steps.date")} onEdit={() => edit("date")}>
        <Row label={t("preferredDate")}>{date ?? tw("noDate")}</Row>
      </ReviewSection>
      <ReviewSection title={tw("steps.details")} onEdit={() => edit("details")}>
        <Row label={t("fullName")}>{form.fullName.trim()}</Row>
        <Row label={t("phone")}>{shownPhone(form.phone)}</Row>
        <Row label={t("email")}>{form.email.trim() || none}</Row>
        <Row label={t("location")}>{form.location.trim() || none}</Row>
        <Row label={t("clientType")}>{form.clientType ? t(`clientTypes.${form.clientType}`) : none}</Row>
        <Row label={t("message")}>{form.message.trim() ? <span className="whitespace-pre-line">{form.message.trim()}</span> : none}</Row>
      </ReviewSection>
      <p className="m-0 text-sm text-tx2">{t("replyTime")}</p>
    </div>
  );
}

function ReviewSection({ title, onEdit, children }: { title: string; onEdit: () => void; children: ReactNode }) {
  const tw = useTranslations("store.services.wizard");
  return (
    <section className="rounded-xl border border-bd">
      <div className="flex items-center justify-between gap-3 border-b border-bd bg-page px-4 py-2.5">
        <h3 className="m-0 text-sm font-semibold text-navy">{title}</h3>
        <button
          type="button"
          onClick={onEdit}
          className="flex cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-sm font-semibold text-pri-h hover:text-pri"
        >
          <Pencil size={14} aria-hidden="true" />
          {tw("edit")}
          <span className="sr-only"> {title}</span>
        </button>
      </div>
      <dl className="m-0 flex flex-col gap-2.5 px-4 py-3">{children}</dl>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[180px_1fr] sm:gap-4">
      <dt className="text-sm text-tx2">{label}</dt>
      <dd className="m-0 text-sm font-medium break-words text-tx">{children}</dd>
    </div>
  );
}

/** Step 5: the request was received. Its reference, its status (every new request starts as
 * "new" for staff, shown here as received), what happens next, and WhatsApp for urgent cases. */
function Confirmation({ service, reference, headingRef }: { service: WizardService; reference: string; headingRef: React.RefObject<HTMLHeadingElement | null> }) {
  const t = useTranslations("store.services");
  const tw = useTranslations("store.services.wizard");
  const tl = useTranslations("store.contactLinks");
  const { contact } = useStoreContact();
  return (
    <section
      role="status"
      aria-labelledby="wizard-done-title"
      className="flex flex-col items-center gap-5 rounded-xl border border-bd bg-white px-6 py-10 text-center shadow-sh sm:px-12"
    >
      <span aria-hidden="true" className="flex size-16 items-center justify-center rounded-full bg-ok-bg text-ok-tx motion-safe:animate-hero-pop">
        <CircleCheck size={34} />
      </span>
      <h2 id="wizard-done-title" ref={headingRef} tabIndex={-1} className="t-h2 outline-none">
        {tw("doneTitle")}
      </h2>
      <p className="m-0 max-w-lg text-tx2">{t("sent")}</p>
      <dl className="m-0 grid w-full max-w-md gap-3 rounded-xl bg-page p-4 text-left sm:grid-cols-2">
        <div className="flex flex-col gap-0.5">
          <dt className="text-cap text-tx2">{tw("referenceLabel")}</dt>
          <dd className="m-0 font-mono text-base font-semibold text-navy">{reference}</dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-cap text-tx2">{tw("statusLabel")}</dt>
          <dd className="m-0">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-light px-2.5 py-0.5 text-sm font-semibold text-pri-h">
              <span aria-hidden="true" className="size-1.5 rounded-full bg-pri" />
              {tw("statusReceived")}
            </span>
          </dd>
        </div>
        <div className="flex flex-col gap-0.5 sm:col-span-2">
          <dt className="text-cap text-tx2">{tw("steps.service")}</dt>
          <dd className="m-0 text-sm font-medium text-tx">{service.name}</dd>
        </div>
      </dl>
      <div className="flex flex-wrap justify-center gap-3">
        {contact?.whatsapp && (
          <a
            href={whatsappHref(contact.whatsapp, t("whatsappMessage", { reference, service: service.name }))}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonClasses({ variant: "outline", size: "lg" })}
          >
            {tw("whatsappUrgent")}
            <span className="sr-only"> {tl("newTab")}</span>
          </a>
        )}
        <Link href="/services" className={buttonClasses({ size: "lg" })}>
          {tw("moreServices")}
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}
