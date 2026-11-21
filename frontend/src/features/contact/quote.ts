import type { components } from "@/lib/api/schema";
import { localPhone } from "@/lib/checkout";

/** The Contact page's business quote request (POST /quote-requests, module 19): the same rules
 * as the backend, so mistakes show next to their field before anything is sent. */

export type QuoteBody = components["schemas"]["QuoteRequestCreate"];
export type QuoteLineInput = { product: string; quantity: string };
export type QuoteForm = {
  company: string;
  contactName: string;
  phone: string;
  email: string;
  lines: QuoteLineInput[];
  deliveryLocation: string;
  neededBy: string;
  message: string;
};
/** Error keys (store.contact.errors.*) by field; line errors by row index. */
export type QuoteErrors = Partial<Record<"company" | "contactName" | "phone" | "email" | "lines" | "neededBy" | "message", string>> & {
  rows?: Record<number, { product?: string; quantity?: string }>;
};

export const QUOTE_LIMITS = {
  company: 150,
  contactName: 120,
  email: 254,
  product: 200,
  quantity: 100_000,
  lines: 20,
  location: 120,
  message: 2000,
  neededByDays: 366,
} as const;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const emptyLine = (): QuoteLineInput => ({ product: "", quantity: "" });

/** Today in Kigali as YYYY-MM-DD (the backend checks needed-by dates in Kigali time). */
export function kigaliDay(now = new Date(), addDays = 0): string {
  const day = new Date(now.getTime() + addDays * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Kigali", year: "numeric", month: "2-digit", day: "2-digit" }).format(day);
}

/** `rowIndex[i]` is the form row of the body's line i (empty rows are not sent). */
/** One product and its quantity: the line to send, or the error keys of its two fields (the
 * quote form's "Add a product" popup checks each one before it joins the list). */
export function validateLine(input: QuoteLineInput): { line: QuoteBody["lines"][number] | null; errors: { product?: string; quantity?: string } } {
  const product = input.product.trim();
  const quantityText = input.quantity.trim();
  const quantity = /^\d+$/.test(quantityText) ? Number(quantityText) : NaN;
  const errors: { product?: string; quantity?: string } = {};
  if (!product) errors.product = "productRequired";
  else if (product.length > QUOTE_LIMITS.product) errors.product = "tooLong";
  if (!quantityText) errors.quantity = "quantityRequired";
  else if (!Number.isInteger(quantity) || quantity < 1 || quantity > QUOTE_LIMITS.quantity) errors.quantity = "quantityInvalid";
  return { line: errors.product || errors.quantity ? null : { product, quantity }, errors };
}

export function validateQuote(
  form: QuoteForm,
  locale: "en" | "rw",
  now = new Date(),
): { errors: QuoteErrors; body: QuoteBody | null; rowIndex: number[] } {
  const errors: QuoteErrors = {};
  const company = form.company.trim();
  const contact = form.contactName.trim();
  if (company.length < 2) errors.company = company ? "tooShort" : "required";
  else if (company.length > QUOTE_LIMITS.company) errors.company = "tooLong";
  if (contact.length < 2) errors.contactName = contact ? "tooShort" : "required";
  else if (contact.length > QUOTE_LIMITS.contactName) errors.contactName = "tooLong";
  const local = localPhone(form.phone);
  if (!local) errors.phone = form.phone.trim() ? "phoneInvalid" : "required";
  const email = form.email.trim();
  if (email && (!EMAIL.test(email) || email.length > QUOTE_LIMITS.email)) errors.email = "emailInvalid";

  const lines: QuoteBody["lines"] = [];
  const rowIndex: number[] = [];
  const rows: NonNullable<QuoteErrors["rows"]> = {};
  form.lines.forEach((input, index) => {
    if (!input.product.trim() && !input.quantity.trim()) return; // an empty row is ignored
    const { line, errors: row } = validateLine(input);
    if (!line) rows[index] = row;
    else {
      lines.push(line);
      rowIndex.push(index);
    }
  });
  if (Object.keys(rows).length) errors.rows = rows;
  else if (lines.length === 0) errors.lines = "linesRequired";

  if (form.neededBy && (form.neededBy < kigaliDay(now) || form.neededBy > kigaliDay(now, QUOTE_LIMITS.neededByDays))) errors.neededBy = "neededByInvalid";
  if (form.message.trim().length > QUOTE_LIMITS.message) errors.message = "tooLong";

  if (Object.keys(errors).length) return { errors, body: null, rowIndex };
  return {
    errors,
    rowIndex,
    body: {
      company,
      contact_name: contact,
      phone: `0${local}`,
      email: email || null,
      lines,
      delivery_location: form.deliveryLocation.trim() || null,
      needed_by: form.neededBy || null,
      message: form.message.trim() || null,
      locale,
    },
  };
}

/** The backend's 422 details mapped onto the form's fields (["body", "company"], ["body",
 * "lines", 0, "quantity"], …), for a rule the browser check missed. */
export function serverErrors(details: unknown, rowIndex: number[]): QuoteErrors {
  const errors: QuoteErrors = {};
  if (!Array.isArray(details)) return errors;
  const fields: Record<string, keyof Omit<QuoteErrors, "rows">> = {
    company: "company",
    contact_name: "contactName",
    phone: "phone",
    email: "email",
    lines: "lines",
    needed_by: "neededBy",
    message: "message",
  };
  for (const detail of details as { loc?: unknown[] }[]) {
    const [, field, index, part] = detail?.loc ?? [];
    if (field === "lines" && typeof index === "number" && (part === "product" || part === "quantity")) {
      const row = rowIndex[index] ?? index;
      errors.rows = { ...errors.rows, [row]: { ...errors.rows?.[row], [part]: part === "product" ? "productRequired" : "quantityInvalid" } };
    } else if (typeof field === "string" && fields[field]) {
      errors[fields[field]] = "invalid";
    }
  }
  return errors;
}
