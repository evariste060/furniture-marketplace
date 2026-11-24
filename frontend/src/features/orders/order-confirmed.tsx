"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, Download, Truck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { PhoneForm } from "@/features/checkout/payment-status";
import { firstName, useSession } from "@/features/session/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { localPhone, orderAccess, rememberOrder } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";

type Order = components["schemas"]["OrderDetailResponse"];
type Proof = { phone: string } | { customer: true };

/** /order/[number]/confirmed (OrderConfirmed.dc.html). A guest's order is read with its phone
 * (kept for this tab at checkout, or typed again); a customer's from their order history. */
export function OrderConfirmedView({ orderNumber }: { orderNumber: string }) {
  const { data: user, isPending } = useSession();
  const [phone, setPhone] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    // sessionStorage exists only in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPhone(orderAccess(orderNumber)?.phone ?? null);
    setChecked(true);
  }, [orderNumber]);

  if (!checked || isPending) return <ConfirmedSkeleton />;
  const proof: Proof | null = phone ? { phone } : user?.is_customer ? { customer: true } : null;
  if (!proof) return <Gate orderNumber={orderNumber} onPhone={(p) => (rememberOrder({ number: orderNumber, phone: p }), setPhone(p))} />;
  return <Confirmed orderNumber={orderNumber} proof={proof} signedIn={Boolean(user?.is_customer)} onDenied={() => setPhone(null)} />;
}

function Gate({ orderNumber, onPhone }: { orderNumber: string; onPhone: (phone: string) => void }) {
  const t = useTranslations("store.payment");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const local = localPhone(phone);
    if (!local) setError(t("phoneInvalid"));
    else onPhone(`0${local}`);
  }
  return (
    <div className="flex justify-center">
      <PhoneForm orderNumber={orderNumber} phone={phone} setPhone={setPhone} error={error} onSubmit={onSubmit} label={t("phoneGateTitle")} text={t("phoneGateText")} />
    </div>
  );
}

async function readOrder(orderNumber: string, proof: Proof): Promise<Order> {
  if ("phone" in proof) {
    const { data, error, response } = await browserApi.POST("/api/v1/orders/lookup", { body: { order_number: orderNumber, phone: proof.phone } });
    if (!data) throw ApiError.from(response.status, error);
    return data;
  }
  const { data, error, response } = await browserApi.GET("/api/v1/customers/me/orders/number/{order_number}", {
    params: { path: { order_number: orderNumber } },
  });
  if (!data) throw ApiError.from(response.status, error);
  return data;
}

function ConfirmedSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-6">
      <Card padding={32} className="flex flex-col items-center gap-3.5">
        <Skeleton className="size-20 rounded-full" />
        <Skeleton className="h-9 w-3/4" />
        <Skeleton className="h-5 w-1/2" />
      </Card>
      <Card padding={24}>
        <Skeleton className="h-40 w-full" />
      </Card>
    </div>
  );
}

function Confirmed({ orderNumber, proof, signedIn, onDenied }: { orderNumber: string; proof: Proof; signedIn: boolean; onDenied: () => void }) {
  const t = useTranslations("store.order");
  const router = useRouter();
  const query = useQuery({
    queryKey: ["order", orderNumber, "phone" in proof ? proof.phone : "me"],
    queryFn: () => readOrder(orderNumber, proof),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });
  const order = query.data;
  const payment = order?.payment;
  const unpaid = payment && payment.method !== "cash_on_delivery" && payment.status !== "succeeded";
  useEffect(() => {
    // A mobile money order is confirmed once paid: until then, the payment page.
    if (unpaid && order.status !== "cancelled") router.replace(`/checkout/pay/${orderNumber}`);
  }, [unpaid, order, orderNumber, router]);
  const denied = query.error instanceof ApiError && query.error.status === 404;
  useEffect(() => {
    if (denied && "phone" in proof) onDenied();
  }, [denied, proof, onDenied]);

  if (query.isPending || (unpaid && order?.status !== "cancelled")) return <ConfirmedSkeleton />;
  if (query.isError || !order)
    return (
      <Card padding={32} role="alert" className="flex flex-col items-center gap-4 text-center">
        <h1 className="t-h2">{t(denied ? "notFoundTitle" : "loadFailedTitle")}</h1>
        <p className="text-tx2">{t(denied ? "notFoundText" : "loadFailedText")}</p>
        {denied ? (
          <Link href="/" className={buttonClasses()}>
            {t("continueShopping")}
          </Link>
        ) : (
          <Button onClick={() => query.refetch()}>{t("retry")}</Button>
        )}
      </Card>
    );

  if (order.status === "cancelled")
    return (
      <Card padding={32} role="alert" className="flex flex-col items-center gap-4 text-center">
        <h1 className="t-h2">{t("cancelledTitle")}</h1>
        <p className="text-tx2">{t("cancelledText", { number: order.order_number })}</p>
        <Link href="/" className={buttonClasses()}>
          {t("continueShopping")}
        </Link>
      </Card>
    );
  const cash = payment?.method === "cash_on_delivery";
  const paid = payment?.status === "succeeded";
  const name = firstName(order.recipient_name) ?? order.recipient_name;
  const method = payment ? t(`method.${payment.method === "card" ? "mtn_momo" : payment.method}`) : "";
  const address = order.delivery_address as { sector?: string | null; district?: string | null };
  const where = [address.sector, address.district].filter(Boolean).join(", ");
  const strong = (chunks: ReactNode) => <b className="font-bold text-tx">{chunks}</b>;

  return (
    <>
      <section className="flex flex-col items-center gap-3.5 rounded-xl border border-bd bg-card p-8 text-center max-sm:p-5">
        <span className="flex size-20 items-center justify-center rounded-full bg-ok-bg text-ok">
          <CircleCheck size={40} aria-hidden="true" />
        </span>
        <h1 className="t-h1">{t(cash ? "titleCash" : "title", { name })}</h1>
        <p className="text-lg text-tx2">
          {t.rich(cash ? "lineCash" : "linePaid", { number: order.order_number, method, amount: formatMoney(order.total), b: strong })}
        </p>
        <div className="flex flex-wrap justify-center gap-3 pt-1">
          <Link href={`/track?order=${encodeURIComponent(order.order_number)}`} className={buttonClasses()}>
            <Truck size={18} aria-hidden="true" />
            {t("track")}
          </Link>
          {signedIn && paid && (
            <a href={`/api/backend/api/v1/customers/me/orders/${order.id}/invoice`} className={buttonClasses({ variant: "outline" })}>
              <Download size={18} aria-hidden="true" />
              {t("invoice")}
            </a>
          )}
          <Link href="/" className={buttonClasses({ variant: "ghost" })}>
            {t("continueShopping")}
          </Link>
        </div>
      </section>
      <div className="flex flex-wrap items-start gap-6">
        <section aria-labelledby="order-details" className="flex min-w-0 flex-[999_1_460px] flex-col rounded-xl border border-bd bg-card p-6 max-sm:p-4">
          <h2 id="order-details" className="t-h3 pb-2">
            {t("details")}
          </h2>
          {order.lines.map((line) => (
            <div key={line.sku} className="flex items-center gap-3.5 border-b border-bd py-3.5">
              <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-16" iconSize={24} />
              <span className="flex min-w-0 flex-1 flex-col">
                <b className="text-sm font-semibold">{line.product_name}</b>
                <span className="text-cap text-mut">{t("soldBy", { store: line.store_name })}</span>
                <span className="text-cap text-mut">
                  {line.variant_name ? `${line.variant_name} · ` : ""}
                  {t("qty", { count: line.quantity })}
                </span>
              </span>
              <b className="text-sm font-semibold">{formatMoney(line.line_subtotal)}</b>
            </div>
          ))}
          <div className="flex flex-col gap-2 pt-3.5">
            <div className="kv">
              <span>{t("subtotal")}</span>
              <span>{formatMoney(order.subtotal)}</span>
            </div>
            <div className="kv">
              <span>{t("delivery")}</span>
              {order.delivery_fee === 0 ? <span className="font-medium text-ok-tx">{t("free")}</span> : <span>{formatMoney(order.delivery_fee)}</span>}
            </div>
            {order.discount_total > 0 && (
              <div className="kv">
                <span>{t("discount", { code: order.discount_code ?? "" })}</span>
                <span className="font-medium text-ok-tx">− {formatMoney(order.discount_total)}</span>
              </div>
            )}
            {order.tax_total > 0 && (
              <div className="kv">
                <span>{t("vat")}</span>
                <span className="text-mut">{formatMoney(order.tax_total)}</span>
              </div>
            )}
            <div className="flex items-center justify-between pt-1.5">
              <b className="t-h4">{t(paid ? "totalPaid" : "totalToPay")}</b>
              <b className="t-price text-head">{formatMoney(order.total)}</b>
            </div>
            <span>
              <Badge tone={paid ? "soft-ok" : "soft-warn"}>{t(paid ? "paid" : "payOnDelivery")}</Badge>
            </span>
          </div>
        </section>
        <aside className="flex w-full flex-[1_1_300px] flex-col gap-4">
          <Card padding={24} className="flex flex-col gap-3 max-sm:p-4">
            <h2 className="t-h4">{t("next")}</h2>
            <NextStep state="done" mark="✓">
              {t(paid ? "nextPaid" : "nextReceived")}
            </NextStep>
            <NextStep state="now" mark="2">
              {t("nextPack")}
            </NextStep>
            <NextStep state="todo" mark="3">
              {t(cash ? "nextRiderCash" : "nextRider", { place: where || t("yourAddress") })}
            </NextStep>
          </Card>
          {!signedIn && <CreateAccount name={order.recipient_name} phone={order.recipient_phone} />}
        </aside>
      </div>
    </>
  );
}

function NextStep({ state, mark, children }: { state: "done" | "now" | "todo"; mark: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <span
        aria-hidden="true"
        className={cx(
          "inline-flex size-6 flex-none items-center justify-center rounded-full text-xs font-semibold",
          state === "done" && "bg-ok-tx text-white",
          state === "now" && "bg-pri text-white",
          state === "todo" && "border border-bd2 bg-card text-mut",
        )}
      >
        {mark}
      </span>
      <span className={cx("text-sm", state === "todo" && "text-tx2")}>{children}</span>
    </div>
  );
}

/** "Save your details — create an account": the registration page with the name and phone filled
 * in (owner decision 2026-10-27). This order stays a guest order. */
function CreateAccount({ name, phone }: { name: string; phone: string }) {
  const t = useTranslations("store.order");
  const href = `/register?${new URLSearchParams({ name, phone: `0${localPhone(phone) ?? ""}` })}`;
  return (
    <Card padding={24} className="flex flex-col gap-3 border-light! bg-light! max-sm:p-4">
      <h2 className="t-h4 text-head">{t("accountTitle")}</h2>
      <p className="text-sm text-tx2">{t("accountText")}</p>
      <Link href={href} className={buttonClasses({ block: true })}>
        {t("createAccount")}
      </Link>
    </Card>
  );
}
