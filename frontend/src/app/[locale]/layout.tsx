import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getTranslations } from "next-intl/server";
import { ToastProvider } from "@/components/ui/toast";
import { routing } from "@/i18n/routing";
import { QueryProvider } from "@/lib/query/provider";
import { inter } from "../fonts";
import "../globals.css";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: LayoutProps<"/[locale]">): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "meta" });
  return { title: { default: t("title"), template: `%s · ${t("title")}` }, description: t("description") };
}

/** The storefront's root layout: English at "/", Kinyarwanda under "/rw". */
export default async function LocaleLayout({ children, params }: LayoutProps<"/[locale]">) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: "ui" });
  return (
    <html lang={locale} className={inter.variable}>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2"
        >
          {t("skipToContent")}
        </a>
        <NextIntlClientProvider>
          <QueryProvider>
            <ToastProvider closeLabel={t("close")}>{children}</ToastProvider>
          </QueryProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
