"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, ExternalLink, History as HistoryIcon, Mail, MapPin, MessageSquareText, Phone, Printer, Truck, UserRound, XCircle } from "lucide-react";
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
import { addressLine } from "@/features/orders/order-parts";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { cx } from "@/lib/cx";
import { formatDate, formatMoney, formatPhone } from "@/lib/format";
import { useStaffAccess } from "./access";
import { CopyChip, DrawerHeader, DrawerSection, Fact, FACTS, Stepper, Timeline, TimelineItem } from "./inbox";
import { timeAgo } from "./time";
import { OrderStatusBadge, PaymentStatusBadge, type OrderStatus } from "./status";
import { LoadError, must, PageHeader, Thumb } from "./ui";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";

type StaffOrder = components["schemas"]["StaffOrderDetailResponse"];

type SellerOrder = StaffOrder["seller_orders"][number];

/** ADR-014 phase 3 (owner decision 2, 2026-11-21): each store's seller moves its own part of the
 * order and the order's status follows; staff have no fulfilment controls. The only change staff
 * make is cancelling the whole order, which the backend allows only while its stock is still on
 * hold (received). The backend checks every change again; this only decides what to show. */
export function staffCanCancel(status: OrderStatus): boolean {
  return status === "received";
}

/** wa.me wants the number in international form without "+". */
export function whatsappLink(phone: string): string {
  return `https://wa.me/${phone.replace(/\D/g, "")}`;
}

const ADDRESS_PARTS = ["street_address", "village", "cell", "sector", "district", "province"] as const;

/** AdminOrderDetail.dc.html */
export function OrderDetailView({ orderId }: { orderId: string }) {
  const t = useTranslations("admin");
  const { can } = useStaffAccess();
  const query = useQuery({
    queryKey: ["admin", "order", orderId],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/orders/{order_id}", {
          params: { path: { order_id: orderId } },
        }),
      ),
    retry: (count, error) => !(error instanceof ApiError && (error.status === 404 || error.status === 422)) && count < 2,
  });

  if (query.isError) {
    const missing = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 422);
    if (missing)
      return (
        <Card padding={32} className="flex flex-col items-start gap-3">
          <h1 className="t-h2">{t("order.notFound")}</h1>
          <p className="text-tx2">{t("order.notFoundBody")}</p>
          <NextLink href="/admin/orders" className={buttonClasses({ variant: "neutral", size: "sm" })}>
            {t("order.back")}
          </NextLink>
        </Card>
      );
    return <LoadError onRetry={() => query.refetch()} />;
  }
  if (!query.data) return <DetailSkeleton />;

  const order = query.data;
  const fulfil = can("orders:fulfil");
  const paid = order.payment?.status === "succeeded";
  const docBase = `/api/backend/api/v1/staff/orders/${order.id}`;

  return (
    <>
      <PageHeader
        title={t("order.title", { number: order.order_number })}
        back={{ label: t("order.back"), href: "/admin/orders" }}
        badges={
          <>
            <OrderStatusBadge status={order.status} />
            {order.payment && <PaymentStatusBadge status={order.payment.status} method={order.payment.method} />}
          </>
        }
        description={
          <span className="text-sm text-tx2">
            {t("order.placed", {
              date: formatDate(order.created_at, "dateTime"),
            })}{" "}
            · {order.user_id ? t("order.account") : t("order.guest")}
          </span>
        }
        actions={
          <>
            <a
              href={`${docBase}/delivery-note`}
              className={buttonClasses({
                variant: "neutral",
                size: "sm",
                className: "gap-2",
              })}
            >
              <Printer size={16} aria-hidden="true" />
              {t("order.deliveryNote")}
            </a>
            {paid && (
              <a
                href={`${docBase}/invoice`}
                className={buttonClasses({
                  variant: "neutral",
                  size: "sm",
                  className: "gap-2",
                })}
              >
                <Download size={16} aria-hidden="true" />
                {t("order.invoice")}
              </a>
            )}
            {fulfil && staffCanCancel(order.status) && <CancelOrder order={order} />}
          </>
        }
      />

      <SellerOrders order={order} />

      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-5">
          <Items order={order} />
          <History order={order} />
        </div>
        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
          <Card padding={20} className="flex flex-col gap-2">
            <h2 className="t-h4">{t("order.customer")}</h2>
            <b className="text-sm font-medium">{order.recipient_name}</b>
            <span className="text-sm text-tx2">{formatPhone(order.recipient_phone)}</span>
            {order.customer_email && <span className="text-sm break-all text-tx2">{order.customer_email}</span>}
            <span className="text-cap text-tx2">{order.user_id ? t("order.account") : t("order.guest")}</span>
            <a
              href={whatsappLink(order.recipient_phone)}
              target="_blank"
              rel="noopener noreferrer"
              className={buttonClasses({
                variant: "whatsapp-outline",
                size: "sm",
                className: "mt-1.5 gap-2 self-start",
              })}
            >
              <WhatsAppIcon size={16} aria-hidden="true" />
              {t("order.whatsapp")}
            </a>
          </Card>
          <Card padding={20} className="flex flex-col gap-1.5">
            <h2 className="t-h4">{t("order.deliveryTitle")}</h2>
            <span className="text-sm text-tx2">{addressLine(order.delivery_address, ADDRESS_PARTS)}</span>
            {typeof order.delivery_address.delivery_instructions === "string" && order.delivery_address.delivery_instructions && (
              <span className="text-cap text-tx2">
                {t("order.landmark", {
                  text: order.delivery_address.delivery_instructions,
                })}
              </span>
            )}
            {order.delivery_zone && (
              <span className="text-sm text-tx2">
                {t("order.zone")} <b className="font-medium text-tx">{order.delivery_zone}</b>
              </span>
            )}
            {order.customer_note && (
              <span className="text-sm text-tx2">
                {t("order.note")} {order.customer_note}
              </span>
            )}
          </Card>
          <PaymentCard order={order} />
        </div>
      </div>
    </>
  );
}

/** Each store's part of the order, read-only (ADR-014 phase 3): the stores move them. */
function SellerOrders({ order }: { order: StaffOrder }) {
  const t = useTranslations("admin");
  if (order.seller_orders.length === 0) return null;
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-light bg-light p-5" aria-labelledby="seller-orders-title">
      <div className="flex flex-col gap-0.5">
        <h2 id="seller-orders-title" className="t-h4 text-navy">
          {t("order.sellerOrders.title", { count: order.seller_orders.length })}
        </h2>
        <span className="text-sm text-tx2">{t("order.sellerOrders.hint")}</span>
      </div>
      <ul className="m-0 flex list-none flex-col divide-y divide-bd rounded-xl border border-bd bg-surface p-0">
        {order.seller_orders.map((group) => (
          <SellerOrderRow key={group.id} group={group} />
        ))}
      </ul>
    </section>
  );
}

function SellerOrderRow({ group }: { group: SellerOrder }) {
  const t = useTranslations("admin");
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-3">
      <span className="flex min-w-0 flex-[1_1_180px] flex-col">
        <b className="text-sm font-medium break-words">{group.store_name}</b>
        <span className="text-cap text-tx2">{t(`status.sellerOrder.${group.status}`)}</span>
      </span>
      <span className="flex flex-col text-right text-cap text-tx2 tabular-nums">
        <span>
          {t("order.sellerOrders.merchandise")} <b className="font-semibold text-tx">{formatMoney(group.merchandise_total)}</b>
        </span>
        <span>
          {t("order.sellerOrders.commission", { rate: (group.commission_rate_bps / 100).toString() })}{" "}
          <b className="font-semibold text-tx">{formatMoney(group.commission_amount)}</b>
        </span>
      </span>
    </li>
  );
}

function useStatusChange(order: StaffOrder) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: { status: OrderStatus; reason: string | null }) =>
      must(
        browserApi.PATCH("/api/v1/staff/orders/{order_id}/status", {
          params: { path: { order_id: order.id } },
          body,
        }),
      ),
    onSuccess: (_data, body) => {
      toast.show(t("order.statusChanged", { status: t(`status.order.${body.status}`) }));
      void client.invalidateQueries({ queryKey: ["admin"] });
    },
  });
}

function CancelOrder({ order }: { order: StaffOrder }) {
  const t = useTranslations("admin");
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const change = useStatusChange(order);
  const close = () => {
    setOpen(false);
    change.reset();
  };
  return (
    <>
      <Button variant="danger-outline" size="sm" onClick={() => setOpen(true)}>
        {t("order.cancel")}
      </Button>
      <Dialog
        open={open}
        onClose={close}
        title={t("order.cancelTitle", { number: order.order_number })}
        closeLabel={t("common.close")}
        footer={
          <>
            <Button variant="neutral" onClick={close}>
              {t("order.keep")}
            </Button>
            <Button
              variant="danger"
              disabled={change.isPending || reason.trim() === ""}
              onClick={() => change.mutate({ status: "cancelled", reason: reason.trim() }, { onSuccess: close })}
            >
              {t("order.cancelConfirm")}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <p className="text-tx2">{t("order.cancelBody")}</p>
          <Field label={t("order.cancelReason")}>
            {(control) => <Textarea {...control} rows={3} maxLength={500} required value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
          {change.error && (
            <p role="alert" className="text-sm text-err-tx">
              {change.error instanceof ApiError && change.error.status === 409 ? t("order.transitionConflict") : t("common.saveError")}
            </p>
          )}
        </div>
      </Dialog>
    </>
  );
}

function Items({ order }: { order: StaffOrder }) {
  const t = useTranslations("admin.order");
  return (
    <Card className="overflow-hidden">
      <h2 className="t-h3 border-b border-bd px-5 py-[18px]">{t("items")}</h2>
      <Table>
        <thead>
          <tr>
            <Th>{t("columns.product")}</Th>
            <Th>{t("columns.sku")}</Th>
            <Th>{t("columns.qty")}</Th>
            <Th>{t("columns.unit")}</Th>
            <Th className="text-right">{t("columns.total")}</Th>
          </tr>
        </thead>
        <tbody>
          {order.lines.map((line) => (
            <tr key={line.id}>
              <Td>
                <span className="flex items-center gap-2.5">
                  <Thumb image={line.image} size={44} />
                  <span className="flex min-w-0 flex-col">
                    <b className="font-medium">{line.product_name}</b>
                    {line.variant_name && <span className="text-cap text-tx2">{line.variant_name}</span>}
                    <span className="text-cap text-tx2">{t("soldBy", { store: line.store_name })}</span>
                  </span>
                </span>
              </Td>
              <Td className="whitespace-nowrap text-tx2">{line.sku}</Td>
              <Td>{line.quantity}</Td>
              <Td className="whitespace-nowrap">{formatMoney(line.unit_price)}</Td>
              <Td className="text-right font-semibold whitespace-nowrap">{formatMoney(line.line_total)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="ml-auto flex w-full max-w-[360px] flex-col gap-2 border-t border-bd px-5 py-4">
        <div className="kv">
          <span>{t("subtotal")}</span>
          <span>{formatMoney(order.subtotal)}</span>
        </div>
        <div className="kv">
          <span>{order.delivery_zone ? t("delivery", { zone: order.delivery_zone }) : t("deliveryNoZone")}</span>
          <span>{order.delivery_fee === 0 ? t("free") : formatMoney(order.delivery_fee)}</span>
        </div>
        {order.discount_total > 0 && (
          <div className="kv">
            <span>{order.discount_code ? t("discount", { code: order.discount_code }) : t("discountNoCode")}</span>
            <span className="text-ok-tx">− {formatMoney(order.discount_total)}</span>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-bd pt-1.5">
          <b className="font-semibold">{t("total")}</b>
          <b className="t-price">{formatMoney(order.total)}</b>
        </div>
        {order.tax_total > 0 && <span className="text-right text-cap text-tx2">{t("vat", { amount: formatMoney(order.tax_total) })}</span>}
      </div>
    </Card>
  );
}

function History({ order }: { order: StaffOrder }) {
  const t = useTranslations("admin");
  const entries = [...order.status_history].reverse();
  return (
    <Card padding={20} className="flex flex-col gap-3.5">
      <h2 className="t-h3">{t("order.history")}</h2>
      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {entries.map((entry, i) => (
          <li key={`${entry.status}-${entry.created_at}`} className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className={cx("inline-flex size-6 flex-none items-center justify-center rounded-full text-[11px] font-semibold text-white", i === 0 ? "bg-pri" : "bg-ok-tx")}
            >
              {i === 0 ? "●" : <Check size={13} />}
            </span>
            <span className="flex min-w-0 flex-col">
              <b className="text-sm font-semibold">{t(`status.order.${entry.status}`)}</b>
              <span className="text-cap text-tx2">{formatDate(entry.created_at, "dateTime")}</span>
              {entry.reason && <span className="text-sm break-words text-tx2">{entry.reason}</span>}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function PaymentCard({ order }: { order: StaffOrder }) {
  const t = useTranslations("admin");
  const { can } = useStaffAccess();
  const latest = order.payments.at(-1);
  return (
    <Card padding={20} className="flex flex-col gap-1.5">
      <h2 className="t-h4">{t("order.payment")}</h2>
      {!latest ? (
        <span className="text-sm text-tx2">{t("order.noPayment")}</span>
      ) : (
        <>
          <div className="kv">
            <span>{t("order.method")}</span>
            <span>{t(`status.method.${latest.method}`)}</span>
          </div>
          <div className="kv">
            <span>{t("order.status")}</span>
            <PaymentStatusBadge status={latest.status} method={latest.method} />
          </div>
          {latest.provider && (
            <div className="kv">
              <span>{t("order.provider")}</span>
              <span>{latest.provider}</span>
            </div>
          )}
          {latest.succeeded_at && (
            <div className="kv">
              <span>{t("order.paidAt")}</span>
              <span>{formatDate(latest.succeeded_at, "dateTime")}</span>
            </div>
          )}
          <div className="kv">
            <span>{t("order.amount")}</span>
            <b className="font-semibold">{formatMoney(latest.amount)}</b>
          </div>
          {order.payments.length > 1 && <span className="text-cap text-tx2">{t("order.attempts", { count: order.payments.length })}</span>}
        </>
      )}
      {can("payments:read") && (
        <NextLink href="/admin/payments" className="pt-1 text-sm font-medium">
          {t("order.viewPayments")}
        </NextLink>
      )}
    </Card>
  );
}

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-80" />
      <Skeleton className="h-24 w-full" />
      <div className="flex flex-wrap gap-5">
        <Skeleton className="h-80 min-w-0 flex-[999_1_520px]" />
        <Skeleton className="h-80 min-w-0 flex-[1_1_300px]" />
      </div>
    </div>
  );
}

/** The path an order normally follows; cancelled is set aside from it. */
const ORDER_PATH = ["received", "confirmed", "processing", "dispatched", "delivered"] as const satisfies readonly OrderStatus[];

/** The order in the Orders drawer (layout owner 2026-11-18): the same data, actions and permission
 * checks as the full page, laid out like the Service requests drawer. */
export function OrderPanel({ orderId, now }: { orderId: string; now: number }) {
  const { can } = useStaffAccess();
  const query = useQuery({
    queryKey: ["admin", "order", orderId],
    queryFn: () => must(browserApi.GET("/api/v1/staff/orders/{order_id}", { params: { path: { order_id: orderId } } })),
    retry: (count, error) => !(error instanceof ApiError && (error.status === 404 || error.status === 422)) && count < 2,
  });
  if (query.isError) return <LoadError onRetry={() => query.refetch()} className="m-5" />;
  if (!query.data)
    return (
      <div className="flex flex-col gap-4 p-5" aria-busy="true">
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-60 w-full" />
      </div>
    );
  return <OrderPanelBody order={query.data} fulfil={can("orders:fulfil")} payments={can("payments:read")} now={now} />;
}

function OrderPanelBody({ order, fulfil, payments, now }: { order: StaffOrder; fulfil: boolean; payments: boolean; now: number }) {
  const t = useTranslations("admin");
  const canCancel = staffCanCancel(order.status);
  const paid = order.payment?.status === "succeeded";
  const docBase = `/api/backend/api/v1/staff/orders/${order.id}`;
  const latest = order.payments.at(-1);
  const cancelled = order.status === "cancelled" ? [...order.status_history].reverse().find((e) => e.status === "cancelled") : undefined;
  const landmark = typeof order.delivery_address.delivery_instructions === "string" ? order.delivery_address.delivery_instructions : "";
  const units = order.lines.reduce((n, l) => n + l.quantity, 0);

  return (
    <div className="flex flex-col gap-5 p-5">
      <DrawerHeader
        name={order.recipient_name}
        badges={
          <>
            <OrderStatusBadge status={order.status} />
            {order.payment && <PaymentStatusBadge status={order.payment.status} method={order.payment.method} />}
            <CopyChip value={order.order_number} label={t("inbox.copyValue", { value: order.order_number })} />
          </>
        }
        meta={`${t("inbox.placedAgo", { ago: timeAgo(order.created_at, now), date: formatDate(order.created_at, "dateTime") })} · ${order.user_id ? t("order.account") : t("order.guest")}`}
        phone={order.recipient_phone}
        phoneText={formatPhone(order.recipient_phone)}
        whatsapp={whatsappLink(order.recipient_phone)}
        email={order.customer_email}
      />

      {/* Documents and the full page */}
      <div className="flex flex-wrap gap-2">
        <a href={`${docBase}/delivery-note`} className={buttonClasses({ variant: "neutral", size: "sm", className: "gap-2" })}>
          <Printer size={16} aria-hidden="true" />
          {t("order.deliveryNote")}
        </a>
        {paid && (
          <a href={`${docBase}/invoice`} className={buttonClasses({ variant: "neutral", size: "sm", className: "gap-2" })}>
            <Download size={16} aria-hidden="true" />
            {t("order.invoice")}
          </a>
        )}
        <NextLink href={`/admin/orders/${order.id}`} className={buttonClasses({ variant: "ghost", size: "sm", className: "gap-2" })}>
          <ExternalLink size={16} aria-hidden="true" />
          {t("inbox.fullPage")}
        </NextLink>
      </div>

      {/* Progress and the allowed next steps (the backend checks every change again) */}
      <DrawerSection title={t("inbox.progress")}>
        {order.status === "cancelled" ? (
          <div className="flex flex-col gap-1 rounded-xl bg-err-bg/60 px-4 py-3">
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-err-tx">
              <XCircle size={16} aria-hidden="true" />
              {t("order.done", { status: t("status.order.cancelled").toLowerCase() })}
            </span>
            {cancelled?.reason && <span className="text-sm break-words text-tx2">{cancelled.reason}</span>}
          </div>
        ) : (
          <Stepper
            label={t("inbox.progress")}
            steps={ORDER_PATH.map((s) => ({ key: s, label: t(`status.order.${s}`) }))}
            at={ORDER_PATH.indexOf(order.status as (typeof ORDER_PATH)[number])}
            finished={order.status === "delivered"}
          />
        )}
        {fulfil && canCancel && (
          <div className="flex flex-wrap items-center gap-2">
            <CancelOrder order={order} />
          </div>
        )}
        {order.seller_orders.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-cap font-semibold text-tx2">{t("order.sellerOrders.title", { count: order.seller_orders.length })}</span>
            <ul className="m-0 flex list-none flex-col divide-y divide-bd rounded-xl border border-bd p-0">
              {order.seller_orders.map((group) => (
                <SellerOrderRow key={group.id} group={group} />
              ))}
            </ul>
            <span className="text-cap text-tx2">{t("order.sellerOrders.hint")}</span>
          </div>
        )}
      </DrawerSection>

      {/* What was ordered */}
      <DrawerSection title={t("order.items")} aside={<span className="text-cap font-semibold text-tx2">{t("orders.items", { count: units })}</span>}>
        <ul className="m-0 flex list-none flex-col divide-y divide-bd rounded-xl border border-bd p-0">
          {order.lines.map((line) => (
            <li key={line.id} className="flex items-center gap-3 px-3 py-2.5">
              <Thumb image={line.image} size={44} />
              <span className="flex min-w-0 flex-1 flex-col">
                <b className="text-sm font-medium break-words">{line.product_name}</b>
                {line.variant_name && <span className="text-cap text-tx2">{line.variant_name}</span>}
                <span className="text-cap text-tx2">{t("order.soldBy", { store: line.store_name })}</span>
                <span className="text-cap text-tx2">
                  <span className="font-mono">{line.sku}</span> · {line.quantity} × {formatMoney(line.unit_price)}
                </span>
              </span>
              <b className="flex-none text-sm font-semibold whitespace-nowrap tabular-nums">{formatMoney(line.line_total)}</b>
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-2 rounded-xl bg-page px-4 py-3">
          <div className="kv">
            <span>{t("order.subtotal")}</span>
            <span>{formatMoney(order.subtotal)}</span>
          </div>
          <div className="kv">
            <span>{order.delivery_zone ? t("order.delivery", { zone: order.delivery_zone }) : t("order.deliveryNoZone")}</span>
            <span>{order.delivery_fee === 0 ? t("order.free") : formatMoney(order.delivery_fee)}</span>
          </div>
          {order.discount_total > 0 && (
            <div className="kv">
              <span>{order.discount_code ? t("order.discount", { code: order.discount_code }) : t("order.discountNoCode")}</span>
              <span className="text-ok-tx">− {formatMoney(order.discount_total)}</span>
            </div>
          )}
          <div className="flex items-center justify-between border-t border-bd pt-2">
            <b className="font-semibold">{t("order.total")}</b>
            <b className="t-price">{formatMoney(order.total)}</b>
          </div>
          {order.tax_total > 0 && <span className="text-right text-cap text-tx2">{t("order.vat", { amount: formatMoney(order.tax_total) })}</span>}
        </div>
      </DrawerSection>

      {/* Who and where */}
      <DrawerSection title={t("inbox.customerDelivery")}>
        <dl className={FACTS}>
          <Fact Icon={UserRound} label={t("order.customer")}>
            {order.recipient_name}
            <span className="block text-cap font-normal text-tx2">{order.user_id ? t("order.account") : t("order.guest")}</span>
          </Fact>
          <Fact Icon={Phone} label={t("inbox.phone")}>
            {formatPhone(order.recipient_phone)}
          </Fact>
          {order.customer_email && (
            <Fact Icon={Mail} label={t("inbox.email")} wide>
              <span className="break-all">{order.customer_email}</span>
            </Fact>
          )}
          <Fact Icon={MapPin} label={t("order.deliveryTitle")} wide>
            {addressLine(order.delivery_address, ADDRESS_PARTS)}
            {landmark && <span className="block text-cap font-normal text-tx2">{t("order.landmark", { text: landmark })}</span>}
          </Fact>
          {order.delivery_zone && (
            <Fact Icon={Truck} label={t("inbox.zone")}>
              {order.delivery_zone}
            </Fact>
          )}
          {order.customer_note && (
            <Fact Icon={MessageSquareText} label={t("inbox.customerNote")} wide>
              <span className="whitespace-pre-line">{order.customer_note}</span>
            </Fact>
          )}
        </dl>
      </DrawerSection>

      {/* Payment */}
      <DrawerSection
        title={t("order.payment")}
        aside={
          payments ? (
            <NextLink href="/admin/payments" className="text-cap font-medium">
              {t("order.viewPayments")}
            </NextLink>
          ) : undefined
        }
      >
        {!latest ? (
          <p className="m-0 rounded-xl bg-page px-4 py-3 text-sm text-tx2">{t("order.noPayment")}</p>
        ) : (
          <div className="flex flex-col gap-2 rounded-xl border border-bd px-4 py-3">
            <div className="kv">
              <span>{t("order.method")}</span>
              <span>{t(`status.method.${latest.method}`)}</span>
            </div>
            <div className="kv">
              <span>{t("order.status")}</span>
              <PaymentStatusBadge status={latest.status} method={latest.method} />
            </div>
            {latest.provider && (
              <div className="kv">
                <span>{t("order.provider")}</span>
                <span>{latest.provider}</span>
              </div>
            )}
            {latest.succeeded_at && (
              <div className="kv">
                <span>{t("order.paidAt")}</span>
                <span>{formatDate(latest.succeeded_at, "dateTime")}</span>
              </div>
            )}
            <div className="kv">
              <span>{t("order.amount")}</span>
              <b className="font-semibold">{formatMoney(latest.amount)}</b>
            </div>
            {order.payments.length > 1 && <span className="text-cap text-tx2">{t("order.attempts", { count: order.payments.length })}</span>}
          </div>
        )}
      </DrawerSection>

      {/* Status history, newest first */}
      <DrawerSection title={t("order.history")}>
        <Timeline>
          {[...order.status_history].reverse().map((entry) => (
            <TimelineItem
              key={`${entry.status}-${entry.created_at}`}
              Icon={entry.status === "cancelled" ? XCircle : entry.status === "received" ? Check : HistoryIcon}
              label={t(`status.order.${entry.status}`)}
              at={entry.created_at}
              note={entry.reason}
            />
          ))}
        </Timeline>
      </DrawerSection>
    </div>
  );
}
