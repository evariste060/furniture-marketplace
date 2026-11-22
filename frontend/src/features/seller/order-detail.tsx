"use client";

import { ArrowRight } from "lucide-react";
import NextLink from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { MethodMark, OrderStatusBadge, PaymentStatusBadge } from "@/features/admin/status";
import { LoadError, PageHeader } from "@/features/admin/ui";
import { ApiError } from "@/lib/api/errors";
import { formatDate, formatMoney, formatPhone } from "@/lib/format";
import { moveErrorKey, nextSellerStep, useMoveSellerOrder, useSellerOrder, type SellerMove, type SellerOrderDetail } from "./orders-api";
import { SellerOrderBadge } from "./status";
import { percent } from "./store-context";

const REASON_MAX = 500;

/** /seller/orders/[id]: the store's own lines, money, recipient and delivery address, and the one
 * step the store can take next. Nothing about other stores' lines or the order's total. */
export function SellerOrderDetailView({ id }: { id: string }) {
  const t = useTranslations("admin.seller.order");
  const query = useSellerOrder(id);
  if (query.isError) {
    if (query.error instanceof ApiError && [404, 422].includes(query.error.status))
      return (
        <Card padding={32} className="flex flex-col items-start gap-3">
          <h1 className="t-h2">{t("notFound")}</h1>
          <NextLink href="/seller/orders" className={buttonClasses({ variant: "neutral", size: "sm" })}>
            {t("back")}
          </NextLink>
        </Card>
      );
    return <LoadError onRetry={() => query.refetch()} />;
  }
  if (!query.data) return <DetailSkeleton />;
  return <Detail order={query.data} />;
}

function Detail({ order }: { order: SellerOrderDetail }) {
  const t = useTranslations("admin.seller.order");
  const address = order.delivery_address;
  const addressLines = [address.street_address, [address.village, address.cell].filter(Boolean).join(", "), [address.sector, address.district].filter(Boolean).join(", "), address.province].filter(
    (line): line is string => Boolean(line),
  );
  return (
    <>
      <PageHeader
        title={order.order_number}
        back={{ label: t("back"), href: "/seller/orders" }}
        badges={<SellerOrderBadge status={order.status} />}
        description={t("placed", { date: formatDate(order.created_at, "dateTime") })}
      />
      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <NextStep order={order} />
          <Card className="overflow-hidden">
            <h2 className="t-h3 border-b border-bd px-5 py-[18px]">{t("items")}</h2>
            <Table>
              <thead>
                <tr>
                  <Th>{t("columns.product")}</Th>
                  <Th>{t("columns.sku")}</Th>
                  <Th className="text-right">{t("columns.quantity")}</Th>
                  <Th className="text-right">{t("columns.price")}</Th>
                  <Th className="text-right">{t("columns.discount")}</Th>
                  <Th className="text-right">{t("columns.total")}</Th>
                </tr>
              </thead>
              <tbody>
                {order.lines.map((line) => (
                  <tr key={`${line.sku}-${line.unit_price}`}>
                    <Td>
                      <span className="flex flex-col">
                        <b className="font-medium">{line.product_name}</b>
                        {line.variant_name && <span className="text-cap text-tx2">{line.variant_name}</span>}
                      </span>
                    </Td>
                    <Td className="font-mono text-cap whitespace-nowrap text-tx2">{line.sku}</Td>
                    <Td className="text-right tabular-nums">{line.quantity}</Td>
                    <Td className="text-right whitespace-nowrap tabular-nums">{formatMoney(line.unit_price)}</Td>
                    <Td className="text-right whitespace-nowrap tabular-nums">{line.discount_amount ? `−${formatMoney(line.discount_amount)}` : "—"}</Td>
                    <Td className="text-right font-semibold whitespace-nowrap tabular-nums">{formatMoney(line.line_total)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <dl className="m-0 flex flex-col gap-2 border-t border-bd px-5 py-4">
              <Row label={t("money.subtotal")} value={formatMoney(order.subtotal)} />
              {order.discount_total > 0 && <Row label={t("money.discount")} value={`−${formatMoney(order.discount_total)}`} />}
              <Row label={t("money.goods")} value={formatMoney(order.merchandise_total)} />
              <Row label={t("money.commission", { rate: percent(order.commission_rate_bps) })} value={`−${formatMoney(order.commission_amount)}`} />
              <Row label={t("money.net")} value={formatMoney(order.seller_net_amount)} strong />
            </dl>
          </Card>
          <Card padding={24} className="flex flex-col gap-3">
            <h2 className="t-h3">{t("history")}</h2>
            <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
              {order.status_history.map((entry, i) => (
                <li key={`${entry.status}-${entry.created_at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <SellerOrderBadge status={entry.status} />
                  <span className="text-cap text-tx2">{formatDate(entry.created_at, "dateTime")}</span>
                  {entry.reason && <span className="basis-full text-sm text-tx">{entry.reason}</span>}
                </li>
              ))}
            </ol>
          </Card>
        </div>
        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
          <Card padding={20} className="flex flex-col gap-2">
            <h2 className="t-h4">{t("deliverTo")}</h2>
            <b className="font-semibold">{order.recipient_name}</b>
            <span className="text-sm">
              {t("phone")}: <a href={`tel:${order.recipient_phone}`}>{formatPhone(order.recipient_phone)}</a>
            </span>
            {addressLines.map((line) => (
              <span key={line} className="text-sm text-tx2">
                {line}
              </span>
            ))}
            {order.delivery_zone && (
              <span className="text-sm text-tx2">
                {t("zone")}: {order.delivery_zone}
              </span>
            )}
            {address.delivery_instructions && (
              <span className="text-sm">
                {t("instructions")}: {address.delivery_instructions}
              </span>
            )}
          </Card>
          <Card padding={20} className="flex flex-col gap-2.5">
            <h2 className="t-h4">{t("payment")}</h2>
            {order.payment_method && <MethodMark method={order.payment_method} />}
            {order.payment_status && (
              <span>
                <PaymentStatusBadge status={order.payment_status} method={order.payment_method} />
              </span>
            )}
          </Card>
          <Card padding={20} className="flex flex-col gap-2.5">
            <h2 className="t-h4">{t("wholeOrder")}</h2>
            <span>
              <OrderStatusBadge status={order.order_status} />
            </span>
            <p className="m-0 text-cap text-tx2">{t("wholeOrderHint")}</p>
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className={strong ? "font-semibold" : "text-tx2"}>{label}</dt>
      <dd className={strong ? "m-0 t-h4 tabular-nums" : "m-0 tabular-nums"}>{value}</dd>
    </div>
  );
}

/** The store's next step, with a confirmation (each step is final for the store). */
function NextStep({ order }: { order: SellerOrderDetail }) {
  const t = useTranslations("admin.seller.order");
  const step = nextSellerStep(order.status);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card padding={20} className="flex flex-wrap items-center justify-between gap-3">
      <span className="flex min-w-0 flex-[1_1_280px] flex-col gap-1">
        <b className="t-h4">{t("nextStep")}</b>
        <span className="text-sm text-tx2">{t(`hint.${order.status}`)}</span>
        {error && (
          <span role="alert" className="text-sm text-err-tx">
            {error}
          </span>
        )}
      </span>
      {step && (
        <Button onClick={() => setOpen(true)} className="gap-2">
          {t(`action.${step}`)}
          <ArrowRight size={16} aria-hidden="true" />
        </Button>
      )}
      {open && step && <MoveDialog order={order} step={step} onClose={() => setOpen(false)} onError={setError} />}
    </Card>
  );
}

function MoveDialog({ order, step, onClose, onError }: { order: SellerOrderDetail; step: SellerMove; onClose: () => void; onError: (message: string | null) => void }) {
  const t = useTranslations("admin");
  const toast = useToast();
  const [reason, setReason] = useState("");
  const move = useMoveSellerOrder(order.id);
  const action = t(`seller.order.action.${step}`);
  const submit = () =>
    move.mutate(
      { status: step, reason: reason.trim() || null },
      {
        onSuccess: (detail) => {
          onError(null);
          toast.show(t("seller.order.moved", { number: detail.order_number, status: t(`status.sellerOrder.${detail.status}`) }));
          onClose();
        },
        onError: (e) => {
          onError(t(`seller.order.errors.${moveErrorKey(e)}`));
          onClose();
        },
      },
    );
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("seller.order.confirmTitle", { action })}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={move.isPending} onClick={submit}>
            {action}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="m-0 text-tx2">
          {t("seller.order.confirmBody", { number: order.order_number })} {t(`seller.order.hint.${order.status}`)}
        </p>
        <Field
          label={
            <>
              {t("seller.order.reasonLabel")} <span className="font-normal text-tx2">{t("common.optional")}</span>
            </>
          }
          help={t("seller.order.reasonHelp")}
        >
          {(c) => <Textarea {...c} rows={2} maxLength={REASON_MAX} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
    </Dialog>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-80" />
      <div className="flex flex-wrap gap-5">
        <Skeleton className="h-[420px] min-w-0 flex-[999_1_560px]" />
        <Skeleton className="h-72 min-w-0 flex-[1_1_300px]" />
      </div>
    </div>
  );
}
