"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { buttonClasses, type ButtonSize, type ButtonVariant } from "@/components/ui/button";
import { whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import { useStoreContact } from "./use-store-contact";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";

type Props = {
  label: string;
  /** Prefilled message, e.g. the product or order it is about. */
  message?: string;
  variant?: ButtonVariant | "link";
  size?: ButtonSize;
  block?: boolean;
  iconSize?: number;
  className?: string;
  /** Shown instead once it is known that the store has no WhatsApp number (or the request
   * failed); nothing is shown while loading. */
  fallback?: ReactNode;
};

/** A WhatsApp button (.btn-wa / .btn-oa) or plain link to the store's WhatsApp number. Renders
 * nothing until the number is known, and `fallback` (or nothing) when the store has none. Opens
 * in a new tab. */
export function WhatsAppLink({ label, message, variant = "whatsapp-outline", size = "md", block, iconSize = 18, className, fallback = null }: Props) {
  const t = useTranslations("store.contactLinks");
  const { contact, settled } = useStoreContact();
  if (!contact?.whatsapp) return settled ? fallback : null;
  return (
    <a
      href={whatsappHref(contact.whatsapp, message)}
      target="_blank"
      rel="noopener noreferrer"
      className={variant === "link" ? className : buttonClasses({ variant, size, block, className })}
    >
      {variant !== "link" && <WhatsAppIcon size={iconSize} aria-hidden="true" />}
      {label}
      <span className="sr-only"> {t("newTab")}</span>
    </a>
  );
}

/** The round WhatsApp button in the page corner (.fab, Main.dc.html, MobileHome.dc.html). Above
 * the phone tab bar on small screens. */
export function WhatsAppFab({ className }: { className?: string }) {
  const t = useTranslations("store.contactLinks");
  const { contact } = useStoreContact();
  if (!contact?.whatsapp) return null;
  return (
    <a
      href={whatsappHref(contact.whatsapp)}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={t("fab")}
      className={cx(
        "fixed right-4 bottom-[84px] z-30 flex size-14 items-center justify-center rounded-full bg-wa text-wa-ink shadow-[0_8px_24px_rgba(13,31,64,.2)] hover:text-wa-ink sm:right-8 sm:bottom-8",
        className,
      )}
    >
      <WhatsAppIcon size={28} aria-hidden="true" />
    </a>
  );
}
