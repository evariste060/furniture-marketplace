import type { components } from "@/lib/api/schema";

/** Checkout helpers shared by the checkout steps, the payment page and the confirmation page.
 * The browser only collects and checks what the customer types; the backend prices the order,
 * checks the address and the payment method again, and owns every amount (AGENTS.md). */

export type PaymentMethod = Exclude<components["schemas"]["PaymentStatusResponse"]["method"], "card">;
export const MOBILE_MONEY: readonly PaymentMethod[] = ["mtn_momo", "airtel_money"];
export const CHECKOUT_STEPS = ["contact", "delivery", "payment", "review"] as const;
export type CheckoutStep = (typeof CHECKOUT_STEPS)[number];

export function checkoutStep(value: string | string[] | undefined | null): CheckoutStep {
  const step = Array.isArray(value) ? value[0] : value;
  return CHECKOUT_STEPS.includes(step as CheckoutStep) ? (step as CheckoutStep) : "contact";
}

/** A Rwandan mobile number as typed ("788 123 456", "0788123456", "+250 788…") → its 9 local
 * digits ("788123456"), or null. The backend checks the operator prefixes again. */
export function localPhone(value: string): string | null {
  const digits = value.replace(/\D/g, "");
  const local = digits.startsWith("250") && digits.length === 12 ? digits.slice(3) : digits.replace(/^0(?=7)/, "");
  return /^7[2389]\d{7}$/.test(local) ? local : null;
}

export const NAME_MAX = 90;
export const EMAIL_MAX = 254;
export const STREET_MAX = 240;
export const TEXT_MAX = 120;
export const NOTE_MAX = 500;

export type ContactForm = { firstName: string; lastName: string; phone: string; email: string };
export type AddressForm = { district: string; sector: string; street: string; landmark: string; save: boolean };

export type ContactErrors = Partial<Record<keyof ContactForm, "required" | "invalid">>;
export type AddressErrors = Partial<Record<"district" | "street", "required" | "invalid">>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function checkContact(form: ContactForm): ContactErrors {
  const errors: ContactErrors = {};
  if (!form.firstName.trim()) errors.firstName = "required";
  if (!form.lastName.trim()) errors.lastName = "required";
  if (!form.phone.trim()) errors.phone = "required";
  else if (!localPhone(form.phone)) errors.phone = "invalid";
  if (form.email.trim() && !EMAIL.test(form.email.trim())) errors.email = "invalid";
  return errors;
}

export function checkAddress(form: AddressForm, districts: readonly string[]): AddressErrors {
  const errors: AddressErrors = {};
  if (!form.district) errors.district = "required";
  else if (!districts.includes(form.district)) errors.district = "invalid";
  if (!form.street.trim()) errors.street = "required";
  else if (form.street.trim().length < 3) errors.street = "invalid";
  return errors;
}

export function fullName(contact: Pick<ContactForm, "firstName" | "lastName">): string {
  return `${contact.firstName.trim()} ${contact.lastName.trim()}`.trim();
}

/** "Aline Mukamana" → first and last name for the contact form (the rest goes to the last). */
export function splitName(name: string | null | undefined): Pick<ContactForm, "firstName" | "lastName"> {
  const [first = "", ...rest] = (name ?? "").trim().split(/\s+/);
  return { firstName: first, lastName: rest.join(" ") };
}

type CheckoutAddress = components["schemas"]["CheckoutAddress"];

/** The address sent with the order: the contact person receives it at the chosen place. */
export function orderAddress(contact: ContactForm, address: AddressForm): CheckoutAddress {
  const optional = (value: string) => value.trim() || null;
  return {
    recipient_name: fullName(contact),
    phone: `0${localPhone(contact.phone) ?? ""}`,
    district: address.district,
    sector: optional(address.sector),
    street_address: address.street.trim(),
    delivery_instructions: optional(address.landmark),
  };
}

/** A placed order this tab may read: guests prove an order with its phone (the backend's
 * order lookup and payment endpoints, §7 Q17). Kept in sessionStorage, so it ends with the tab
 * and never reaches the server or another tab; the phone is the customer's own. */
export type OrderAccess = { number: string; phone: string; methods?: PaymentMethod[] };
const ACCESS_KEY = "sixty_orders";

function readAll(): OrderAccess[] {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(ACCESS_KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as OrderAccess[]).filter((a) => typeof a?.number === "string" && typeof a?.phone === "string") : [];
  } catch {
    return [];
  }
}

export function rememberOrder(access: OrderAccess): void {
  try {
    const others = readAll().filter((a) => a.number !== access.number);
    sessionStorage.setItem(ACCESS_KEY, JSON.stringify([access, ...others].slice(0, 5)));
  } catch {
    // Storage may be unavailable (private mode): the pages then ask for the phone.
  }
}

export function orderAccess(number: string): OrderAccess | null {
  return readAll().find((a) => a.number === number.toUpperCase()) ?? null;
}

/** "ORD-261027-ABC123" in a URL segment → upper case, or null if it is not an order number. */
export function orderNumber(value: string): string | null {
  const number = decodeURIComponent(value).trim().toUpperCase();
  return /^[A-Z0-9-]{6,40}$/.test(number) ? number : null;
}

/** Seconds until an ISO time, never below zero. */
export function secondsLeft(until: string | null | undefined, now: number): number {
  if (!until) return 0;
  return Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000));
}

/** 272 → "04:32". */
export function countdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}
