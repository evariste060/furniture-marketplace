"use client";

import { House, RefreshCw, TriangleAlert } from "lucide-react";
import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { startTransition, useEffect } from "react";
import { Button, buttonClasses } from "@/components/ui/button";

/** An admin page that failed to render, in the AccessDenied card layout with ServerError.dc.html's
 * "Try again" and error reference (Next.js's digest of the server error, kept in the server log). */
export function AdminErrorCard({ error, reset, home = "/admin" }: { error: Error & { digest?: string }; reset: () => void; home?: string }) {
  const t = useTranslations("admin.failed");
  const router = useRouter();
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="flex justify-center pt-24 max-md:pt-8">
      <section className="flex max-w-[480px] flex-col items-center gap-3.5 rounded-xl border border-bd bg-white p-8 text-center">
        <span aria-hidden="true" className="flex size-20 items-center justify-center rounded-full bg-warn-bg text-warn-tx">
          <TriangleAlert size={32} />
        </span>
        <h1 className="t-h2">{t("title")}</h1>
        <p className="text-tx2">{t("body")}</p>
        <div className="flex flex-wrap justify-center gap-2.5">
          <Button
            onClick={() =>
              startTransition(() => {
                router.refresh();
                reset();
              })
            }
          >
            <RefreshCw size={16} aria-hidden="true" />
            {t("retry")}
          </Button>
          <NextLink href={home} className={buttonClasses({ variant: "outline" })}>
            <House size={16} aria-hidden="true" />
            {t("back")}
          </NextLink>
        </div>
        {error.digest && <span className="text-cap text-tx2">{t("reference", { reference: error.digest })}</span>}
      </section>
    </div>
  );
}
