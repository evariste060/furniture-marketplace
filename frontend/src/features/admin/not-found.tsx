import { House, SearchX } from "lucide-react";
import NextLink from "next/link";
import { getTranslations } from "next-intl/server";
import { buttonClasses } from "@/components/ui/button";

/** An unknown admin address, or an order or product that does not exist, in the AccessDenied
 * card layout (the admin has no design of its own for this). */
export async function AdminNotFound({ home = "/admin" }: { home?: string }) {
  const t = await getTranslations("admin.missing");
  return (
    <div className="flex justify-center pt-24 max-md:pt-8">
      <section className="flex max-w-[480px] flex-col items-center gap-3.5 rounded-xl border border-bd bg-card p-8 text-center">
        <span aria-hidden="true" className="flex size-20 items-center justify-center rounded-full bg-light text-pri-h">
          <SearchX size={32} />
        </span>
        <h1 className="t-h2">{t("title")}</h1>
        <p className="text-tx2">{t("body")}</p>
        <NextLink href={home} className={buttonClasses({ variant: "primary" })}>
          <House size={16} aria-hidden="true" />
          {t("back")}
        </NextLink>
      </section>
    </div>
  );
}
