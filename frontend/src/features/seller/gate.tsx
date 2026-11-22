import { Clock, Lock, Store, TriangleAlert, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { getTranslations } from "next-intl/server";
import { buttonClasses } from "@/components/ui/button";
import { cx } from "@/lib/cx";
import type { SellerVisitor } from "@/lib/seller";

/** Why the seller dashboard is closed to this visitor (ADR-014 phase 4): a staff account, no
 * store, or a store that is pending, rejected or suspended. No store data beyond the visitor's
 * own application status, name and reason, and no dashboard navigation. */
export async function SellerGate({ visitor }: { visitor: Exclude<SellerVisitor, { kind: "signed-out" } | { kind: "seller" }> }) {
  const t = await getTranslations("admin.seller.gate");
  const application = "/account/seller";
  const view: { Icon: LucideIcon; tone: string; title: string; body: string; reason?: string | null; action: { href: string; label: string; external?: boolean } } = (() => {
    switch (visitor.kind) {
      case "staff":
        return { Icon: Lock, tone: "bg-warn-bg text-warn-tx", title: t("staffTitle"), body: t("staffBody"), action: { href: "/admin", label: t("toAdmin") } };
      case "no-store":
        return { Icon: Store, tone: "bg-light text-pri-h", title: t("noStoreTitle"), body: t("noStoreBody"), action: { href: application, label: t("apply"), external: true } };
      case "not-approved": {
        const { status, name, status_reason } = visitor.store;
        const store = name;
        if (status === "rejected")
          return { Icon: TriangleAlert, tone: "bg-warn-bg text-warn-tx", title: t("rejectedTitle"), body: t("rejectedBody", { store }), reason: status_reason, action: { href: application, label: t("toApplication"), external: true } };
        if (status === "suspended")
          return { Icon: Lock, tone: "bg-err-bg text-err-tx", title: t("suspendedTitle"), body: t("suspendedBody", { store }), reason: status_reason, action: { href: application, label: t("toApplication"), external: true } };
        return { Icon: Clock, tone: "bg-light text-pri-h", title: t("pendingTitle"), body: t("pendingBody", { store }), action: { href: application, label: t("toApplication"), external: true } };
      }
    }
  })();
  const { Icon } = view;
  return (
    <main id="main" className="flex min-h-dvh items-center justify-center bg-page p-4">
      <section className="flex max-w-[480px] flex-col items-center gap-3.5 rounded-xl border border-bd bg-white p-8 text-center">
        <span aria-hidden="true" className={cx("flex size-20 items-center justify-center rounded-full", view.tone)}>
          <Icon size={32} />
        </span>
        <h1 className="t-h2">{view.title}</h1>
        <p className="text-tx2">{view.body}</p>
        {view.reason && <p className="rounded-lg bg-page px-4 py-3 text-sm text-tx">{t("reason", { reason: view.reason })}</p>}
        <div className="flex flex-wrap justify-center gap-2.5">
          {/* The account pages belong to the storefront (locale routing): a plain link. */}
          {view.action.external ? (
            <a href={view.action.href} className={buttonClasses({ variant: "primary" })}>
              {view.action.label}
            </a>
          ) : (
            <NextLink href={view.action.href} className={buttonClasses({ variant: "primary" })}>
              {view.action.label}
            </NextLink>
          )}
          <a href="/" className={buttonClasses({ variant: "neutral" })}>
            {t("toShop")}
          </a>
        </div>
      </section>
    </main>
  );
}
