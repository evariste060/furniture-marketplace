"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Clock, RefreshCw, Smartphone } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, PhoneInput, RadioOption } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { useSession } from "@/features/session/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import {
  MOBILE_MONEY,
  countdown,
  localPhone,
  orderAccess,
  rememberOrder,
  secondsLeft,
  type OrderAccess,
  type PaymentMethod,
} from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { formatMoney, formatPhone } from "@/lib/format";
import { CheckoutHeader } from "./checkout-header";
import { PaymentMark } from "./payment-mark";

type Status = components["schemas"]["PaymentStatusResponse"];
const POLL_MS = 3000;
const CLOSED = ["failed", "cancelled", "expired"] as const;

/** Who may read this order's payment: its owner (signed in) or anyone with the order's phone. */
type Access = { phone: string | null };

/** /checkout/pay/[orderNumber]: PaymentWaiting.dc.html while the customer approves the request
 * on their phone, PaymentFailed.dc.html when it was not approved. The page reads the status every
 * few seconds; the provider's signed notice to the backend is what marks it paid. */
export function PaymentStatusView({ orderNumber }: { orderNumber: string }) {
  const { data: user, isPending } = useSession();
  const [access, setAccess] = useState<Access | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    const stored = orderAccess(orderNumber);
    // sessionStorage is read after mount (it does not exist on the server).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (stored) setAccess({ phone: stored.phone });
    setChecked(true);
  }, [orderNumber]);

  if (!checked || isPending) return <Shell><WaitingSkeleton /></Shell>;
  const effective = access ?? (user?.is_customer ? { phone: null } : null);
  if (!effective)
    return (
      <Shell>
        <PhoneGate
          orderNumber={orderNumber}
          onAccess={(phone) => {
            rememberOrder({ number: orderNumber, phone });
            setAccess({ phone });
          }}
        />
      </Shell>
    );
  return <Payment orderNumber={orderNumber} access={effective} onDenied={() => setAccess(null)} />;
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <>
      <CheckoutHeader step={null} />
      <main id="main" className="wrap flex flex-col items-center pt-8 pb-16 sm:pt-14">
        {children}
      </main>
    </>
  );
}

function WaitingSkeleton() {
  return (
    <Card padding={32} aria-busy="true" className="flex w-full max-w-[560px] flex-col items-center gap-5">
      <Skeleton className="size-28 rounded-full" />
      <Skeleton className="h-8 w-3/4" />
      <Skeleton className="h-24 w-full" />
    </Card>
  );
}

function statusHeaders(access: Access) {
  return access.phone ? { "X-Order-Phone": access.phone } : {};
}

function usePaymentStatus(orderNumber: string, access: Access) {
  return useQuery({
    queryKey: ["payment", orderNumber, access.phone],
    queryFn: async (): Promise<Status> => {
      const { data, error, response } = await browserApi.GET("/api/v1/payments/{order_number}/status", {
        params: { path: { order_number: orderNumber }, header: statusHeaders(access) },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    refetchInterval: (query) => {
      const s = query.state.data;
      if (query.state.error) return false;
      return s && (s.status === "created" || s.status === "pending") && s.order_status !== "cancelled" ? POLL_MS : false;
    },
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  });
}

function useInitiate(orderNumber: string, access: Access) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<Status> => {
      const { data, error, response } = await browserApi.POST("/api/v1/payments/{order_number}/initiate", {
        params: { path: { order_number: orderNumber } },
        body: { phone: access.phone },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (data) => client.setQueryData(["payment", orderNumber, access.phone], data),
    onSettled: () => client.invalidateQueries({ queryKey: ["payment", orderNumber] }),
  });
}

function useChangeMethod(orderNumber: string, access: Access) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (method: PaymentMethod): Promise<Status> => {
      const { data, error, response } = await browserApi.POST("/api/v1/payments/{order_number}/method", {
        params: { path: { order_number: orderNumber } },
        body: { phone: access.phone, payment_method: method },
      });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
    onSuccess: (data) => client.setQueryData(["payment", orderNumber, access.phone], data),
  });
}

function Payment({ orderNumber, access, onDenied }: { orderNumber: string; access: Access; onDenied: () => void }) {
  const t = useTranslations("store.payment");
  const router = useRouter();
  const status = usePaymentStatus(orderNumber, access);
  const initiate = useInitiate(orderNumber, access);
  const [choosing, setChoosing] = useState(false);
  const started = useRef(false);
  const s = status.data;
  const now = useNow();

  // A new mobile money attempt is sent to the phone once; reloading the page does not resend
  // it (the backend returns the request already started).
  useEffect(() => {
    if (!s || started.current || initiate.isPending) return;
    if (s.status === "created" && MOBILE_MONEY.includes(s.method as PaymentMethod) && s.order_status !== "cancelled") {
      started.current = true;
      initiate.mutate();
    }
  }, [s, initiate]);

  const paid = s?.status === "succeeded";
  const cash = s?.method === "cash_on_delivery";
  useEffect(() => {
    if (paid || (cash && !choosing)) router.replace(`/order/${orderNumber}/confirmed`);
  }, [paid, cash, choosing, orderNumber, router]);

  const denied = status.error instanceof ApiError && (status.error.status === 404 || status.error.status === 403);
  useEffect(() => {
    if (denied && access.phone) onDenied();
  }, [denied, access.phone, onDenied]);

  if (status.isPending || paid || (cash && !choosing)) return <Shell><WaitingSkeleton /></Shell>;
  if (status.isError || !s)
    return (
      <Shell>
        <Card padding={32} role="alert" className="flex w-full max-w-[560px] flex-col items-center gap-4 text-center">
          <h1 className="t-h2">{t(denied ? "notFoundTitle" : "loadFailedTitle")}</h1>
          <p className="text-tx2">{t(denied ? "notFoundText" : "loadFailedText")}</p>
          {denied ? (
            <Link href="/" className={buttonClasses()}>
              {t("continueShopping")}
            </Link>
          ) : (
            <Button onClick={() => status.refetch()}>{t("retry")}</Button>
          )}
        </Card>
      </Shell>
    );

  const held = secondsLeft(s.reservation_expires_at, now);
  const expired = s.order_status === "cancelled" || held === 0;
  return (
    <Shell>
      {expired ? (
        <Expired status={s} />
      ) : choosing ? (
        <ChooseMethod
          orderNumber={orderNumber}
          access={access}
          status={s}
          onDone={(changed) => {
            // A new mobile money attempt is sent to the phone like the first one.
            if (changed) {
              started.current = false;
              initiate.reset();
            }
            setChoosing(false);
          }}
        />
      ) : CLOSED.includes(s.status as (typeof CLOSED)[number]) || initiate.isError ? (
        <Failed
          status={s}
          phone={access.phone}
          heldSeconds={held}
          startError={initiate.error}
          retrying={initiate.isPending}
          onRetry={() => initiate.mutate()}
          onChoose={() => setChoosing(true)}
        />
      ) : (
        <Waiting status={s} phone={access.phone} seconds={held} sending={initiate.isPending || s.status === "created"} onChoose={() => setChoosing(true)} />
      )}
    </Shell>
  );
}

/** The current time, every second (for the countdown). */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

function StepDot({ state, children }: { state: "done" | "now" | "todo"; children: ReactNode }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "inline-flex size-6 flex-none items-center justify-center rounded-full text-xs font-semibold",
        state === "done" && "bg-ok-tx text-white",
        state === "now" && "bg-pri text-white",
        state === "todo" && "border border-bd2 bg-card text-mut",
      )}
    >
      {children}
    </span>
  );
}

function shownPhone(phone: string | null): string | null {
  return phone ? formatPhone(`0${localPhone(phone) ?? ""}`) : null;
}

function Waiting({
  status,
  phone,
  seconds,
  sending,
  onChoose,
}: {
  status: Status;
  phone: string | null;
  seconds: number;
  sending: boolean;
  onChoose: () => void;
}) {
  const t = useTranslations("store.payment");
  const number = shownPhone(phone);
  const provider = t(`provider.${status.method === "airtel_money" ? "airtel_money" : "mtn_momo"}`);
  const strong = (chunks: ReactNode) => <b className="font-semibold text-tx">{chunks}</b>;
  return (
    <section role="status" aria-live="polite" className="flex w-full max-w-[560px] flex-col items-center gap-5 rounded-xl border border-bd bg-card p-8 text-center shadow-sh max-sm:p-5">
      <div className="relative size-28">
        <span className="absolute inset-0 rounded-full border-6 border-light" />
        <span className="absolute inset-0 animate-spin rounded-full border-6 border-transparent border-t-pri border-r-pri [animation-duration:1.6s] motion-reduce:animate-none" />
        <span className={cx("absolute inset-[22px] flex items-center justify-center rounded-full", status.method === "airtel_money" ? "bg-[#E40000] text-white" : "bg-[#FFCC00] text-tx")}>
          <Smartphone size={32} aria-hidden="true" />
        </span>
      </div>
      <div className="flex flex-col items-center gap-1.5">
        <h1 className="t-h2">{t("waitingTitle")}</h1>
        <p className="max-w-[440px] text-tx2">
          {number
            ? t.rich("waitingText", { provider, phone: number, amount: formatMoney(status.amount), b: strong })
            : t.rich("waitingTextNoPhone", { provider, amount: formatMoney(status.amount), b: strong })}
        </p>
      </div>
      <ol className="m-0 flex w-full list-none flex-col gap-2.5 rounded-xl bg-page px-5 py-4 text-left">
        <li className="flex items-center gap-2.5">
          <StepDot state="done">✓</StepDot>
          <span className="text-sm">{t("stepCreated", { number: status.order_number })}</span>
        </li>
        <li className="flex items-center gap-2.5">
          <StepDot state="now">2</StepDot>
          <span className="text-sm font-semibold">{t(sending ? "stepSending" : "stepWaiting")}</span>
        </li>
        <li className="flex items-center gap-2.5">
          <StepDot state="todo">3</StepDot>
          <span className="text-sm text-tx2">{t("stepConfirmed")}</span>
        </li>
      </ol>
      <p className="text-sm text-mut">
        {status.method === "mtn_momo" && <>{t.rich("noPrompt", { b: strong })} </>}
        {t.rich("keepOpen", { time: countdown(seconds), b: strong })}
      </p>
      <Button variant="neutral" onClick={onChoose}>
        {t("changeMethod")}
      </Button>
    </section>
  );
}

function Failed({
  status,
  phone,
  heldSeconds,
  startError,
  retrying,
  onRetry,
  onChoose,
}: {
  status: Status;
  phone: string | null;
  heldSeconds: number;
  startError: Error | null;
  retrying: boolean;
  onRetry: () => void;
  onChoose: () => void;
}) {
  const t = useTranslations("store.payment");
  const number = shownPhone(phone);
  const code = startError instanceof ApiError ? startError.code : null;
  const reason =
    code === "payment_provider_unavailable"
      ? t("reason.unavailable")
      : code
        ? t("reason.notSent")
        : t(`reason.${status.status === "expired" ? "expired" : status.status === "cancelled" ? "cancelled" : "failed"}`);
  const strong = (chunks: ReactNode) => <b className="font-semibold text-tx">{chunks}</b>;
  return (
    <section role="alert" className="flex w-full max-w-[560px] flex-col items-center gap-5 rounded-xl border border-bd bg-card p-8 text-center shadow-sh max-sm:p-5">
      <span className="flex size-22 items-center justify-center rounded-full bg-err-bg text-err-fg">
        <CircleAlert size={40} aria-hidden="true" />
      </span>
      <div className="flex flex-col items-center gap-1.5">
        <h1 className="t-h2">{t("failedTitle")}</h1>
        <p className="max-w-[440px] text-tx2">{t.rich("failedText", { number: status.order_number, b: strong })}</p>
      </div>
      <div className="flex w-full flex-col gap-2 rounded-xl bg-page px-5 py-4 text-left">
        <div className="kv">
          <span>{t("amount")}</span>
          <b className="font-semibold">{formatMoney(status.amount)}</b>
        </div>
        <div className="kv">
          <span>{t("method")}</span>
          <span>
            {t(`provider.${status.method === "airtel_money" ? "airtel_money" : "mtn_momo"}`)}
            {number && ` · ${number}`}
          </span>
        </div>
        <div className="kv">
          <span>{t("reasonLabel")}</span>
          <span className="font-medium text-err-fg">{reason}</span>
        </div>
      </div>
      <div className="flex w-full flex-col gap-2.5">
        <Button size="lg" block disabled={retrying} onClick={onRetry}>
          <RefreshCw size={18} aria-hidden="true" />
          {t("tryAgain")}
        </Button>
        <Button variant="outline" block onClick={onChoose}>
          {t("chooseAnother")}
        </Button>
        <WhatsAppLink label={t("whatsapp")} message={t("whatsappMessage", { number: status.order_number })} block />
      </div>
      <p className="text-cap text-mut">{t("heldFor", { time: countdown(heldSeconds) })}</p>
    </section>
  );
}

function Expired({ status }: { status: Status }) {
  const t = useTranslations("store.payment");
  const strong = (chunks: ReactNode) => <b className="font-semibold text-tx">{chunks}</b>;
  return (
    <section role="alert" className="flex w-full max-w-[560px] flex-col items-center gap-5 rounded-xl border border-bd bg-card p-8 text-center shadow-sh max-sm:p-5">
      <span className="flex size-22 items-center justify-center rounded-full bg-warn-bg text-warn-tx">
        <Clock size={40} aria-hidden="true" />
      </span>
      <div className="flex flex-col items-center gap-1.5">
        <h1 className="t-h2">{t("expiredTitle")}</h1>
        <p className="max-w-[440px] text-tx2">{t.rich("expiredText", { number: status.order_number, b: strong })}</p>
      </div>
      <Link href="/cart" className={buttonClasses({ size: "lg", block: true })}>
        {t("backToCart")}
      </Link>
    </section>
  );
}

/** "Choose another payment method": the methods this order can use (from checkout, else mobile
 * money and, when the order's zone allows it, cash, which the backend checks). */
function ChooseMethod({ orderNumber, access, status, onDone }: { orderNumber: string; access: Access; status: Status; onDone: (changed: boolean) => void }) {
  const t = useTranslations("store.payment");
  const tc = useTranslations("store.checkout");
  const change = useChangeMethod(orderNumber, access);
  const stored: OrderAccess | null = orderAccess(orderNumber);
  const methods: PaymentMethod[] = stored?.methods?.length ? stored.methods : [...MOBILE_MONEY, "cash_on_delivery"];
  const [value, setValue] = useState<PaymentMethod>(status.method as PaymentMethod);
  const [error, setError] = useState<string | null>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    change.mutate(value, {
      onSuccess: () => onDone(true),
      onError: (err) => {
        const code = err instanceof ApiError ? err.code : "";
        if (code === "payment_in_progress") setError(t("switchInProgress"));
        else if (code === "payment_method_change_too_late") setError(t("switchTooLate"));
        else if (err instanceof ApiError && err.status === 422) setError(t("switchUnavailable"));
        else if (code === "order_not_payable") setError(t("switchNotPayable"));
        else setError(t("switchFailed"));
      },
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full max-w-[560px] flex-col gap-5 rounded-xl border border-bd bg-card p-8 shadow-sh max-sm:p-5">
      <div className="flex flex-col gap-1">
        <h1 className="t-h2">{tc("paymentTitle")}</h1>
        <p className="text-tx2">{t("chooseText", { number: orderNumber })}</p>
      </div>
      <fieldset className="m-0 flex flex-col gap-3 border-0 p-0">
        <legend className="sr-only">{tc("paymentTitle")}</legend>
        {methods.map((m) => (
          <RadioOption
            key={m}
            name="method"
            checked={value === m}
            onChange={() => setValue(m)}
            label={
              <span className="flex min-w-0 flex-1 items-center gap-3.5">
                <PaymentMark method={m} size="lg" />
                <span className="flex min-w-0 flex-col">
                  <b className="font-semibold">{tc(`methods.${m}.name`)}</b>
                  <span className="text-cap text-tx2">{tc(`methods.${m}.text`)}</span>
                </span>
              </span>
            }
          />
        ))}
      </fieldset>
      {error && (
        <p role="alert" className="rounded-lg bg-err-bg px-3 py-2.5 text-sm text-err-tx">
          {error}
        </p>
      )}
      <div className="flex flex-wrap justify-between gap-3">
        <Button variant="neutral" onClick={() => onDone(false)}>
          {t("keepMethod")}
        </Button>
        <Button type="submit" disabled={change.isPending}>
          {t("useMethod")}
        </Button>
      </div>
    </form>
  );
}

/** A guest who opened the link in another tab proves the order with its phone. */
function PhoneGate({ orderNumber, onAccess }: { orderNumber: string; onAccess: (phone: string) => void }) {
  const t = useTranslations("store.payment");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const local = localPhone(phone);
    if (!local) {
      setError(t("phoneInvalid"));
      return;
    }
    onAccess(`0${local}`);
  }
  return <PhoneForm orderNumber={orderNumber} phone={phone} setPhone={setPhone} error={error} onSubmit={onSubmit} label={t("phoneGateTitle")} text={t("phoneGateText")} />;
}

export function PhoneForm({
  orderNumber,
  phone,
  setPhone,
  error,
  onSubmit,
  label,
  text,
  pending = false,
}: {
  orderNumber: string;
  phone: string;
  setPhone: (value: string) => void;
  error: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  label: string;
  text: string;
  pending?: boolean;
}) {
  const t = useTranslations("store.payment");
  return (
    <form onSubmit={onSubmit} noValidate className="flex w-full max-w-[480px] flex-col gap-4 rounded-xl border border-bd bg-card p-8 max-sm:p-5">
      <div className="flex flex-col gap-1">
        <h1 className="t-h2">{label}</h1>
        <p className="text-tx2">{text}</p>
        <p className="text-sm font-semibold">{t("orderLabel", { number: orderNumber })}</p>
      </div>
      <Field label={t("phoneLabel")} error={error}>
        {(c) => <PhoneInput {...c} value={phone} maxLength={16} onChange={(e) => setPhone(e.target.value)} placeholder="788 000 111" />}
      </Field>
      <Button type="submit" disabled={pending}>
        {t("phoneContinue")}
      </Button>
    </form>
  );
}
