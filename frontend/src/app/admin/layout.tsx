import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense, type ReactNode } from "react";
import { ToastProvider } from "@/components/ui/toast";
import { AdminShell } from "@/features/admin/shell";
import { NotStaff } from "@/features/admin/not-staff";
import { QueryProvider } from "@/lib/query/provider";
import { MARKETPLACE_NAME } from "@/lib/marketplace";
import { getAdminVisitor } from "@/lib/staff";
import { inter } from "../fonts";
import "../globals.css";

export const metadata: Metadata = {
  title: { default: `Admin · ${MARKETPLACE_NAME}`, template: `%s · Admin · ${MARKETPLACE_NAME}` },
  robots: { index: false, follow: false },
};

/** The admin's root layout. Every request is checked on the server: no session → sign in; a
 * customer session → a notice; staff → the shell with their permissions. The backend checks every
 * call again. The language (English or Kinyarwanda, chosen in the top bar) is read per request, so
 * the messages are provided inside the suspended part; <html lang> stays "en" and the shell carries
 * the chosen language. */
export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
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
  const visitor = await getAdminVisitor();
  if (visitor.kind === "signed-out") redirect("/login?returnTo=%2Fadmin");
  const locale = await getLocale();
  const t = await getTranslations("admin.shell");
  return (
    <NextIntlClientProvider>
      <ToastProvider closeLabel={t("close")}>
        <div lang={locale} className="contents">
          {visitor.kind === "not-staff" ? <NotStaff /> : <AdminShell access={visitor.access}>{children}</AdminShell>}
        </div>
      </ToastProvider>
    </NextIntlClientProvider>
  );
}

/** The sidebar and top bar's footprint while the staff check runs. */
function ShellFallback() {
  return (
    <div aria-busy="true" className="flex min-h-dvh bg-page">
      <div className="hidden w-60 flex-none bg-deep lg:block" />
      <div className="flex-1">
        <div className="h-[68px] border-b border-bd bg-white" />
      </div>
    </div>
  );
}
