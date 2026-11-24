"use client";

import { ArrowLeft, Check, Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment } from "react";
import { Logo } from "@/components/store/logo";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { CHECKOUT_STEPS, type CheckoutStep } from "@/lib/checkout";

/** CheckoutHeader.dc.html: the logo, the four steps and "Secure checkout"; no store navigation.
 * `step` null hides the steps (the payment status page). Phones get MobileCheckout.dc.html's
 * header: back, logo, "Secure" and a "Step n of 4" progress bar. */
export function CheckoutHeader({ step, backHref = "/cart", onBack }: { step: CheckoutStep | null; backHref?: string; onBack?: () => void }) {
  const t = useTranslations("store.checkout");
  const ts = useTranslations("store");
  const index = step ? CHECKOUT_STEPS.indexOf(step) : -1;
  const backClass = "flex size-10 items-center justify-center rounded-lg border-0 bg-transparent text-tx2 cursor-pointer";
  return (
    <header className="border-b border-bd bg-card">
      {/* Phone */}
      <div className="sm:hidden">
        <div className="flex h-14 items-center justify-between px-3">
          {onBack ? (
            <button type="button" aria-label={t("back")} onClick={onBack} className={backClass}>
              <ArrowLeft size={22} aria-hidden="true" />
            </button>
          ) : (
            <Link href={backHref} aria-label={t("back")} className={backClass}>
              <ArrowLeft size={22} aria-hidden="true" />
            </Link>
          )}
          <Link href="/" aria-label={ts("homeLink")}>
            <Logo height={34} alt={ts("logoAlt")} eager />
          </Link>
          <span className="flex items-center gap-1 text-cap font-semibold text-ok-tx">
            <Lock size={14} aria-hidden="true" />
            {t("secureShort")}
          </span>
        </div>
        {step && (
          <div className="px-4 pb-3">
            <div className="mb-1.5 flex items-center justify-between text-cap font-medium">
              <span className="text-mut">{t("stepOf", { n: index + 1, total: CHECKOUT_STEPS.length })}</span>
              <span>{t(`steps.${step}`)}</span>
            </div>
            <div
              role="progressbar"
              aria-label={t("stepsLabel")}
              aria-valuemin={1}
              aria-valuemax={CHECKOUT_STEPS.length}
              aria-valuenow={index + 1}
              className="h-1.5 overflow-hidden rounded bg-bd"
            >
              <span className="block h-full rounded bg-pri" style={{ width: `${((index + 1) / CHECKOUT_STEPS.length) * 100}%` }} />
            </div>
          </div>
        )}
      </div>
      {/* Tablet and desktop */}
      <div className="wrap hidden min-h-[76px] flex-wrap items-center justify-between gap-6 py-2.5 sm:flex">
        <Link href="/" aria-label={ts("homeLink")}>
          <Logo height={48} alt={ts("logoAlt")} eager />
        </Link>
        {step && (
          <ol aria-label={t("stepsLabel")} className="m-0 flex list-none items-center gap-3 p-0">
            {CHECKOUT_STEPS.map((s, i) => {
              const done = i < index;
              const now = i === index;
              return (
                <Fragment key={s}>
                  <li className="flex items-center gap-2" aria-current={now ? "step" : undefined}>
                    <span
                      aria-hidden="true"
                      className={cx(
                        "inline-flex size-8 flex-none items-center justify-center rounded-full text-[13px] font-semibold",
                        done && "bg-ok-tx text-white",
                        now && "bg-pri text-white",
                        !done && !now && "border border-bd2 bg-card text-mut",
                      )}
                    >
                      {done ? <Check size={16} aria-hidden="true" /> : i + 1}
                    </span>
                    <span className={cx("text-sm", now ? "font-semibold" : done ? "font-medium" : "font-medium text-mut")}>
                      {t(`steps.${s}`)}
                      {done && <span className="sr-only"> ({t("stepDone")})</span>}
                    </span>
                    {i < CHECKOUT_STEPS.length - 1 && (
                      <span aria-hidden="true" className={cx("ml-1 h-0.5 w-12", done ? "bg-ok" : "bg-bd")} />
                    )}
                  </li>
                </Fragment>
              );
            })}
          </ol>
        )}
        <div className="flex items-center gap-2">
          <Lock size={18} className="text-ok" aria-hidden="true" />
          <span className="font-semibold">{t("secure")}</span>
        </div>
      </div>
    </header>
  );
}

/** The small footer under checkout pages: copyright and the delivery and returns policies. */
export function CheckoutFooter({ deliveryHref, returnsHref }: { deliveryHref: string; returnsHref: string }) {
  const t = useTranslations("store.checkout");
  return (
    <div className="wrap flex flex-wrap items-center justify-between gap-3 pb-8 text-cap text-tx2">
      <span>{t("copyright", { year: 2026 })}</span>
      <span className="flex gap-4">
        <Link href={deliveryHref}>{t("deliveryPolicy")}</Link>
        <Link href={returnsHref}>{t("returnsPolicy")}</Link>
        <WhatsAppLink label={t("whatsappHelp")} variant="link" />
      </span>
    </div>
  );
}
