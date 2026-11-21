import { Lock } from "lucide-react";
import NextLink from "next/link";
import { getTranslations } from "next-intl/server";
import { buttonClasses } from "@/components/ui/button";

/** A customer session opened /admin: no admin data or navigation, just the way out. */
export async function NotStaff() {
  const t = await getTranslations("admin.denied");
  return (
    <main id="main" className="flex min-h-dvh items-center justify-center bg-page p-4">
      <section className="flex max-w-[480px] flex-col items-center gap-3.5 rounded-xl border border-bd bg-white p-8 text-center">
        <span aria-hidden="true" className="flex size-20 items-center justify-center rounded-full bg-warn-bg text-warn-tx">
          <Lock size={32} />
        </span>
        <h1 className="t-h2">{t("notStaffTitle")}</h1>
        <p className="text-tx2">{t("notStaffBody")}</p>
        <div className="flex flex-wrap justify-center gap-2.5">
          <NextLink href="/" className={buttonClasses({ variant: "neutral" })}>
            {t("toStore")}
          </NextLink>
        </div>
      </section>
    </main>
  );
}
