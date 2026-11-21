import { House, Lock } from "lucide-react";
import NextLink from "next/link";
import { getTranslations } from "next-intl/server";
import { buttonClasses } from "@/components/ui/button";
import { NAV, type NavKey } from "./nav";
import { rolesFor } from "./roles";

/** AccessDenied.dc.html: shown inside the admin shell when the role can't open a page. */
export async function AccessDenied({ area }: { area?: NavKey }) {
  const t = await getTranslations("admin");
  const item = NAV.flatMap((g) => g.items).find((i) => i.key === area);
  let body = t("denied.bodyGeneric");
  if (item) {
    const roles = rolesFor(item.anyOf).map((role) => t(`shell.roles.${role}`));
    const list = new Intl.ListFormat("en", { type: "conjunction" }).format(roles);
    body = t("denied.body", { area: t(`shell.nav.${item.key}`), roles: list });
  }
  return (
    <div className="flex justify-center pt-24 max-md:pt-8">
      <section className="flex max-w-[480px] flex-col items-center gap-3.5 rounded-xl border border-bd bg-white p-8 text-center">
        <span aria-hidden="true" className="flex size-20 items-center justify-center rounded-full bg-warn-bg text-warn-tx">
          <Lock size={32} />
        </span>
        <h1 className="t-h2">{t("denied.title")}</h1>
        <p className="text-tx2">{body}</p>
        <NextLink href="/admin" className={buttonClasses({ variant: "primary" })}>
          <House size={16} aria-hidden="true" />
          {t("denied.back")}
        </NextLink>
      </section>
    </div>
  );
}
