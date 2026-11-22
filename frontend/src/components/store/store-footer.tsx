import { getLocale, getTranslations } from "next-intl/server";
import { MARKETPLACE_NAME } from "@/lib/marketplace";
import { Suspense } from "react";
import { SOCIAL_NAMES, SOCIAL_NETWORKS, SocialIcon, type SocialNetwork } from "@/components/ui/social-icons";
import { getCategories, getServices, getStoreContact } from "@/lib/api/catalogue";
import { Link } from "@/i18n/navigation";
import { topCategories } from "@/lib/catalogue";
import { INFO_PAGES } from "@/lib/info-pages";
import { Logo } from "./logo";

const LINK = "text-sm text-odm hover:text-white";
const HEADING = "t-h4 mb-1 text-sm text-white";
/** Each network's own colour behind its icon on hover (brand colours, like the payment badges). */
const SOCIAL_HOVER: Record<SocialNetwork, string> = {
  facebook: "hover:bg-[#1877F2] focus-visible:bg-[#1877F2]",
  instagram: "hover:bg-[#E4405F] focus-visible:bg-[#E4405F]",
  x: "hover:bg-black focus-visible:bg-black",
  youtube: "hover:bg-[#FF0000] focus-visible:bg-[#FF0000]",
  tiktok: "hover:bg-black focus-visible:bg-black",
  linkedin: "hover:bg-[#0A66C2] focus-visible:bg-[#0A66C2]",
};
/** The name in the copyright line until the store name setting is read. */
const STORE_NAME = MARKETPLACE_NAME;

/** Footer.dc.html, rearranged (owner, 2026-11-18): one row with the logo, tagline and social
 * icons, then Shop (the API's categories), Services (ADR-013), Customer Service and Company; "We
 * accept" on a second row; the contact lines are left out (the Contact page has them). The social
 * icons are the links set in Settings (GET /settings → social), each left out while unset. */
export async function StoreFooter() {
  const t = await getTranslations("store.footer");
  const th = await getTranslations("store");
  return (
    <footer className="bg-navy text-white">
      <div className="wrap grid grid-cols-2 gap-x-6 gap-y-10 pt-14 pb-10 sm:grid-cols-4 lg:grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))] lg:gap-x-8">
        <div className="col-span-2 flex max-w-[320px] flex-col gap-4 sm:col-span-4 lg:col-span-1">
          <div className="w-fit rounded-[10px] bg-white px-3 py-2">
            <Logo height={40} alt={th("logoAlt")} />
          </div>
          <p className="text-sm text-odm">{t("tagline")}</p>
          <Suspense fallback={null}>
            <SocialLinks />
          </Suspense>
        </div>
        <nav aria-label={t("shop")} className="flex flex-col gap-2.5">
          <h2 className={HEADING}>{t("shop")}</h2>
          <Suspense fallback={null}>
            <ShopLinks />
          </Suspense>
          <Link href="/deals" className={LINK}>
            {th("header.deals")}
          </Link>
        </nav>
        <nav aria-label={t("services")} className="flex flex-col gap-2.5">
          <h2 className={HEADING}>{t("services")}</h2>
          <Suspense fallback={null}>
            <ServiceLinks />
          </Suspense>
          <Link href="/services" className={LINK}>
            {t("allServices")}
          </Link>
        </nav>
        <nav aria-label={t("customerService")} className="flex flex-col gap-2.5">
          <h2 className={HEADING}>{t("customerService")}</h2>
          <Link href="/track" className={LINK}>
            {t("trackOrder")}
          </Link>
          <Link href={INFO_PAGES.delivery} className={LINK}>
            {t("delivery")}
          </Link>
          <Link href={INFO_PAGES.returns} className={LINK}>
            {t("returns")}
          </Link>
          <Link href={INFO_PAGES.warranty} className={LINK}>
            {t("warranty")}
          </Link>
          <Link href="/contact" className={LINK}>
            {t("contact")}
          </Link>
        </nav>
        <nav aria-label={t("company")} className="flex flex-col gap-2.5">
          <h2 className={HEADING}>{t("company")}</h2>
          <Link href={INFO_PAGES.about} className={LINK}>
            {t("about")}
          </Link>
          <Link href="/bulk-orders" className={LINK}>
            {t("business")}
          </Link>
          <Link href={INFO_PAGES.terms} className={LINK}>
            {t("terms")}
          </Link>
          <Link href={INFO_PAGES.privacy} className={LINK}>
            {t("privacy")}
          </Link>
        </nav>
      </div>
      {/* The second row: how customers can pay. */}
      <div className="border-t border-white/14">
        <div className="wrap flex flex-wrap items-center gap-x-4 gap-y-2.5 py-5">
          <h2 className="t-h4 m-0 text-sm text-white">{t("weAccept")}</h2>
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            <li className="rounded-sm bg-[#FFCC00] px-2 py-[3px] text-cap font-semibold text-tx">{t("momo")}</li>
            <li className="rounded-sm bg-[#E40000] px-2 py-[3px] text-cap font-semibold text-white">{t("airtel")}</li>
            {(["visa", "mastercard", "cod"] as const).map((key) => (
              <li key={key} className="rounded-sm bg-white/12 px-2 py-[3px] text-cap font-semibold text-white">
                {t(key)}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="border-t border-white/14">
        <div className="wrap flex flex-wrap justify-between gap-2 py-[18px] text-cap text-odm">
          <Suspense fallback={<span>{t("copyright", { year: 2026, name: STORE_NAME })}</span>}>
            <Copyright />
          </Suspense>
          <span>{t("languages")}</span>
        </div>
      </div>
    </footer>
  );
}

async function ShopLinks() {
  const categories = topCategories(await getCategories().catch(() => []));
  return categories.map((c) => (
    <Link key={c.id} href={`/category/${c.slug}`} className={LINK}>
      {c.name}
    </Link>
  ));
}

async function ServiceLinks() {
  const locale = (await getLocale()) === "rw" ? "rw" : "en";
  const services = await getServices(locale).catch(() => []);
  return services.map((s) => (
    <Link key={s.slug} href={`/services/${s.slug}`} className={LINK}>
      {s.name}
    </Link>
  ));
}

/** The store's social media icons, each opening its page in a new tab; nothing while none is set. */
async function SocialLinks() {
  const t = await getTranslations("store.footer");
  const contact = await getStoreContact().catch(() => null);
  const links = SOCIAL_NETWORKS.flatMap((network) => {
    const href = contact?.social?.[network];
    return href ? [{ network, href }] : [];
  });
  if (!links.length) return null;
  return (
    <div className="flex flex-col gap-2.5">
      <h2 className={HEADING}>{t("followUs")}</h2>
      <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
        {links.map(({ network, href }) => (
          <li key={network}>
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t("socialLink", { network: SOCIAL_NAMES[network] })}
              className={`flex size-10 items-center justify-center rounded-full bg-white/10 text-white transition-[background-color,translate] duration-200 hover:-translate-y-0.5 hover:text-white focus-visible:outline-white motion-reduce:transition-none ${SOCIAL_HOVER[network]}`}
            >
              <SocialIcon network={network} size={18} />
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

async function Copyright() {
  const t = await getTranslations("store.footer");
  const contact = await getStoreContact().catch(() => null);
  return <span>{t("copyright", { year: 2026, name: contact?.store_name ?? STORE_NAME })}</span>;
}
