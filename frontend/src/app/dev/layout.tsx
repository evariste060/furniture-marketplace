import type { Metadata } from "next";
import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { NextIntlClientProvider } from "next-intl";
import { ToastProvider } from "@/components/ui/toast";
import { devPagesEnabled } from "@/lib/dev-pages";
import { QueryProvider } from "@/lib/query/provider";
import { inter } from "../fonts";
import "../globals.css";

export const metadata: Metadata = {
  title: "Component gallery",
  robots: { index: false, follow: false },
};

export default function DevLayout({ children }: { children: ReactNode }) {
  if (!devPagesEnabled()) notFound();
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <NextIntlClientProvider>
          <QueryProvider>
            <ToastProvider closeLabel="Close">{children}</ToastProvider>
          </QueryProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
