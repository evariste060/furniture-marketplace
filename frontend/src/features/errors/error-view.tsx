"use client";

import { House, RefreshCw, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { startTransition, useEffect } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { Link } from "@/i18n/navigation";

/** ServerError.dc.html, shown by the storefront's error boundaries. "Try again" fetches the page
 * from the server again and re-renders it. The reference is Next.js's digest of the server error,
 * which the server log records with the error; the error's own message is never shown. The
 * WhatsApp button shows once the store's number is known (GET /settings, from the browser). */
export function ErrorView({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("store.error");
  const router = useRouter();
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex flex-col items-center gap-4 pt-12 pb-16 text-center sm:pt-[72px] sm:pb-20">
        <span className="flex size-24 items-center justify-center rounded-full bg-warn-bg text-warn-tx" aria-hidden="true">
          <TriangleAlert size={40} />
        </span>
        <h1 className="t-h1">{t("title")}</h1>
        <p className="text-lg max-w-[520px] text-tx2">{t("text")}</p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button
            onClick={() =>
              startTransition(() => {
                router.refresh();
                reset();
              })
            }
          >
            <RefreshCw size={18} aria-hidden="true" />
            {t("retry")}
          </Button>
          <Link href="/" className={buttonClasses({ variant: "outline" })}>
            <House size={18} aria-hidden="true" />
            {t("home")}
          </Link>
          <WhatsAppLink label={t("whatsapp")} />
        </div>
        {error.digest && <span className="text-cap text-tx2">{t("reference", { reference: error.digest })}</span>}
      </div>
    </main>
  );
}
