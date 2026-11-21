import type { components } from "@/lib/api/schema";
import { localPhone } from "@/lib/checkout";

/** Customer support messages (POST /support-messages; My messages; the private link; the admin
 * inbox): the same rules as the backend, so mistakes show next to their field before anything is
 * sent. The Contact page asks in four steps: topic, the question, contact details, review. */

export type SupportBody = components["schemas"]["SupportMessageCreate"];
export type SupportStatus = components["schemas"]["SupportThreadSummary"]["status"];
export type SupportTopic = SupportBody["topic"];
export type SupportForm = { topic: SupportTopic | ""; name: string; phone: string; email: string; subject: string; orderNumber: string; body: string };
/** Error keys (store.support.errors.*) by field. */
export type SupportErrors = Partial<Record<keyof SupportForm | "contact", string>>;

export const SUPPORT_LIMITS = { name: 120, email: 254, subject: 120, orderNumber: 32, body: 2000 } as const;
export const SUPPORT_STATUSES = ["open", "answered", "closed"] as const satisfies readonly SupportStatus[];
export const SUPPORT_TONE = { open: "soft-warn", answered: "soft-ok", closed: "soft-neutral" } as const;
export const SUPPORT_TOPICS = ["order", "product", "payment", "warranty", "returns", "other"] as const satisfies readonly SupportTopic[];
/** Topics about something already bought: the wizard asks for the order number. */
export const ORDER_TOPICS: readonly SupportTopic[] = ["order", "payment", "warranty", "returns"];
export const WIZARD_STEPS = ["topic", "details", "contact", "review"] as const;
export type WizardStep = (typeof WIZARD_STEPS)[number];
/** The fields each step checks before moving on. */
const STEP_FIELDS: Record<WizardStep, (keyof SupportErrors)[]> = {
  topic: ["topic"],
  details: ["subject", "orderNumber", "body"],
  contact: ["name", "phone", "email", "contact"],
  review: [],
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** "M-261111-ABCDEF" from a URL segment, or null. */
export function supportReference(value: string): string | null {
  let text: string;
  try {
    text = decodeURIComponent(value).trim().toUpperCase();
  } catch {
    return null;
  }
  return /^M-\d{6}-[A-Z0-9]{6}$/.test(text) ? text : null;
}

/** A private-link key from a URL segment (32 base64url characters), or null (no decoding). */
export function supportKey(value: string): string | null {
  return /^[A-Za-z0-9_-]{32}$/.test(value) ? value : null;
}

/** A message body's own rule (the reply boxes use it too): 2 to 2,000 characters. */
export function bodyError(body: string): string | undefined {
  const text = body.trim();
  if (!text) return "required";
  if (text.length < 2) return "tooShort";
  if (text.length > SUPPORT_LIMITS.body) return "tooLong";
  return undefined;
}

function allErrors(form: SupportForm): SupportErrors {
  const errors: SupportErrors = {};
  const name = form.name.trim();
  const subject = form.subject.trim();
  const email = form.email.trim();
  const phoneText = form.phone.trim();
  if (!form.topic) errors.topic = "topicRequired";
  if (name.length < 2) errors.name = name ? "tooShort" : "required";
  else if (name.length > SUPPORT_LIMITS.name) errors.name = "tooLong";
  if (phoneText && !localPhone(phoneText)) errors.phone = "phoneInvalid";
  if (email && (!EMAIL.test(email) || email.length > SUPPORT_LIMITS.email)) errors.email = "emailInvalid";
  if (!phoneText && !email) errors.contact = "contactRequired";
  if (subject.length < 3) errors.subject = subject ? "tooShort" : "required";
  else if (subject.length > SUPPORT_LIMITS.subject) errors.subject = "tooLong";
  if (form.orderNumber.trim().length > SUPPORT_LIMITS.orderNumber) errors.orderNumber = "tooLong";
  const body = bodyError(form.body);
  if (body) errors.body = body;
  return errors;
}

/** The errors of one wizard step's fields (empty: the step may move on). */
export function validateStep(step: WizardStep, form: SupportForm): SupportErrors {
  const errors = allErrors(form);
  return Object.fromEntries(STEP_FIELDS[step].filter((f) => errors[f]).map((f) => [f, errors[f]]));
}

/** The first step with a mistake, for the review step (and server errors) to send the visitor back. */
export function stepOf(errors: SupportErrors): WizardStep | null {
  return WIZARD_STEPS.find((step) => STEP_FIELDS[step].some((f) => errors[f])) ?? null;
}

export function validateSupport(form: SupportForm, locale: "en" | "rw"): { errors: SupportErrors; body: SupportBody | null } {
  const errors = allErrors(form);
  if (Object.keys(errors).length || !form.topic) return { errors, body: null };
  const local = form.phone.trim() ? localPhone(form.phone) : null;
  return {
    errors,
    body: {
      topic: form.topic,
      name: form.name.trim(),
      phone: local ? `0${local}` : null,
      email: form.email.trim() || null,
      subject: form.subject.trim(),
      // Only the topics about an order send one.
      order_number: ORDER_TOPICS.includes(form.topic) ? form.orderNumber.trim() || null : null,
      body: form.body.trim(),
      locale,
    },
  };
}

/** The backend's 422 details mapped onto the form's fields, for a rule the browser check missed. */
export function serverErrors(details: unknown): SupportErrors {
  const errors: SupportErrors = {};
  if (!Array.isArray(details)) return errors;
  const fields: Record<string, keyof SupportErrors> = { topic: "topic", name: "name", phone: "phone", email: "email", subject: "subject", order_number: "orderNumber", body: "body" };
  for (const detail of details as { loc?: unknown[] }[]) {
    const [, field] = detail?.loc ?? [];
    if (typeof field === "string" && fields[field]) errors[fields[field]] = "invalid";
    else if (field === undefined) errors.contact = "contactRequired"; // the phone-or-email rule
  }
  return errors;
}
