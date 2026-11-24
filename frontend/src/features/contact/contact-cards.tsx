import { Mail, MapPin, Phone } from "lucide-react";
import { getTranslations } from "next-intl/server";
import type { ComponentType, ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";
import { getStoreContact } from "@/lib/api/catalogue";
import { telHref, whatsappHref } from "@/lib/contact";
import { cx } from "@/lib/cx";
import { SideCard } from "./side-card";

/** The store's WhatsApp, phone, email and address cards (GET /settings, module 19), each left out
 * while unset. Shared by the Contact and Business & bulk orders pages. */
/** The page puts the cards in its own side column; compact rows sit inside a side card. */
const COLUMN = "flex w-full flex-col gap-3.5";
const LIST = "-mx-2 flex flex-col";

/** With a card (id and title), the rows sit inside a titled side card, left out with them. */
export async function ContactCards({ card }: { card?: { id: string; title: string } }) {
  const compact = Boolean(card);
  const t = await getTranslations("store.contact");
  const tl = await getTranslations("store.contactLinks");
  const contact = await getStoreContact().catch(() => null);
  if (!contact) return null;
  const { whatsapp, phone, email, address, hours } = contact;
  if (!whatsapp && !phone && !email && !address) return null;
  const list = (
    <div className={compact ? LIST : COLUMN}>
      {whatsapp && (
        <Card compact={compact} href={whatsappHref(whatsapp)} external Icon={WhatsAppIcon} tone="wa" title={t("whatsapp")} newTab={tl("newTab")}>
          {t("whatsappLine", { number: whatsapp })}
        </Card>
      )}
      {phone && (
        <Card compact={compact} href={telHref(phone)} Icon={Phone} title={t("call")}>
          {hours ? `${phone} · ${hours}` : phone}
        </Card>
      )}
      {email && (
        <Card compact={compact} href={`mailto:${email}`} Icon={Mail} title={t("emailTitle")}>
          {email}
        </Card>
      )}
      {address && (
        <Card compact={compact} Icon={MapPin} title={t("visit")}>
          <span className="flex flex-col">
            <span>{address}</span>
            {hours && <span>{hours}</span>}
          </span>
        </Card>
      )}
    </div>
  );
  return card ? (
    <SideCard id={card.id} title={card.title}>
      {list}
    </SideCard>
  ) : (
    list
  );
}

function Card({
  compact,
  href,
  external,
  Icon,
  tone = "pri",
  title,
  newTab,
  children,
}: {
  compact: boolean;
  href?: string;
  external?: boolean;
  Icon: ComponentType<{ size?: number }>;
  tone?: "pri" | "wa";
  title: string;
  newTab?: string;
  children: ReactNode;
}) {
  const body = (
    <>
      <span aria-hidden="true" className={cx("flex size-11 flex-none items-center justify-center rounded-[10px]", tone === "wa" ? "bg-ok-bg text-ok-tx" : "bg-light text-pri-fg")}>
        <Icon size={22} />
      </span>
      <span className="flex min-w-0 flex-col">
        <b className="font-semibold">{title}</b>
        <span className="text-sm break-words text-tx2">{children}</span>
      </span>
      {external && newTab && <span className="sr-only">{newTab}</span>}
    </>
  );
  const box = compact ? "flex items-center gap-3.5 rounded-lg p-2 text-tx" : "flex items-center gap-3.5 rounded-xl border border-bd bg-card p-5 text-tx";
  if (!href) return <div className={box}>{body}</div>;
  return (
    <a href={href} className={cx(box, compact ? "hover:bg-page hover:text-tx" : "hover:border-pri hover:text-tx")} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
      {body}
    </a>
  );
}

export function CardsFallback({ compact = false }: { compact?: boolean }) {
  if (compact) return <Skeleton aria-busy="true" className="h-[300px] w-full rounded-xl" />;
  return (
    <div aria-busy="true" className={COLUMN}>
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-[86px] w-full rounded-xl" />
      ))}
    </div>
  );
}
