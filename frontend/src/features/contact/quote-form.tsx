"use client";

import { useMutation } from "@tanstack/react-query";
import { Building2, CircleAlert, CircleCheck, Plus, Send, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRef, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import { Button, IconButton } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, PhoneInput, Textarea } from "@/components/ui/form";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import { emptyLine, kigaliDay, QUOTE_LIMITS, serverErrors, validateLine, validateQuote, type QuoteBody, type QuoteErrors, type QuoteForm as Form } from "./quote";
import { useStoreContact } from "./use-store-contact";

const noSubscribe = () => () => {};

/** Today in Kigali once in the browser; null while prerendering, as the date must not be baked
 * into the cached page. */
function useToday(): string | null {
  return useSyncExternalStore(noSubscribe, () => kigaliDay(), () => null);
}

const START: Form = { company: "", contactName: "", phone: "", email: "", lines: [], deliveryLocation: "", neededBy: "", message: "" };

/** Contact.dc.html: "Request a business quote" (POST /quote-requests, module 19). Products are
 * added one at a time in a popup (name and quantity, checked there) and listed with their
 * quantities, each with a remove button; up to 20. After sending, the form is cleared and the
 * thank-you note shows with the request's reference. */
export function QuoteForm() {
  const t = useTranslations("store.contact");
  const tl = useTranslations("store.contactLinks");
  const { contact } = useStoreContact();
  const locale = useLocale() === "rw" ? "rw" : "en";
  const formRef = useRef<HTMLFormElement>(null);
  const today = useToday();
  const [form, setForm] = useState<Form>(START);
  const [errors, setErrors] = useState<QuoteErrors>({});
  const [adding, setAdding] = useState(false);
  const rowIndex = useRef<number[]>([]);
  const send = useMutation({
    mutationFn: async (body: QuoteBody) => {
      const { data, error, response } = await browserApi.POST("/api/v1/quote-requests", { body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: () => {
      setForm(START);
      setErrors({});
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) {
        setErrors(serverErrors(error.details, rowIndex.current));
        focusFirstError();
      }
    },
  });

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));
  // A row's errors follow its index, so they are dropped when the list changes.
  const addLine = (line: { product: string; quantity: number }) => {
    setForm((f) => ({ ...f, lines: [...f.lines, { product: line.product, quantity: String(line.quantity) }] }));
    setErrors((e) => ({ ...e, rows: undefined, lines: undefined }));
  };
  const removeLine = (index: number) => {
    setForm((f) => ({ ...f, lines: f.lines.filter((_, i) => i !== index) }));
    setErrors((e) => ({ ...e, rows: undefined }));
  };
  const message = (key: string | undefined) => (key ? t(`errors.${key}` as "errors.required") : undefined);

  function focusFirstError() {
    // No product yet: the Add a product button is where to go next.
    requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>("[aria-invalid=true], [data-add-product]")?.focus());
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send.reset();
    const result = validateQuote(form, locale);
    setErrors(result.errors);
    rowIndex.current = result.rowIndex;
    if (!result.body) return focusFirstError();
    send.mutate(result.body);
  }

  const failure = send.error && !(send.error instanceof ApiError && send.error.status === 422) ? send.error : null;
  const limited = failure instanceof ApiError && failure.status === 429;
  return (
    <>
      <form ref={formRef} onSubmit={onSubmit} noValidate aria-labelledby="quote-title" className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <div className="flex items-start gap-4 border-b border-bd px-8 pt-7 pb-6 max-sm:px-5 max-sm:pt-5">
          <span aria-hidden="true" className="flex size-12 flex-none items-center justify-center rounded-xl bg-light text-pri max-sm:hidden">
            <Building2 size={24} />
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id="quote-title" className="t-h2">
              {t("quoteTitle")}
            </h2>
            <p className="m-0 text-tx2">{t("quoteText")}</p>
          </div>
        </div>
        <div className="flex flex-col divide-y divide-bd px-8 max-sm:px-5">
          <Section number={1} title={t("sectionDetails")} text={t("sectionDetailsText")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("company")} error={message(errors.company)}>
                {(p) => (
                  <Input {...p} value={form.company} onChange={(e) => set("company", e.target.value)} maxLength={QUOTE_LIMITS.company} autoComplete="organization" placeholder={t("companyPlaceholder")} />
                )}
              </Field>
              <Field label={t("contactName")} error={message(errors.contactName)}>
                {(p) => <Input {...p} value={form.contactName} onChange={(e) => set("contactName", e.target.value)} maxLength={QUOTE_LIMITS.contactName} autoComplete="name" placeholder={t("contactNamePlaceholder")} />}
              </Field>
              <Field label={t("phone")} error={message(errors.phone)}>
                {(p) => <PhoneInput {...p} value={form.phone} onChange={(e) => set("phone", e.target.value)} maxLength={16} placeholder={t("phonePlaceholder")} />}
              </Field>
              <Field label={t("email")} error={message(errors.email)}>
                {(p) => <Input {...p} type="email" value={form.email} onChange={(e) => set("email", e.target.value)} maxLength={QUOTE_LIMITS.email} autoComplete="email" placeholder={t("emailPlaceholder")} />}
              </Field>
            </div>
          </Section>
          <Section number={2} title={t("products")} text={t("sectionProductsText")}>
            <fieldset className="m-0 flex min-w-0 flex-col gap-2.5 border-0 p-0">
              <legend className="sr-only">{t("products")}</legend>
              {form.lines.length === 0 ? (
                <p className="rounded-lg border border-dashed border-bd2 px-4 py-3 text-sm text-tx2">{t("noProducts")}</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {form.lines.map((line, index) => {
                    const row = errors.rows?.[index];
                    return (
                      <li key={index} className="flex flex-col gap-1">
                        <div className={cx("flex items-center gap-3 rounded-lg border bg-white py-2 pr-2 pl-4", row ? "border-err" : "border-bd")}>
                          <span className="min-w-0 flex-1 truncate font-medium text-tx">{line.product}</span>
                          <span className="flex-none rounded-md bg-light px-2.5 py-1 text-sm font-semibold text-pri-h">{t("quantityValue", { quantity: line.quantity })}</span>
                          <IconButton aria-label={t("removeProduct", { product: line.product })} bordered={false} onClick={() => removeLine(index)} className="text-err! hover:bg-err-bg">
                            <Trash2 size={18} aria-hidden="true" />
                          </IconButton>
                        </div>
                        {row?.product && <span className="text-cap text-err">{message(row.product)}</span>}
                        {row?.quantity && <span className="text-cap text-err">{message(row.quantity)}</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
              {errors.lines && (
                <span role="alert" className="text-cap text-err">
                  {message(errors.lines)}
                </span>
              )}
              {form.lines.length < QUOTE_LIMITS.lines && (
                <Button data-add-product variant="outline" size="sm" className="self-start" onClick={() => setAdding(true)}>
                  <Plus size={16} aria-hidden="true" />
                  {t("addProduct")}
                </Button>
              )}
            </fieldset>
          </Section>
          <Section number={3} title={t("sectionDelivery")} text={t("sectionDeliveryText")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("location")}>
                {(p) => <Input {...p} value={form.deliveryLocation} onChange={(e) => set("deliveryLocation", e.target.value)} maxLength={QUOTE_LIMITS.location} placeholder={t("locationPlaceholder")} />}
              </Field>
              <Field label={t("neededBy")} error={message(errors.neededBy)}>
                {(p) => <Input {...p} type="date" value={form.neededBy} min={today ?? undefined} max={today ? kigaliDay(new Date(`${today}T12:00:00+02:00`), QUOTE_LIMITS.neededByDays) : undefined} onChange={(e) => set("neededBy", e.target.value)} />}
              </Field>
            </div>
            <Field label={t("message")} error={message(errors.message)}>
              {(p) => <Textarea {...p} value={form.message} onChange={(e) => set("message", e.target.value)} maxLength={QUOTE_LIMITS.message} placeholder={t("messagePlaceholder")} />}
            </Field>
          </Section>
        </div>
        <div className="flex flex-col px-8 max-sm:px-5">
          <div aria-live="polite" className="contents">
            {send.isSuccess && (
              <div role="status" className="mb-6 flex items-start gap-3 rounded-xl bg-ok-bg px-4 py-3.5 text-ok-tx">
                <CircleCheck size={20} aria-hidden="true" className="mt-px flex-none" />
                <span className="flex flex-col gap-1 text-sm">
                  <span>
                    {t("sent")}
                    {contact?.whatsapp &&
                      t.rich("urgent", {
                        link: (chunks) => (
                          <a
                            href={whatsappHref(contact.whatsapp!, t("whatsappMessage", { reference: send.data.reference }))}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-ok-tx underline hover:text-ok-tx"
                          >
                            {chunks}
                            <span className="sr-only"> {tl("newTab")}</span>
                          </a>
                        ),
                      })}
                  </span>
                  <span>{t("reference", { reference: send.data.reference })}</span>
                </span>
              </div>
            )}
          </div>
          {failure && (
            <div role="alert" className="mb-6 flex items-center gap-2.5 rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
              <CircleAlert size={18} aria-hidden="true" className="flex-none" />
              {t(limited ? "limited" : "failed")}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bd bg-page px-8 py-4 max-sm:px-5">
          <span className="text-sm text-tx2">{t("replyTime")}</span>
          <Button type="submit" size="lg" disabled={send.isPending}>
            <Send size={18} aria-hidden="true" />
            {t("send")}
          </Button>
        </div>
      </form>
      {/* Outside the quote form: a form inside a form is not allowed. */}
      <Dialog open={adding} onClose={() => setAdding(false)} title={t("addProduct")} closeLabel={t("close")}>
        {adding && (
          <ProductPopupForm
            onAdd={(line) => {
              addLine(line);
              setAdding(false);
            }}
            onCancel={() => setAdding(false)}
          />
        )}
      </Dialog>
    </>
  );
}

/** One numbered part of the form: its number, title and a line on what it asks for. */
function Section({ number, title, text, children }: { number: number; title: string; text: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 py-6">
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="flex size-7 flex-none items-center justify-center rounded-full bg-pri text-sm font-semibold text-white">
          {number}
        </span>
        <div className="flex min-w-0 flex-col">
          <h3 className="t-h4">{title}</h3>
          <p className="m-0 text-sm text-tx2">{text}</p>
        </div>
      </div>
      {children}
    </div>
  );
}

/** "Add a product": the product's name or model and its quantity, checked before it joins the
 * list. */
function ProductPopupForm({ onAdd, onCancel }: { onAdd: (line: { product: string; quantity: number }) => void; onCancel: () => void }) {
  const t = useTranslations("store.contact");
  const [draft, setDraft] = useState(emptyLine);
  const [errors, setErrors] = useState<{ product?: string; quantity?: string }>({});
  const message = (key: string | undefined) => (key ? t(`errors.${key}` as "errors.required") : undefined);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();
    const result = validateLine(draft);
    setErrors(result.errors);
    if (result.line) onAdd(result.line);
    else event.currentTarget.querySelector<HTMLElement>("[aria-invalid=true]")?.focus();
  }

  return (
    <form onSubmit={onSubmit} noValidate aria-label={t("addProduct")} className="flex flex-col gap-4">
      <Field label={t("productLabel")} error={message(errors.product)}>
        {(p) => <Input {...p} value={draft.product} onChange={(e) => setDraft((d) => ({ ...d, product: e.target.value }))} maxLength={QUOTE_LIMITS.product} placeholder={t("productPlaceholder")} />}
      </Field>
      <Field label={t("quantityLabel")} error={message(errors.quantity)}>
        {(p) => <Input {...p} value={draft.quantity} onChange={(e) => setDraft((d) => ({ ...d, quantity: e.target.value }))} inputMode="numeric" maxLength={6} placeholder={t("quantityPlaceholder")} className="max-w-40" />}
      </Field>
      <div className="flex justify-end gap-2.5 pt-1">
        <Button variant="neutral" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button type="submit">
          <Plus size={16} aria-hidden="true" />
          {t("addToList")}
        </Button>
      </div>
    </form>
  );
}
