import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { RichText } from "@/components/store/rich-text";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { getPathname, Link } from "@/i18n/navigation";
import { getPage } from "@/lib/api/catalogue";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import { INFO_PAGES, infoPageKey, type InfoPageKey } from "@/lib/info-pages";

type Props = PageProps<"/[locale]/pages/[slug]">;
type Locale = "en" | "rw";
type Shown = { page: components["schemas"]["PublicPage"]; fallback: boolean; other: boolean };

/** The version to show: the reader's language, or English for a Kinyarwanda reader when the
 * page has no published Kinyarwanda text yet (Settings.dc.html: "RW missing" pages show English
 * to Kinyarwanda readers). `other` says whether the other language exists, for the switch link.
 * Null when neither version is published. */
async function shownPage(slug: string, locale: Locale): Promise<Shown | null> {
  const [en, rw] = await Promise.all([getPage(slug, "en"), getPage(slug, "rw")]);
  if (locale === "rw") {
    if (rw) return { page: rw, fallback: false, other: en !== null };
    return en ? { page: en, fallback: true, other: false } : null;
  }
  return en ? { page: en, fallback: false, other: rw !== null } : null;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  if (!infoPageKey(slug)) notFound();
  const locale = (await getLocale()) as Locale;
  const shown = await shownPage(slug, locale).catch(() => undefined);
  if (shown === null) notFound();
  return shown ? { title: shown.page.title } : {};
}

/** /pages/[slug]: Policy.dc.html. The text is the staff's Markdown (module 19). */
export default function PolicyPage({ params }: Props) {
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex flex-wrap items-start gap-8 pt-8 pb-16 max-sm:gap-4 max-sm:pt-4 max-sm:pb-10">
        <Suspense fallback={<NavFallback />}>
          <PolicyNav params={params} />
        </Suspense>
        <Suspense fallback={<ArticleFallback />}>
          <PolicyArticle params={params} />
        </Suspense>
      </div>
    </main>
  );
}

const ARTICLE = "flex min-w-0 flex-[999_1_560px] flex-col gap-5 rounded-xl border border-bd bg-white p-10 max-sm:p-5 lg:max-w-[860px]";

async function PolicyNav({ params }: Pick<Props, "params">) {
  const { slug } = await params;
  const t = await getTranslations("store.policy");
  const current = infoPageKey(slug);
  return (
    <nav aria-label={t("navLabel")} className="flex w-full flex-col gap-0.5 rounded-xl border border-bd bg-white p-4 sm:max-w-[260px] sm:flex-[1_1_240px]">
      <span className="t-over px-3 py-2 text-mut">{t("navTitle")}</span>
      {(Object.keys(INFO_PAGES) as InfoPageKey[]).map((key) => (
        <Link
          key={key}
          href={INFO_PAGES[key]}
          aria-current={key === current ? "page" : undefined}
          className={cx("flex items-center rounded-lg px-3 py-2.5 font-medium", key === current ? "bg-light text-pri-h" : "text-tx2 hover:text-pri-h")}
        >
          {t(`pages.${key}`)}
        </Link>
      ))}
    </nav>
  );
}

async function PolicyArticle({ params }: Pick<Props, "params">) {
  const { slug } = await params;
  if (!infoPageKey(slug)) notFound();
  const locale = (await getLocale()) as Locale;
  const t = await getTranslations("store.policy");
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  let shown: Shown | null;
  try {
    shown = await shownPage(slug, locale);
  } catch {
    return (
      <div className={ARTICLE}>
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("error")}
        </p>
      </div>
    );
  }
  if (!shown) notFound();
  const { page, fallback, other } = shown;
  const otherLocale: Locale = page.locale === "rw" ? "en" : "rw";
  // English text shown to a Kinyarwanda reader is marked as English for screen readers.
  const lang = fallback ? "en" : undefined;
  return (
    <article className={ARTICLE}>
      <Breadcrumb
        label={tu("breadcrumb")}
        items={[{ label: th("home"), href: getPathname({ href: "/", locale }) }, { label: t("help") }, { label: page.title, lang }]}
      />
      <div className="flex flex-col gap-1.5">
        <h1 lang={lang} className="t-h1 text-navy">
          {page.title}
        </h1>
        <span className="text-sm text-mut">
          {t("updated", { date: formatDate(page.updated_at, "date") })}
          {other && (
            <>
              {" · "}
              <Link href={`/pages/${slug}`} locale={otherLocale} lang={otherLocale} className="underline">
                {t(otherLocale === "rw" ? "readRw" : "readEn")}
              </Link>
            </>
          )}
        </span>
      </div>
      {fallback && (
        <p className="rounded-xl bg-warn-bg px-4 py-3 text-sm text-warn-tx">
          {t("fallback")}
        </p>
      )}
      <div lang={lang}>
        <RichText markdown={page.body} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bd pt-3">
        <span className="text-sm text-mut">{t("question")}</span>
        <span className="flex flex-wrap gap-2.5">
          <WhatsAppLink label={t("whatsapp")} message={t("whatsappMessage", { page: page.title })} size="sm" iconSize={16} />
          <Link href="/contact" className={buttonClasses({ variant: "outline", size: "sm" })}>
            {t("contact")}
          </Link>
        </span>
      </div>
    </article>
  );
}

function NavFallback() {
  return <Skeleton className="h-[340px] w-full rounded-xl sm:max-w-[260px] sm:flex-[1_1_240px]" />;
}

function ArticleFallback() {
  return (
    <div aria-busy="true" className={ARTICLE}>
      <Skeleton className="h-5 w-48" />
      <Skeleton className="h-10 w-2/3" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}
