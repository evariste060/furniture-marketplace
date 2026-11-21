"use client";

import { ArrowLeft, ArrowRight, Check, ChevronRight, Download, Star } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Pagination } from "@/components/ui/pagination";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useProfile, useSavedAddresses } from "@/features/checkout/use-checkout";
import { addressLine, ProgressRow, StatusBadge } from "@/features/orders/order-parts";
import { firstName, useSession } from "@/features/session/use-session";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { getPathname, Link, useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api/errors";
import { formatDate, formatMoney, formatPhone } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import { statusTime } from "@/lib/order-progress";
import { ORDERS_PAGE_SIZE, useOrder, useOrders, useReviewLink, type OrderDetail, type OrderSummary } from "./use-account";

/** Account.dc.html, MyOrders.dc.html and OrderDetail.dc.html. */

function LoadFailed({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("store.account");
  return (
    <Card padding={24} role="alert" className="flex flex-col items-start gap-3">
      <p className="text-tx2">{t("loadFailed")}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {t("retry")}
      </Button>
    </Card>
  );
}

function NoOrders() {
  const t = useTranslations("store.account");
  return (
    <div className="flex flex-col items-start gap-3 border-t border-bd py-5">
      <p className="text-tx2">{t("noOrders")}</p>
      <Link href="/" className={buttonClasses({ size: "sm" })}>
        {t("startShopping")}
      </Link>
    </div>
  );
}

function OrderRow({ order }: { order: OrderSummary }) {
  const t = useTranslations("store.account");
  return (
    <Link
      href={`/account/orders/${order.order_number}`}
      className="flex flex-wrap items-center gap-4 border-t border-bd py-4 text-tx no-underline hover:text-tx max-sm:gap-x-3 max-sm:gap-y-1.5"
    >
      <span className="flex min-w-40 flex-1 flex-col gap-0.5">
        <b className="font-semibold">#{order.order_number}</b>
        <span className="text-sm text-tx2">
          {formatDate(order.created_at)} · {t("items", { count: order.item_count })}
        </span>
      </span>
      <StatusBadge status={order.status} />
      <b className="w-[130px] text-right font-semibold max-sm:w-auto">{formatMoney(order.total)}</b>
      <ChevronRight size={18} aria-hidden="true" className="text-tx2" />
    </Link>
  );
}

// ---- Account.dc.html ---------------------------------------------------------------------------

export function AccountOverview() {
  const t = useTranslations("store.account");
  const { data: user } = useSession();
  const orders = useOrders(1, 3);
  const profile = useProfile(true);
  const addresses = useSavedAddresses(true);
  const preferred = addresses.data?.find((a) => a.is_default) ?? addresses.data?.[0];
  return (
    <>
      <div className="flex flex-col gap-1">
        <h1 className="t-h1 text-navy">{t("hello", { name: firstName(user?.full_name) ?? "" })}</h1>
        <p className="text-tx2">{t("overviewText")}</p>
      </div>
      <Card padding={24} className="flex flex-col gap-1 max-sm:p-4">
        <div className="flex items-center justify-between pb-2">
          <h2 className="t-h3">{t("recentOrders")}</h2>
          <Link href="/account/orders" className="flex items-center gap-1.5 text-sm font-medium">
            {t("seeAll")}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        {orders.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : orders.isError ? (
          <LoadFailed onRetry={() => orders.refetch()} />
        ) : orders.data.items.length === 0 ? (
          <NoOrders />
        ) : (
          orders.data.items.map((o) => <OrderRow key={o.id} order={o} />)
        )}
      </Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card padding={24} className="flex flex-col gap-2 max-sm:p-4">
          <div className="flex items-center justify-between">
            <h2 className="t-h4">{t("defaultAddress")}</h2>
            <Link href="/account/addresses" className="text-sm font-medium">
              {t("manage")}
            </Link>
          </div>
          {addresses.isPending ? (
            <Skeleton className="h-5 w-3/4" />
          ) : (
            <p className="text-sm text-tx2">
              {preferred
                ? [preferred.label, [preferred.street_address, preferred.sector, preferred.district].filter(Boolean).join(", ")].filter(Boolean).join(" · ")
                : t("noAddress")}
            </p>
          )}
        </Card>
        <Card padding={24} className="flex flex-col gap-2 max-sm:p-4">
          <div className="flex items-center justify-between">
            <h2 className="t-h4">{t("profileCard")}</h2>
            <Link href="/account/profile" className="text-sm font-medium">
              {t("edit")}
            </Link>
          </div>
          {profile.isPending ? (
            <Skeleton className="h-5 w-3/4" />
          ) : (
            <p className="text-sm text-tx2">{[profile.data?.email, profile.data?.phone && formatPhone(profile.data.phone)].filter(Boolean).join(" · ")}</p>
          )}
        </Card>
      </div>
    </>
  );
}

// ---- MyOrders.dc.html --------------------------------------------------------------------------

export function OrdersView() {
  const t = useTranslations("store.account");
  const tl = useTranslations("ui");
  const locale = useLocale();
  const params = useSearchParams();
  const page = Math.max(1, Math.min(10_000, Number.parseInt(params.get("page") ?? "1", 10) || 1));
  const orders = useOrders(page);
  return (
    <>
      <h1 className="t-h1 text-navy">{t("ordersTitle")}</h1>
      {orders.isPending ? (
        [0, 1, 2].map((i) => <Skeleton key={i} className="h-[132px] w-full rounded-xl" />)
      ) : orders.isError ? (
        <LoadFailed onRetry={() => orders.refetch()} />
      ) : orders.data.items.length === 0 ? (
        <Card padding={24}>
          <NoOrders />
        </Card>
      ) : (
        <>
          {orders.data.items.map((o) => (
            <article key={o.id} className="flex flex-col gap-3.5 rounded-xl border border-bd bg-white p-5 max-sm:p-4">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-base font-semibold">{t("orderNumber", { number: o.order_number })}</h2>
                <StatusBadge status={o.status} />
                <span className="flex-1" />
                <span className="text-sm text-tx2">{formatDate(o.created_at)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <span className="flex min-w-40 flex-1 flex-col gap-0.5">
                  <span className="text-sm text-tx2">{t("items", { count: o.item_count })}</span>
                  <b className="font-semibold">{formatMoney(o.total)}</b>
                </span>
                <Link href={`/account/orders/${o.order_number}`} className={buttonClasses({ variant: "outline", size: "sm" })}>
                  {t("viewDetails")}
                  <ChevronRight size={14} aria-hidden="true" />
                </Link>
              </div>
            </article>
          ))}
          <Pagination
            total={orders.data.total}
            page={page}
            size={ORDERS_PAGE_SIZE}
            hrefFor={(n) => getPathname({ href: { pathname: "/account/orders", query: n > 1 ? { page: String(n) } : {} }, locale })}
            labels={{ nav: tl("pagination"), previous: tl("previous"), next: tl("next"), page: (n) => tl("page", { n }) }}
          />
        </>
      )}
    </>
  );
}

// ---- OrderDetail.dc.html -----------------------------------------------------------------------

export function OrderDetailView({ number }: { number: string }) {
  const t = useTranslations("store.account");
  const query = useOrder(number);
  const order = query.data;
  const back = (
    <Link href="/account/orders" className="flex items-center gap-1.5 self-start text-sm font-medium">
      <ArrowLeft size={16} aria-hidden="true" />
      {t("allOrders")}
    </Link>
  );
  if (query.isPending)
    return (
      <>
        {back}
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
      </>
    );
  if (query.isError || !order) {
    const missing = query.error instanceof ApiError && query.error.status === 404;
    return (
      <>
        {back}
        {missing ? (
          <Card padding={24} role="alert" className="flex flex-col gap-2">
            <h1 className="t-h2">{t("orderNotFound")}</h1>
            <p className="text-tx2">{t("orderNotFoundText")}</p>
          </Card>
        ) : (
          <LoadFailed onRetry={() => query.refetch()} />
        )}
      </>
    );
  }
  const delivered = statusTime(order, "delivered");
  const cancelled = order.status === "cancelled" ? statusTime(order, "cancelled") : null;
  return (
    <>
      {back}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="t-h1 text-navy">{t("orderNumber", { number: order.order_number })}</h1>
            <StatusBadge status={order.status} />
          </div>
          <span className="text-sm text-tx2">
            {t("placedOn", { date: formatDate(order.created_at) })}
            {delivered && ` · ${t("deliveredOn", { date: formatDate(delivered) })}`}
            {cancelled && ` · ${t("cancelledOn", { date: formatDate(cancelled) })}`}
          </span>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {order.payment?.status === "succeeded" && (
            <a href={`/api/backend/api/v1/customers/me/orders/${order.id}/invoice`} className={buttonClasses({ variant: "outline", size: "sm" })}>
              <Download size={16} aria-hidden="true" />
              {t("invoice")}
            </a>
          )}
          <WhatsAppLink label={t("help")} message={t("helpMessage", { number: order.order_number })} size="sm" iconSize={16} />
        </div>
      </div>
      {order.status === "cancelled" ? (
        <div role="status" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("cancelledNote")}
        </div>
      ) : (
        <section aria-label={t("progressLabel")} className="rounded-xl border border-bd bg-white p-6 max-sm:p-4">
          <ProgressRow order={order} />
        </section>
      )}
      <OrderItems order={order} />
      <OrderFacts order={order} />
    </>
  );
}

function OrderItems({ order }: { order: OrderDetail }) {
  const t = useTranslations("store.account");
  const to = useTranslations("store.order");
  const router = useRouter();
  const toast = useToast();
  const link = useReviewLink();
  const canReview = order.status === "delivered";

  function review(itemId: string) {
    link.mutate(
      { orderId: order.id, itemId },
      {
        onSuccess: (data) => router.push(`/review/${data.token}`),
        onError: (error) => {
          const code = error instanceof ApiError ? error.code : "";
          const known = ["already_reviewed", "review_link_expired", "product_unavailable", "not_delivered"].includes(code);
          toast.show(t(known ? `reviewError.${code}` : "reviewError.other"), "error");
        },
      },
    );
  }

  return (
    <section aria-labelledby="order-items" className="flex flex-col rounded-xl border border-bd bg-white p-6 max-sm:p-4">
      <h2 id="order-items" className="t-h3 pb-2">
        {t("itemsTitle")}
      </h2>
      {order.lines.map((line) => {
        const href = line.product_slug ? `/product/${line.product_slug}` : null;
        return (
          <div key={line.id} className="flex flex-wrap items-center gap-4 border-t border-bd py-4">
            {href ? (
              <Link href={href} aria-label={line.product_name} className="flex-none">
                <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-[72px]" iconSize={28} />
              </Link>
            ) : (
              <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-[72px] flex-none" iconSize={28} />
            )}
            <span className="flex min-w-[180px] flex-1 flex-col gap-0.5">
              {href ? (
                <Link href={href} className="font-semibold text-tx">
                  {line.product_name}
                </Link>
              ) : (
                <b className="font-semibold">{line.product_name}</b>
              )}
              <span className="text-sm text-tx2">
                {line.variant_name ? `${line.variant_name} · ` : ""}
                {to("qty", { count: line.quantity })}
              </span>
            </span>
            <b className="font-semibold">{formatMoney(line.line_total)}</b>
            {canReview &&
              (line.reviewed ? (
                <Badge tone="soft-ok" className="px-3 py-2">
                  <Check size={14} aria-hidden="true" />
                  {t("reviewed")}
                </Badge>
              ) : line.product_slug ? (
                <Button variant="secondary" size="sm" disabled={link.isPending} onClick={() => review(line.id)}>
                  <Star size={14} aria-hidden="true" />
                  {t("writeReview")}
                </Button>
              ) : null)}
          </div>
        );
      })}
    </section>
  );
}

function OrderFacts({ order }: { order: OrderDetail }) {
  const t = useTranslations("store.account");
  const to = useTranslations("store.order");
  const payment = order.payment;
  const paid = payment?.status === "succeeded";
  const cash = payment?.method === "cash_on_delivery";
  const method = payment ? to(`method.${payment.method === "card" ? "mtn_momo" : payment.method}`) : null;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card padding={20} className="flex flex-col gap-1.5">
        <h2 className="text-sm font-semibold">{t("payment")}</h2>
        {method && <span className="text-sm text-tx2">{method}</span>}
        <span>
          <Badge tone={paid ? "soft-ok" : order.status === "cancelled" ? "soft-neutral" : "soft-warn"}>
            {paid ? to("paid") : order.status === "cancelled" ? t("notPaid") : cash ? to("payOnDelivery") : t("notPaid")}
          </Badge>
        </span>
      </Card>
      <Card padding={20} className="flex flex-col gap-1.5">
        <h2 className="text-sm font-semibold">{t(order.status === "delivered" ? "deliveredTo" : "deliverTo")}</h2>
        <span className="text-sm text-tx2">
          {order.recipient_name} · {formatPhone(order.recipient_phone)}
        </span>
        <span className="text-sm text-tx2">{addressLine(order.delivery_address)}</span>
      </Card>
      <Card padding={20} className="flex flex-col gap-1.5">
        <h2 className="text-sm font-semibold">{t("totals")}</h2>
        <div className="kv">
          <span>{to("subtotal")}</span>
          <span>{formatMoney(order.subtotal)}</span>
        </div>
        {order.discount_total > 0 && (
          <div className="kv">
            <span>{to("discount", { code: order.discount_code ?? "" })}</span>
            <span className="text-ok-tx">− {formatMoney(order.discount_total)}</span>
          </div>
        )}
        <div className="kv">
          <span>{to("delivery")}</span>
          {order.delivery_fee === 0 ? <span className="text-ok-tx">{to("free")}</span> : <span>{formatMoney(order.delivery_fee)}</span>}
        </div>
        <div className="kv">
          <b className="font-semibold text-tx">{t("total")}</b>
          <b className="font-semibold">{formatMoney(order.total)}</b>
        </div>
      </Card>
    </div>
  );
}
