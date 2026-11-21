/** Links for the store's contact details (module 19). Numbers come from GET /settings in
 * international form, e.g. "+250 788 123 456". */

/** wa.me wants the number in international form without "+"; `text` prefills the message. */
export function whatsappHref(number: string, text?: string): string {
  const base = `https://wa.me/${number.replace(/\D/g, "")}`;
  return text ? `${base}?text=${encodeURIComponent(text)}` : base;
}

/** tel: with the digits only, keeping the leading "+". */
export function telHref(number: string): string {
  return `tel:${number.trim().startsWith("+") ? "+" : ""}${number.replace(/\D/g, "")}`;
}
