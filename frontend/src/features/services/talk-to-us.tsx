import { Phone } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { buttonClasses } from "@/components/ui/button";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";
import { getStoreContact } from "@/lib/api/catalogue";
import { telHref, whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";

/** The store's Call and WhatsApp buttons (GET /settings), each left out while unset. `message`
 * prefills the WhatsApp chat. Renders nothing when the store has neither. */
export async function ServiceContactButtons({ message, tone = "light", className }: { message: string; tone?: "light" | "dark"; className?: string }) {
  const t = await getTranslations("store.services");
  const tl = await getTranslations("store.contactLinks");
  const contact = await getStoreContact().catch(() => null);
  if (!contact?.phone && !contact?.whatsapp) return null;
  return (
    <div className={cx("flex flex-wrap gap-3", className)}>
      {contact.phone && (
        <a
          href={telHref(contact.phone)}
          className={buttonClasses({
            variant: tone === "dark" ? "white" : "outline",
            size: "lg",
          })}
        >
          <Phone size={18} aria-hidden="true" />
          {t("call")}
        </a>
      )}
      {contact.whatsapp && (
        <a href={whatsappHref(contact.whatsapp, message)} target="_blank" rel="noopener noreferrer" className={buttonClasses({ variant: "whatsapp", size: "lg" })}>
          <WhatsAppIcon size={18} aria-hidden="true" />
          {t("whatsapp")}
          <span className="sr-only"> {tl("newTab")}</span>
        </a>
      )}
    </div>
  );
}
