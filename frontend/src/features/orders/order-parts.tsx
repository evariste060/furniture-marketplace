"use client";

import { Check, House, Package, ShoppingBag, Truck, Wallet, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment } from "react";
import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate } from "@/lib/format";
import { orderProgress, STATUS_TONE, type OrderStatus, type ProgressStep, type StepKey } from "@/lib/order-progress";

type Order = components["schemas"]["OrderDetailResponse"];

/** The order status badge (s-info, s-ok… in the designs). */
export function StatusBadge({ status, className }: { status: OrderStatus; className?: string }) {
  const t = useTranslations("store.orderInfo.status");
  return (
    <Badge tone={STATUS_TONE[status]} className={className}>
      {t(status)}
    </Badge>
  );
}

const ICONS: Record<StepKey, LucideIcon> = { placed: ShoppingBag, paid: Wallet, packed: Package, dispatched: Truck, delivered: House };

function StepDot({ step }: { step: ProgressStep }) {
  const Icon = ICONS[step.key];
  return (
    <span
      aria-hidden="true"
      className={cx(
        "inline-flex size-8 flex-none items-center justify-center rounded-full text-[13px] font-semibold",
        // WCAG AA: white on --ok is 3.30:1, so done steps use --ok-tx.
        step.state === "done" && "bg-ok-tx text-white",
        step.state === "now" && "bg-pri text-white",
        step.state === "todo" && "border border-bd2 bg-card text-tx2",
      )}
    >
      {step.state === "done" ? <Check size={16} /> : <Icon size={16} />}
    </span>
  );
}

function useStepText(order: Order, wording: "short" | "long") {
  const t = useTranslations("store.orderInfo");
  const tm = useTranslations("store.order.method");
  const cash = order.payment?.method === "cash_on_delivery";
  return (step: ProgressStep) => {
    const label = step.key === "paid" && cash ? t(`steps.${wording}.confirmed`) : t(`steps.${wording}.${step.key}`);
    const time = step.at ? formatDate(step.at, "dayTime") : null;
    let note: string;
    if (step.key === "paid" && order.payment) {
      const method = tm(order.payment.method as "mtn_momo" | "airtel_money" | "cash_on_delivery");
      note = time && wording === "long" ? `${method} · ${time}` : method;
    } else note = time ?? t("pending");
    return { label, note, state: step.state === "done" ? t("stepDone") : step.state === "now" ? t("stepNow") : t("stepTodo") };
  };
}

/** Track.dc.html: a vertical list with a line between the dots. */
export function ProgressList({ order, wording = "long", className }: { order: Order; wording?: "short" | "long"; className?: string }) {
  const steps = orderProgress(order);
  const text = useStepText(order, wording);
  return (
    <ol className={cx("m-0 flex list-none flex-col p-0", className)}>
      {steps.map((step, i) => {
        const { label, note, state } = text(step);
        return (
          <li key={step.key} className="flex items-start gap-3.5" aria-current={step.state === "now" ? "step" : undefined}>
            <span className="flex flex-col items-center">
              <StepDot step={step} />
              {i < steps.length - 1 && <span aria-hidden="true" className={cx("h-8 w-0.5", steps[i + 1]?.state === "done" ? "bg-ok" : "bg-bd")} />}
            </span>
            <span className="flex flex-col pt-[5px]">
              <b className={cx("font-semibold", step.state === "todo" && "text-tx2")}>
                {label}
                <span className="sr-only"> ({state})</span>
              </b>
              <span className="text-cap text-tx2">{note}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** OrderDetail.dc.html: the five steps in a row with lines between (a list on phones). */
export function ProgressRow({ order }: { order: Order }) {
  const steps = orderProgress(order);
  const text = useStepText(order, "short");
  return (
    <>
      <ProgressList order={order} wording="short" className="sm:hidden" />
      <ol className="m-0 hidden list-none items-start p-0 sm:flex">
        {steps.map((step, i) => {
          const { label, note, state } = text(step);
          return (
            <Fragment key={step.key}>
              <li className="flex flex-1 flex-col items-center gap-2 text-center" aria-current={step.state === "now" ? "step" : undefined}>
                <StepDot step={step} />
                <b className={cx("text-sm font-semibold", step.state === "todo" && "text-tx2")}>
                  {label}
                  <span className="sr-only"> ({state})</span>
                </b>
                <span className="text-cap text-tx2">{note}</span>
              </li>
              {i < steps.length - 1 && <li aria-hidden="true" className={cx("mt-4 h-0.5 flex-1", steps[i + 1]?.state === "done" ? "bg-ok" : "bg-bd")} />}
            </Fragment>
          );
        })}
      </ol>
    </>
  );
}

/** "KG 11 Ave, House 24, Kimironko, Gasabo" from an order's address snapshot. */
export function addressLine(address: Record<string, unknown>, parts: readonly string[] = ["street_address", "sector", "district"]): string {
  return parts
    .map((key) => address[key])
    .filter((v): v is string => typeof v === "string" && v.trim() !== "")
    .join(", ");
}
