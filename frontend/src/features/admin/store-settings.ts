import { SOCIAL_NETWORKS, socialLinkOk, type SocialNetwork } from "@/components/ui/social-icons";

/** The Store tab's contact, announcement and social media settings (module 19; social links owner
 * 2026-11-18), checked with the backend's rules (app/schemas/settings.py) before anything is sent. */

export const CONTACT_KEYS = {
  name: "store.name",
  phone: "contact.phone",
  whatsapp: "contact.whatsapp",
  email: "contact.email",
  address: "contact.address",
  hours: "contact.hours",
} as const;
export const ANNOUNCEMENT_KEYS = { enabled: "announcement.enabled", en: "announcement.text_en", rw: "announcement.text_rw" } as const;

export type ContactField = keyof typeof CONTACT_KEYS;
export type StoreTexts = Record<ContactField | "announceEn" | "announceRw", string>;
/** Error keys (admin.settings.errors.*, or "required") by field. */
export type StoreErrors = Partial<Record<keyof StoreTexts, string>>;

export const STORE_LIMITS = { name: [2, 80], address: [3, 200], hours: [3, 100], announce: [3, 120], email: 254 } as const;
const PHONE = /^\+[1-9]( ?[0-9]){7,14}$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f]/;

const FIELD_KEY: Record<keyof StoreTexts, string> = { ...CONTACT_KEYS, announceEn: ANNOUNCEMENT_KEYS.en, announceRw: ANNOUNCEMENT_KEYS.rw };

/** The settings key a field saves to, for mapping the backend's 422 details back. */
export function storeFieldOf(settingKey: string): keyof StoreTexts | undefined {
  return (Object.keys(FIELD_KEY) as (keyof StoreTexts)[]).find((f) => FIELD_KEY[f] === settingKey);
}

function lengthError(value: string, [min, max]: readonly [number, number]): string | undefined {
  if (value.length < min) return "tooShort";
  if (value.length > max) return "tooLong";
  return undefined;
}

/** The changed settings as a PATCH body, or the errors. A value once set can be changed but not
 * cleared (the API refuses null); the announcement can be switched on only with both texts. */
export function storeChanges(
  texts: StoreTexts,
  initial: StoreTexts,
  enabled: boolean,
  initialEnabled: boolean,
): { errors: StoreErrors; body: Record<string, string | boolean> } {
  const errors: StoreErrors = {};
  const body: Record<string, string | boolean> = {};
  for (const field of Object.keys(FIELD_KEY) as (keyof StoreTexts)[]) {
    const value = texts[field].trim();
    if (value === initial[field].trim()) continue;
    if (!value) {
      errors[field] = "required";
      continue;
    }
    let error: string | undefined;
    if (CONTROL.test(value)) error = "invalid";
    else if (field === "phone" || field === "whatsapp") error = PHONE.test(value) ? undefined : "phone";
    else if (field === "email") error = EMAIL.test(value) && value.length <= STORE_LIMITS.email ? undefined : "email";
    else if (field === "name") error = lengthError(value, STORE_LIMITS.name);
    else if (field === "address") error = lengthError(value, STORE_LIMITS.address);
    else if (field === "hours") error = lengthError(value, STORE_LIMITS.hours);
    else error = lengthError(value, STORE_LIMITS.announce);
    if (error) errors[field] = error;
    else body[FIELD_KEY[field]] = field === "email" ? value.toLowerCase() : value;
  }
  if (enabled) {
    if (!texts.announceEn.trim()) errors.announceEn = "announcement";
    if (!texts.announceRw.trim()) errors.announceRw = "announcement";
  }
  if (enabled !== initialEnabled) body[ANNOUNCEMENT_KEYS.enabled] = enabled;
  return { errors, body };
}

/** The store's social media links (owner, 2026-11-18), shown as icons in the store footer. */
export const SOCIAL_KEYS = Object.fromEntries(SOCIAL_NETWORKS.map((n) => [n, `social.${n}`])) as Record<SocialNetwork, string>;
export type SocialLinks = Record<SocialNetwork, string>;

/** The network a settings key belongs to, for mapping the backend's 422 details back. */
export function socialNetworkOf(settingKey: string): SocialNetwork | undefined {
  return SOCIAL_NETWORKS.find((n) => SOCIAL_KEYS[n] === settingKey);
}

/** The changed social links as PATCH entries, or the networks whose link is not a full https link
 * on that network's own site. Unlike the contact lines a link can be removed: an emptied field is
 * sent as "" and its icon leaves the footer. */
export function socialChanges(links: SocialLinks, initial: SocialLinks): { errors: SocialNetwork[]; body: Record<string, string> } {
  const errors: SocialNetwork[] = [];
  const body: Record<string, string> = {};
  for (const network of SOCIAL_NETWORKS) {
    const value = links[network].trim();
    if (value === initial[network].trim()) continue;
    if (value && !socialLinkOk(network, value)) errors.push(network);
    else body[SOCIAL_KEYS[network]] = value;
  }
  return { errors, body };
}
