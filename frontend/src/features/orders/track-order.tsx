"use client";

import { useMutation } from "@tanstack/react-query";
import { CircleAlert, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, PhoneInput } from "@/components/ui/form";
import { ProductImage } from "@/components/ui/product-image";
import { WhatsAppLink } from "@/features/contact/whatsapp-link";
import { Link } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { localPhone, orderAccess, orderNumber } from "@/lib/checkout";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import { addressLine, ProgressList, StatusBadge } from "./order-parts";

type Order = components["schemas"]["OrderDetailResponse"];

/** /track (Track.dc.html): a guest finds an order with its number and the checkout phone
 * (POST /orders/lookup; failed tries are limited by the backend). */
export function TrackOrder() {
  const t = useTranslations("store.track");
  const params = useSearchParams();
  const form = useRef<HTMLFormElement>(null);
  const [number, setNumber] = useState(() => orderNumber(params.get("order") ?? "") ?? "");
  const [phone, setPhone] = useState("");
  const [errors, setErrors] = useState<{ number?: string; phone?: string }>({});
  const lookup = useMutation({
    mutationFn: async (body: { order_number: string; phone: string }): Promise<Order> => {
      const { data, error, response } = await browserApi.POST("/api/v1/orders/lookup", { body });
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });

  useEffect(() => {
    // An order placed in this tab: its phone is already known (sessionStorage, browser only).
    const known = number ? orderAccess(number) : null;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (known) setPhone(known.phone.replace(/^0/, ""));
    // Only for the order number the page opened with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    const parsed = orderNumber(number);
    const local = localPhone(phone);
    if (!parsed) found.number = t(number.trim() ? "numberInvalid" : "numberRequired");
    if (!local) found.phone = t(phone.trim() ? "phoneInvalid" : "phoneRequired");
    setErrors(found);
    if (Object.keys(found).length) {
      requestAnimationFrame(() => form.current?.querySelector<HTMLElement>("[aria-invalid=true]")?.focus());
      return;
    }
    lookup.mutate({ order_number: parsed!, phone: `0${local}` });
  }

  const error = lookup.error instanceof ApiError ? lookup.error : lookup.error ? new ApiError(0, "network", "") : null;
  return (
    <>
      <form ref={form} onSubmit={onSubmit} noValidate aria-label={t("formLabel")} className="flex flex-wrap items-end gap-4 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
        <Field label={t("number")} error={errors.number} className="flex-[1_1_220px]">
          {(c) => <Input {...c} value={number} onChange={(e) => setNumber(e.target.value.toUpperCase())} maxLength={40} placeholder="ORD-261028-AB12CD" autoCapitalize="characters" />}
        </Field>
        <Field label={t("phone")} error={errors.phone} className="flex-[1_1_220px]">
          {(c) => <PhoneInput {...c} value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={16} placeholder="788 000 111" />}
        </Field>
        <Button type="submit" disabled={lookup.isPending} className={errors.number || errors.phone ? "self-center" : undefined}>
          <Search size={18} aria-hidden="true" />
          {t("submit")}
        </Button>
      </form>
      {error && (
        <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          <CircleAlert size={18} aria-hidden="true" className="flex-none" />
          <span>
            {error.status === 404
              ? t.rich("notFound", {
                  link: (chunks) => (
                    <Link href="/contact" className="text-err-tx underline">
                      {chunks}
                    </Link>
                  ),
                })
              : error.status === 429
                ? t("limited")
                : t("unavailable")}
          </span>
        </div>
      )}
      {lookup.data && !lookup.isPending && <TrackResult order={lookup.data} />}
    </>
  );
}

function TrackResult({ order }: { order: Order }) {
  const t = useTranslations("store.track");
  const to = useTranslations("store.order");
  const paid = order.payment?.status === "succeeded";
  const where = addressLine(order.delivery_address, ["sector", "district"]);
  return (
    <div className="flex flex-wrap items-start gap-6">
      <section aria-label={t("statusLabel")} className="flex min-w-0 flex-[999_1_460px] flex-col gap-5 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-cap text-tx2">{t("order")}</span>
            <b className="t-h3">#{order.order_number}</b>
          </div>
          <StatusBadge status={order.status} className="px-3 py-1.5 text-sm" />
        </div>
        {order.status === "cancelled" ? (
          <p role="status" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
            {t("cancelled")}
          </p>
        ) : (
          <ProgressList order={order} />
        )}
      </section>
      <aside className="flex w-full flex-[1_1_280px] flex-col gap-3 rounded-xl border border-bd bg-card p-6 max-sm:p-4">
        <h2 className="t-h4">{t("summary")}</h2>
        {order.lines.map((line) => (
          <div key={line.id} className="flex items-center gap-3">
            <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-12 flex-none" iconSize={20} />
            <span className="flex flex-1 flex-col text-sm">
              <span>
                {line.product_name}
                {line.quantity > 1 && <span className="text-tx2"> × {line.quantity}</span>}
              </span>
              <span className="text-cap text-tx2">{to("soldBy", { store: line.store_name })}</span>
            </span>
          </div>
        ))}
        <hr className="hr" />
        <div className="kv">
          <span>{to(paid ? "totalPaid" : "totalToPay")}</span>
          <b className="font-semibold">{formatMoney(order.total)}</b>
        </div>
        {where && (
          <div className="kv">
            <span>{t("deliverTo")}</span>
            <span className="text-right">{where}</span>
          </div>
        )}
        <WhatsAppLink label={t("whatsapp")} message={t("whatsappMessage", { number: order.order_number })} size="sm" iconSize={16} block />
      </aside>
    </div>
  );
}
