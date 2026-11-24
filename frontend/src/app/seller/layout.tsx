import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense, type ReactNode } from "react";
import { ToastProvider } from "@/components/ui/toast";
import { SellerGate } from "@/features/seller/gate";
import { SellerShell } from "@/features/seller/shell";
import { QueryProvider } from "@/lib/query/provider";
import { getSellerVisitor } from "@/lib/seller";
import { inter } from "../fonts";
import "../globals.css";
import { ThemeScript } from "@/lib/theme-script";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin.seller.titles");
  return { title: { default: t("suffix"), template: `%s · ${t("suffix")}` }, robots: { index: false, follow: false } };
}

/** The seller dashboard's root layout (ADR-014 phase 4). Every request is checked on the server:
 * no session → sign in; staff, no store or a store that is not approved → a notice; the owner of
 * an approved store → the shell. The backend resolves the store again on every call, so a
 * suspension applies at once. The language comes from the panel's cookie (path /seller). */
export default function SellerLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className="bg-page">
        <QueryProvider>
          <Suspense fallback={<ShellFallback />}>
            <Gate>{children}</Gate>
          </Suspense>
        </QueryProvider>
      </body>
    </html>
  );
}

async function Gate({ children }: { children: ReactNode }) {
  const visitor = await getSellerVisitor();
  if (visitor.kind === "signed-out") redirect("/login?returnTo=%2Fseller");
  const locale = await getLocale();
  const t = await getTranslations("admin.shell");
  return (
    <NextIntlClientProvider>
      <ToastProvider closeLabel={t("close")}>
        <div lang={locale} className="contents">
          {visitor.kind === "seller" ? (
            <SellerShell
              store={{ id: visitor.store.id, name: visitor.store.name, slug: visitor.store.slug, commissionRateBps: visitor.store.effective_commission_rate_bps }}
              fullName={visitor.fullName}
            >
              {children}
            </SellerShell>
          ) : (
            <SellerGate visitor={visitor} />
          )}
        </div>
      </ToastProvider>
    </NextIntlClientProvider>
  );
}

/** The sidebar and top bar's footprint while the seller check runs. */
function ShellFallback() {
  return (
    <div aria-busy="true" className="flex min-h-dvh bg-page">
      <div className="hidden w-60 flex-none bg-deep lg:block" />
      <div className="flex-1">
        <div className="h-[68px] border-b border-bd bg-card" />
      </div>
    </div>
  );
}
