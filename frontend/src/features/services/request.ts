import type { components } from "@/lib/api/schema";
import { localPhone } from "@/lib/checkout";
import { kigaliDay } from "@/features/contact/quote";

/** "Request this service" (POST /services/{slug}/requests, ADR-013): the backend's rules, so
 * mistakes show next to their field before anything is sent. */

export type ServiceRequestBody = components["schemas"]["ServiceRequestCreate"];
export type ClientType = ServiceRequestBody["client_type"];
export const CLIENT_TYPES: ClientType[] = ["home", "business", "institution"];

export type ServiceRequestForm = {
  fullName: string;
  phone: string;
  email: string;
  location: string;
  clientType: ClientType | "";
  message: string;
  preferredDate: string;
  /** The hidden honeypot: people never see or fill it. */
  website: string;
};
type Field = "fullName" | "phone" | "email" | "location" | "clientType" | "message" | "preferredDate";
/** Error keys (store.services.errors.*) by field. */
export type ServiceRequestErrors = Partial<Record<Field, string>>;

export const REQUEST_LIMITS = {
  name: 120,
  email: 254,
  location: 120,
  message: 2000,
  dateDays: 366,
} as const;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const EMPTY_REQUEST: ServiceRequestForm = {
  fullName: "",
  phone: "",
  email: "",
  location: "",
  clientType: "",
  message: "",
  preferredDate: "",
  website: "",
};

export function validateServiceRequest(
  form: ServiceRequestForm,
  locale: "en" | "rw",
  now = new Date(),
): { errors: ServiceRequestErrors; body: ServiceRequestBody | null } {
  const errors: ServiceRequestErrors = {};
  const name = form.fullName.trim();
  if (name.length < 2) errors.fullName = name ? "tooShort" : "required";
  else if (name.length > REQUEST_LIMITS.name) errors.fullName = "tooLong";
  const local = localPhone(form.phone);
  if (!local) errors.phone = form.phone.trim() ? "phoneInvalid" : "required";
  const email = form.email.trim();
  if (email && (!EMAIL.test(email) || email.length > REQUEST_LIMITS.email)) errors.email = "emailInvalid";
  const location = form.location.trim();
  if (location.length > REQUEST_LIMITS.location) errors.location = "tooLong";
  if (!form.clientType) errors.clientType = "clientTypeRequired";
  const message = form.message.trim();
  if (message.length > REQUEST_LIMITS.message) errors.message = "tooLong";
  if (form.preferredDate && (form.preferredDate < kigaliDay(now) || form.preferredDate > kigaliDay(now, REQUEST_LIMITS.dateDays))) {
    errors.preferredDate = "dateInvalid";
  }
  if (Object.keys(errors).length || !form.clientType || !local) return { errors, body: null };
  return {
    errors,
    body: {
      full_name: name,
      phone: `0${local}`,
      email: email || null,
      location: location || null,
      client_type: form.clientType,
      message: message || null,
      preferred_date: form.preferredDate || null,
      locale,
      website: form.website || null,
    },
  };
}

/** The backend's 422 details (["body", "phone"], …) mapped onto the form's fields. */
export function serviceRequestServerErrors(details: unknown): ServiceRequestErrors {
  const errors: ServiceRequestErrors = {};
  if (!Array.isArray(details)) return errors;
  const fields: Record<string, Field> = {
    full_name: "fullName",
    phone: "phone",
    email: "email",
    location: "location",
    client_type: "clientType",
    message: "message",
    preferred_date: "preferredDate",
  };
  for (const detail of details as { loc?: unknown[] }[]) {
    const field = detail?.loc?.[1];
    if (typeof field === "string" && fields[field]) errors[fields[field]] = field === "preferred_date" ? "dateInvalid" : "invalid";
  }
  return errors;
}

/** The request wizard's steps (owner, 2026-11-17): the same fields, in order. */
export const REQUEST_STEPS = ["service", "date", "details", "review", "done"] as const;
export type RequestStep = (typeof REQUEST_STEPS)[number];

/** Which step asks for each field. */
const STEP_OF: Record<Field, RequestStep> = {
  preferredDate: "date",
  fullName: "details",
  phone: "details",
  email: "details",
  location: "details",
  clientType: "details",
  message: "details",
};

/** The errors of one step's fields (the whole form is checked by validateServiceRequest). */
export function stepErrors(errors: ServiceRequestErrors, step: RequestStep): ServiceRequestErrors {
  return Object.fromEntries(Object.entries(errors).filter(([field]) => STEP_OF[field as Field] === step));
}

/** The first step with a mistake, so the wizard can go back to it (e.g. after the server's 422). */
export function firstErrorStep(errors: ServiceRequestErrors): RequestStep | null {
  return REQUEST_STEPS.find((step) => Object.keys(stepErrors(errors, step)).length > 0) ?? null;
}
