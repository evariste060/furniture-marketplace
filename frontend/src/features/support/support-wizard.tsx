"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, CircleAlert, CircleHelp, Copy, CreditCard, MessageSquareText, Package, Pencil, RotateCcw, Send, ShieldCheck, Smartphone, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Field, Input, PhoneInput, Textarea } from "@/components/ui/form";
import { useProfile } from "@/features/checkout/use-checkout";
import { useSession } from "@/features/session/use-session";
import { getPathname, Link } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { localPhone } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { formatPhone } from "@/lib/format";
import {
  ORDER_TOPICS,
  serverErrors,
  stepOf,
  SUPPORT_LIMITS,
  SUPPORT_TOPICS,
  validateStep,
  validateSupport,
  WIZARD_STEPS,
  type SupportBody,
  type SupportErrors,
  type SupportForm as Form,
  type SupportTopic,
  type WizardStep,
} from "./support";

const START: Form = { topic: "", name: "", phone: "", email: "", subject: "", orderNumber: "", body: "" };
const TOPIC_ICON: Record<SupportTopic, LucideIcon> = {
  order: Package,
  product: Smartphone,
  payment: CreditCard,
  warranty: ShieldCheck,
  returns: RotateCcw,
  other: CircleHelp,
};

/** The Contact page's support request (POST /support-messages), in four steps: what it is about,
 * the question, how to reach the sender, and a review before sending. Each step is checked before
 * the next one opens. A signed-in customer's details are filled in from their profile. Once sent,
 * the sender gets the reference and a link to the conversation: My messages for a customer, the
 * private link for a guest (also emailed with each reply). */
export function SupportWizard() {
  const t = useTranslations("store.support");
  const locale = useLocale() === "rw" ? "rw" : "en";
  const client = useQueryClient();
  const { data: user } = useSession();
  const customer = Boolean(user?.is_customer);
  const profile = useProfile(customer);
  const [form, setForm] = useState<Form>(START);
  const [touched, setTouched] = useState<Partial<Record<keyof Form, true>>>({});
  const [errors, setErrors] = useState<SupportErrors>({});
  const [step, setStep] = useState<WizardStep>("topic");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const index = WIZARD_STEPS.indexOf(step);

  // The profile fills each contact field the visitor has not typed in.
  const filled: Form = {
    ...form,
    name: touched.name ? form.name : form.name || profile.data?.full_name || "",
    email: touched.email ? form.email : form.email || profile.data?.email || "",
    phone: touched.phone ? form.phone : form.phone || (profile.data?.phone ? (localPhone(profile.data.phone) ?? "") : ""),
  };
  const asksOrder = filled.topic !== "" && ORDER_TOPICS.includes(filled.topic);

  const send = useMutation({
    mutationFn: async (body: SupportBody) => {
      const { data, error, response } = await browserApi.POST("/api/v1/support-messages", { body });
      if (!data) throw ApiError.from(response.status, error);
      return { ...data, emailed: Boolean(body.email) };
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["customer", "support"] }),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        const found = serverErrors(error.details);
        setErrors(found);
        go(stepOf(found) ?? "review");
      }
    },
  });

  // Each new step's heading takes focus, so keyboard and screen-reader users start at its top.
  useEffect(() => {
    if (moved.current) headingRef.current?.focus();
  }, [step, send.isSuccess]);

  function go(next: WizardStep) {
    moved.current = true;
    setStep(next);
  }
  const set = (key: keyof Form, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setTouched((f) => ({ ...f, [key]: true }));
    setErrors((e) => ({ ...e, [key]: undefined, ...(key === "phone" || key === "email" ? { contact: undefined } : {}) }));
  };
  const message = (key: string | undefined) => (key ? t(`errors.${key}` as "errors.required") : undefined);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step !== "review") {
      const found = validateStep(step, filled);
      setErrors(found);
      if (Object.keys(found).length) {
        const formEl = event.currentTarget;
        requestAnimationFrame(() => formEl.querySelector<HTMLElement>("[aria-invalid=true], input[name=topic]")?.focus());
        return;
      }
      return go(WIZARD_STEPS[index + 1]!);
    }
    send.reset();
    const result = validateSupport(filled, locale);
    setErrors(result.errors);
    if (!result.body) return go(stepOf(result.errors) ?? "topic");
    send.mutate(result.body);
  }

  function restart() {
    send.reset();
    setForm({ ...START, name: filled.name, phone: filled.phone, email: filled.email });
    setErrors({});
    go("topic");
  }

  if (send.isSuccess) {
    const { reference, access_key, emailed } = send.data;
    return <Sent reference={reference} href={customer ? `/account/messages/${reference}` : `/support/${reference}/${access_key}`} customer={customer} emailed={emailed} onAgain={restart} headingRef={headingRef} />;
  }

  const failure = send.error && !(send.error instanceof ApiError && send.error.status === 422) ? send.error : null;
  const limited = failure instanceof ApiError && failure.status === 429;
  const contactError = errors.contact && !errors.phone && !errors.email ? message(errors.contact) : undefined;
  return (
    <form onSubmit={onSubmit} noValidate aria-labelledby="support-title" className="flex min-w-0 flex-[999_1_560px] flex-col overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
      <div className="flex flex-col gap-5 border-b border-bd px-8 pt-7 pb-6 max-sm:px-5 max-sm:pt-5">
        <div className="flex items-start gap-4">
          <span aria-hidden="true" className="flex size-12 flex-none items-center justify-center rounded-xl bg-light text-pri max-sm:hidden">
            <MessageSquareText size={24} />
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id="support-title" className="t-h2">
              {t("title")}
            </h2>
            <p className="m-0 text-tx2">{t("text")}</p>
          </div>
        </div>
        <Stepper current={index} />
      </div>

      <div className="flex flex-col gap-5 px-8 py-7 max-sm:px-5 max-sm:py-5">
        <div className="flex flex-col gap-1">
          <p className="t-over m-0 text-tx2">{t("stepOf", { step: index + 1, total: WIZARD_STEPS.length })}</p>
          <h3 ref={headingRef} tabIndex={-1} className="t-h3 outline-none">
            {t(`steps.${step}.title`)}
          </h3>
          <p className="m-0 text-sm text-tx2">{t(`steps.${step}.text`)}</p>
        </div>

        {step === "topic" && (
          <fieldset aria-describedby={errors.topic ? "support-topic-error" : undefined} className="m-0 flex min-w-0 flex-col gap-2.5 border-0 p-0">
            <legend className="sr-only">{t("steps.topic.title")}</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {SUPPORT_TOPICS.map((topic) => {
                const Icon = TOPIC_ICON[topic];
                return (
                  <label
                    key={topic}
                    className={cx(
                      "flex cursor-pointer items-start gap-3.5 rounded-xl border bg-white p-4 transition-[border-color,background-color] duration-150 motion-reduce:transition-none",
                      "has-checked:border-pri has-checked:bg-light has-checked:ring-1 has-checked:ring-pri has-focus-visible:outline-2 has-focus-visible:outline-pri",
                      errors.topic ? "border-err" : "border-bd hover:border-bd2",
                    )}
                  >
                    <input type="radio" name="topic" value={topic} checked={form.topic === topic} onChange={() => set("topic", topic)} className="peer sr-only" />
                    <span aria-hidden="true" className="flex size-10 flex-none items-center justify-center rounded-[10px] bg-light text-pri peer-checked:bg-pri peer-checked:text-white">
                      <Icon size={20} />
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <b className="font-semibold text-tx">{t(`topics.${topic}.label`)}</b>
                      <span className="text-sm text-tx2">{t(`topics.${topic}.hint`)}</span>
                    </span>
                  </label>
                );
              })}
            </div>
            {errors.topic && (
              <span id="support-topic-error" role="alert" className="text-cap text-err">
                {message(errors.topic)}
              </span>
            )}
          </fieldset>
        )}

        {step === "details" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("subject")} error={message(errors.subject)} className={asksOrder ? undefined : "sm:col-span-2"}>
              {(p) => <Input {...p} value={form.subject} onChange={(e) => set("subject", e.target.value)} maxLength={SUPPORT_LIMITS.subject} placeholder={t(`subjectPlaceholders.${form.topic || "other"}`)} />}
            </Field>
            {asksOrder && (
              <Field label={t("orderNumber")} error={message(errors.orderNumber)} help={t("orderNumberHelp")}>
                {(p) => <Input {...p} value={form.orderNumber} onChange={(e) => set("orderNumber", e.target.value)} maxLength={SUPPORT_LIMITS.orderNumber} placeholder={t("orderNumberPlaceholder")} autoCapitalize="characters" />}
              </Field>
            )}
            <Field label={t("body")} error={message(errors.body)} help={t("bodyCount", { count: form.body.trim().length, max: SUPPORT_LIMITS.body })} className="sm:col-span-2">
              {(p) => <Textarea {...p} value={form.body} onChange={(e) => set("body", e.target.value)} maxLength={SUPPORT_LIMITS.body} placeholder={t("bodyPlaceholder")} className="min-h-[160px]" />}
            </Field>
          </div>
        )}

        {step === "contact" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("name")} error={message(errors.name)} className="sm:col-span-2">
              {(p) => <Input {...p} value={filled.name} onChange={(e) => set("name", e.target.value)} maxLength={SUPPORT_LIMITS.name} autoComplete="name" placeholder={t("namePlaceholder")} />}
            </Field>
            <Field label={t("email")} error={message(errors.email)} help={t("emailHelp")}>
              {(p) => <Input {...p} type="email" value={filled.email} onChange={(e) => set("email", e.target.value)} maxLength={SUPPORT_LIMITS.email} autoComplete="email" placeholder={t("emailPlaceholder")} />}
            </Field>
            <Field label={t("phone")} error={message(errors.phone) ?? contactError} help={t("contactHelp")}>
              {(p) => <PhoneInput {...p} aria-invalid={p["aria-invalid"] ?? (contactError ? true : undefined)} value={filled.phone} onChange={(e) => set("phone", e.target.value)} maxLength={16} placeholder={t("phonePlaceholder")} />}
            </Field>
          </div>
        )}

        {step === "review" && (
          <dl className="m-0 flex flex-col divide-y divide-bd rounded-xl border border-bd">
            <Review label={t("review.topic")} onEdit={() => go("topic")} edit={t("edit")}>
              {filled.topic && t(`topics.${filled.topic}.label`)}
            </Review>
            <Review label={t("review.question")} onEdit={() => go("details")} edit={t("edit")}>
              <span className="flex flex-col gap-1">
                <b className="font-semibold">{filled.subject.trim()}</b>
                {asksOrder && filled.orderNumber.trim() && <span className="text-sm text-tx2">{t("review.order", { number: filled.orderNumber.trim().toUpperCase() })}</span>}
                <span className="text-sm break-words whitespace-pre-line text-tx2">{filled.body.trim()}</span>
              </span>
            </Review>
            <Review label={t("review.contact")} onEdit={() => go("contact")} edit={t("edit")}>
              <span className="flex flex-col gap-0.5">
                <b className="font-semibold">{filled.name.trim()}</b>
                {filled.email.trim() && <span className="text-sm text-tx2">{filled.email.trim()}</span>}
                {filled.phone.trim() && <span className="text-sm text-tx2">{formatPhone(`+250${localPhone(filled.phone) ?? ""}`)}</span>}
              </span>
            </Review>
          </dl>
        )}

        {failure && (
          <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
            <CircleAlert size={18} aria-hidden="true" className="flex-none" />
            {t(limited ? "limited" : "failed")}
          </div>
        )}
      </div>

      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-bd bg-page px-8 py-4 max-sm:px-5">
        {index > 0 ? (
          <Button variant="outline" onClick={() => (setErrors({}), go(WIZARD_STEPS[index - 1]!))} className="gap-2">
            <ArrowLeft size={16} aria-hidden="true" />
            {t("back")}
          </Button>
        ) : (
          <span className="text-sm text-tx2">{t("replyTime")}</span>
        )}
        {step === "review" ? (
          <Button type="submit" disabled={send.isPending} className="gap-2">
            <Send size={16} aria-hidden="true" />
            {t("send")}
          </Button>
        ) : (
          <Button type="submit" className="gap-2">
            {t("continue")}
            <ArrowRight size={16} aria-hidden="true" />
          </Button>
        )}
      </div>
    </form>
  );
}

/** The four steps: done ones ticked, the current one in blue. Phones show the labels in the step
 * header only. */
function Stepper({ current }: { current: number }) {
  const t = useTranslations("store.support");
  return (
    <ol aria-label={t("progress")} className="m-0 flex list-none items-center gap-2 p-0">
      {WIZARD_STEPS.map((step, i) => {
        const done = i < current;
        const on = i === current;
        return (
          <li key={step} aria-current={on ? "step" : undefined} className="flex min-w-0 flex-1 items-center gap-2 last:flex-none">
            <span
              className={cx(
                "flex size-8 flex-none items-center justify-center rounded-full text-sm font-semibold",
                done ? "bg-ok-tx text-white" : on ? "bg-pri text-white" : "border border-bd2 bg-white text-tx2",
              )}
            >
              {done ? <Check size={16} aria-hidden="true" /> : i + 1}
              <span className="sr-only">
                {" "}
                {t(`steps.${step}.short`)}
                {done ? `, ${t("done")}` : ""}
              </span>
            </span>
            <span aria-hidden="true" className={cx("truncate text-sm font-medium max-md:hidden", on ? "text-tx" : "text-tx2")}>
              {t(`steps.${step}.short`)}
            </span>
            {i < WIZARD_STEPS.length - 1 && <span aria-hidden="true" className={cx("h-0.5 min-w-4 flex-1 rounded-full", done ? "bg-ok-tx" : "bg-bd")} />}
          </li>
        );
      })}
    </ol>
  );
}

function Review({ label, edit, onEdit, children }: { label: string; edit: string; onEdit: () => void; children: ReactNode }) {
  return (
    <div className="flex items-start gap-4 px-4 py-3.5">
      <dt className="w-28 flex-none text-sm font-medium text-tx2 max-sm:w-20">{label}</dt>
      <dd className="m-0 min-w-0 flex-1 text-tx">{children}</dd>
      <button type="button" onClick={onEdit} className="flex flex-none cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-sm font-medium text-pri-h hover:underline">
        <Pencil size={14} aria-hidden="true" />
        {edit}
        <span className="sr-only">: {label}</span>
      </button>
    </div>
  );
}

/** After sending: the reference and the way to follow the conversation. */
function Sent({
  reference,
  href,
  customer,
  emailed,
  onAgain,
  headingRef,
}: {
  reference: string;
  href: string;
  customer: boolean;
  emailed: boolean;
  onAgain: () => void;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
}) {
  const t = useTranslations("store.support");
  const locale = useLocale();
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(new URL(getPathname({ href, locale }), window.location.origin).toString());
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <section aria-labelledby="support-sent" className="flex min-w-0 flex-[999_1_560px] flex-col items-center gap-5 rounded-xl border border-bd bg-white px-8 py-12 shadow-sh text-center max-sm:px-5 max-sm:py-8">
      <span aria-hidden="true" className="flex size-16 items-center justify-center rounded-full bg-ok-bg text-ok-tx">
        <Check size={32} />
      </span>
      <div className="flex max-w-[480px] flex-col gap-2">
        <h2 id="support-sent" ref={headingRef} tabIndex={-1} className="t-h2 outline-none">
          {t("sentTitle")}
        </h2>
        <p className="m-0 text-tx2">{customer ? t("sentCustomer") : emailed ? t("sentGuestEmail") : t("sentGuestPhone")}</p>
      </div>
      <p className="m-0 flex items-center gap-2 rounded-lg bg-page px-4 py-2 text-sm">
        <span className="text-tx2">{t("referenceLabel")}</span>
        <b className="font-mono font-semibold">{reference}</b>
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link href={href} className={buttonClasses({ className: "gap-2" })}>
          <MessageSquareText size={16} aria-hidden="true" />
          {t("viewConversation")}
        </Link>
        {!customer && (
          <Button variant="outline" onClick={copy} className="gap-2">
            {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
            {copied ? t("copied") : t("copyLink")}
          </Button>
        )}
      </div>
      {!customer && <p className="m-0 max-w-[480px] text-cap text-tx2">{t("privateLinkNote")}</p>}
      <button type="button" onClick={onAgain} className="cursor-pointer border-0 bg-transparent p-0 text-sm font-medium text-pri-h hover:underline">
        {t("sendAnother")}
      </button>
    </section>
  );
}
