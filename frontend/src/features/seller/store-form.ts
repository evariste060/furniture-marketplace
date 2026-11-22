import { localPhone } from "@/lib/checkout";
import { formatPhone } from "@/lib/format";

/** The store fields of the seller application (Account) and the store profile (seller dashboard),
 * with the backend's rules (app/schemas/stores.py) checked before sending. The backend checks
 * them again and decides what a phone number or email really is. */
export type StoreForm = {
  name: string;
  description: string;
  email: string;
  phone: string;
  district: string;
  sector: string;
  street: string;
};

export type StoreFormErrors = Partial<Record<keyof StoreForm, string>>;
export type StoreFormProblem = "name" | "email" | "phone" | "district";

export const STORE_NAME_MIN = 2;
export const STORE_NAME_MAX = 120;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type StoreFields = {
  name: string;
  description?: string | null;
  contact_email: string;
  contact_phone: string;
  district: string;
  sector?: string | null;
  street_address?: string | null;
};

export function storeForm(store: StoreFields | null): StoreForm {
  return {
    name: store?.name ?? "",
    description: store?.description ?? "",
    email: store?.contact_email ?? "",
    phone: store ? formatPhone(store.contact_phone) : "",
    district: store?.district ?? "",
    sector: store?.sector ?? "",
    street: store?.street_address ?? "",
  };
}

/** The fields that are wrong, each with the problem's message key. */
export function checkStoreForm(form: StoreForm): Partial<Record<keyof StoreForm, StoreFormProblem>> {
  const found: Partial<Record<keyof StoreForm, StoreFormProblem>> = {};
  const name = form.name.trim();
  if (name.length < STORE_NAME_MIN || name.length > STORE_NAME_MAX) found.name = "name";
  if (!EMAIL.test(form.email.trim())) found.email = "email";
  if (!localPhone(form.phone)) found.phone = "phone";
  if (form.district.trim().length < 2) found.district = "district";
  return found;
}

/** The application body (POST and PUT send every field). */
export function applicationBody(form: StoreForm) {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    contact_email: form.email.trim(),
    contact_phone: form.phone.trim(),
    district: form.district.trim(),
    sector: form.sector.trim() || null,
    street_address: form.street.trim() || null,
  };
}

/** Whether the application form is open: no application yet, or one that is pending or rejected.
 * Approved and suspended stores are managed from the seller dashboard (the backend answers 409
 * store_application_closed). */
export function canEditApplication(status: "pending" | "approved" | "rejected" | "suspended" | null): boolean {
  return status === null || status === "pending" || status === "rejected";
}
