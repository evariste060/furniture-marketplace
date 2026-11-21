"use client";

import { ArrowLeft, ArrowRight, Info, Lock, Plus, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox, Field, Input, PhoneInput, RadioOption, Select, Textarea } from "@/components/ui/form";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { INFO_PAGES } from "@/lib/info-pages";
import { splitLines, useCart, type Cart } from "@/features/cart/use-cart";
import { useSession } from "@/features/session/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api/errors";
import {
  CHECKOUT_STEPS,
  EMAIL_MAX,
  MOBILE_MONEY,
  NAME_MAX,
  NOTE_MAX,
  STREET_MAX,
  TEXT_MAX,
  checkAddress,
  checkContact,
  checkoutStep,
  fullName,
  localPhone,
  orderAddress,
  rememberOrder,
  splitName,
  type AddressErrors,
  type AddressForm,
  type CheckoutStep,
  type ContactErrors,
  type ContactForm,
  type PaymentMethod,
} from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { formatMoney, formatPhone } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import { CheckoutHeader } from "./checkout-header";
import { PaymentMark } from "./payment-mark";
import { useSavedAddresses, useSaveAddress, useProfile, usePlaceOrder, type SavedAddress } from "./use-checkout";
import { useZones, type Zone } from "./use-zones";

const EMPTY_CONTACT: ContactForm = { firstName: "", lastName: "", phone: "", email: "" };
const EMPTY_ADDRESS: AddressForm = { district: "", sector: "", street: "", landmark: "", save: false };
const NEW = "new";

/** /checkout: CheckoutContact → CheckoutDelivery → CheckoutPayment → CheckoutReview, one page
 * with the step in the URL (?step=). What the customer types stays in this page's memory only:
 * a reload starts again at the first step that is not complete. The backend prices the order
 * from the cart and checks everything again when the order is placed. */
export function CheckoutView() {
  const router = useRouter();
  const params = useSearchParams();
  const asked = checkoutStep(params.get("step"));
  const { data: user, isPending: sessionPending } = useSession();
  const customer = Boolean(user?.is_customer);
  const profile = useProfile(customer);
  const saved = useSavedAddresses(customer);
  const { data: zones } = useZones();

  const [contact, setContact] = useState<ContactForm>(EMPTY_CONTACT);
  const [address, setAddress] = useState<AddressForm>(EMPTY_ADDRESS);
  const [choice, setChoice] = useState<string | null>(null);
  const [method, setMethod] = useState<PaymentMethod | null>(null);
  const [note, setNote] = useState("");
  // The cart as it was when "Place order" was pressed: the order is placed from it, so the page
  // keeps showing it (under the placing overlay) while the cart empties and the order page opens.
  const [placing, setPlacing] = useState<Cart | null>(null);

  // A signed-in customer's details fill in an empty contact form once.
  const [filled, setFilled] = useState(false);
  useEffect(() => {
    if (filled || !profile.data) return;
    const name = splitName(profile.data.full_name);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setContact((c) => ({
      firstName: c.firstName || name.firstName,
      lastName: c.lastName || name.lastName,
      phone: c.phone || (profile.data.phone ? (localPhone(profile.data.phone) ?? "") : ""),
      email: c.email || (profile.data.email ?? ""),
    }));
    setFilled(true);
  }, [filled, profile.data]);

  const addresses = useMemo(() => saved.data ?? [], [saved.data]);
  const zoneDistricts = useMemo(() => [...new Set((zones?.items ?? []).map((z) => z.district))], [zones]);
  // The default saved address is chosen at first; a guest fills in a new one.
  const selected = choice ?? (addresses[0]?.id ?? NEW);
  const savedChoice = addresses.find((a) => a.id === selected) ?? null;
  const place: AddressForm = savedChoice ? savedAddressForm(savedChoice) : address;
  const zone: Zone | undefined = zones?.items.find((z) => z.district === place.district);

  const { data: liveCart, isPending: cartPending } = useCart(zone?.code ?? null);
  const cart = placing ?? liveCart;
  const cod = cart?.delivery?.cod_available ?? zone?.cod_available ?? false;
  const methods: PaymentMethod[] = cod ? [...MOBILE_MONEY, "cash_on_delivery"] : [...MOBILE_MONEY];
  const chosenMethod = method && methods.includes(method) ? method : null;

  const contactOk = Object.keys(checkContact(contact)).length === 0;
  const deliveryOk = Object.keys(checkAddress(place, zoneDistricts)).length === 0 && Boolean(zone);
  const reachable: CheckoutStep = !contactOk ? "contact" : !deliveryOk ? "delivery" : !chosenMethod ? "payment" : "review";
  const step = CHECKOUT_STEPS.indexOf(asked) <= CHECKOUT_STEPS.indexOf(reachable) ? asked : reachable;

  const go = (next: CheckoutStep) => {
    router.push(next === "contact" ? "/checkout" : `/checkout?step=${next}`);
    window.scrollTo({ top: 0 });
  };
  const back = () => {
    const i = CHECKOUT_STEPS.indexOf(step);
    if (i === 0) router.push("/cart");
    else go(CHECKOUT_STEPS[i - 1]);
  };

  if (!placing && (cartPending || sessionPending)) return <CheckoutSkeleton step={step} />;
  if (!cart || cart.lines.length === 0 || splitLines(cart).blocked.length > 0 || cart.item_count === 0)
    return <CartNotReady cart={cart} />;

  return (
    <>
      <CheckoutHeader step={step} onBack={back} />
      <main id="main" className="wrap flex flex-wrap items-start gap-6 pt-4 pb-14 sm:pt-8">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          {step === "contact" && (
            <ContactStep contact={contact} signedIn={Boolean(user)} onDone={(c) => (setContact(c), go("delivery"))} />
          )}
          {step === "delivery" && (
            <DeliveryStep
              addresses={addresses}
              selected={selected}
              onSelect={setChoice}
              address={address}
              zones={zones?.items ?? []}
              districts={zoneDistricts}
              customer={customer}
              cart={cart}
              onBack={back}
              onDone={(a) => (setAddress(a), go("payment"))}
            />
          )}
          {step === "payment" && (
            <PaymentStep
              methods={methods}
              method={chosenMethod}
              phone={contact.phone}
              onBack={back}
              onDone={(m) => (setMethod(m), go("review"))}
            />
          )}
          {step === "review" && chosenMethod && (
            <ReviewMain contact={contact} place={place} zone={zone} method={chosenMethod} cart={cart} note={note} setNote={setNote} go={go} />
          )}
        </div>
        {step === "review" && chosenMethod ? (
          <PlaceOrder
            cart={cart}
            contact={contact}
            place={place}
            saveAddress={!savedChoice && address.save && customer}
            method={chosenMethod}
            note={note}
            onBack={back}
            onPlacing={(on) => setPlacing(on ? cart : null)}
            onPaymentRefused={() => go("payment")}
            onDeliveryRefused={() => go("delivery")}
          />
        ) : (
          <Summary cart={cart} step={step} contact={contact} place={place} go={go} />
        )}
      </main>
      {placing && <PlacingOrder />}
    </>
  );
}

/** From "Place order" until the order or payment page opens: a spinner over the checkout, so the
 * emptied cart never shows in between. */
function PlacingOrder() {
  const t = useTranslations("store.checkout");
  return (
    <div role="status" aria-live="polite" className="fixed inset-0 z-50 flex items-center justify-center bg-page/95 px-4">
      <div className="flex w-full max-w-[420px] flex-col items-center gap-5 rounded-xl border border-bd bg-white p-8 text-center shadow-sh2 max-sm:p-6">
        <span className="relative size-16" aria-hidden="true">
          <span className="absolute inset-0 rounded-full border-4 border-light" />
          <span className="absolute inset-0 animate-spin rounded-full border-4 border-transparent border-t-pri border-r-pri motion-reduce:animate-none" />
        </span>
        <div className="flex flex-col gap-1.5">
          <p className="t-h3 text-navy">{t("placing")}</p>
          <p className="text-sm text-tx2">{t("placingText")}</p>
        </div>
      </div>
    </div>
  );
}

function savedAddressForm(a: SavedAddress): AddressForm {
  return {
    district: a.district ?? "",
    sector: a.sector ?? "",
    street: a.street_address ?? "",
    landmark: a.delivery_instructions ?? "",
    save: false,
  };
}

function placeLine(place: AddressForm): string {
  return [place.street, place.sector, place.district].map((s) => s.trim()).filter(Boolean).join(", ");
}

function CheckoutSkeleton({ step }: { step: CheckoutStep }) {
  return (
    <>
      <CheckoutHeader step={step} />
      <main id="main" aria-busy="true" className="wrap flex flex-wrap items-start gap-6 pt-8 pb-14">
        <Card padding={32} className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-2/3" />
        </Card>
        <Card padding={24} className="w-full flex-[1_1_320px] sm:max-w-[400px]">
          <Skeleton className="h-48 w-full" />
        </Card>
      </main>
    </>
  );
}

/** An empty cart, or one with lines to fix, goes back to the cart page first. */
function CartNotReady({ cart }: { cart: Cart | undefined }) {
  const t = useTranslations("store.checkout");
  const empty = !cart || cart.lines.length === 0;
  return (
    <>
      <CheckoutHeader step={null} />
      <main id="main" className="wrap flex justify-center pt-14 pb-16">
        <Card padding={32} className="flex w-full max-w-[560px] flex-col items-center gap-3 text-center">
          <h1 className="t-h2">{t(empty ? "emptyTitle" : "attentionTitle")}</h1>
          <p className="text-tx2">{t(empty ? "emptyText" : "attentionText")}</p>
          <Link href={empty ? "/" : "/cart"} className={buttonClasses()}>
            {t(empty ? "startShopping" : "backToCart")}
          </Link>
        </Card>
      </main>
    </>
  );
}

function StepNav({ back, nextLabel }: { back: ReactNode; nextLabel: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-bd">
      <span className="pt-4">{back}</span>
      <Button type="submit" size="lg" className="mt-4 max-sm:w-full">
        {nextLabel}
        <ArrowRight size={18} aria-hidden="true" />
      </Button>
    </div>
  );
}

function BackLink({ label, onClick, href }: { label: string; onClick?: () => void; href?: string }) {
  const content = (
    <>
      <ArrowLeft size={16} aria-hidden="true" />
      {label}
    </>
  );
  const cls = "flex cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-sm font-medium text-pri";
  return href ? (
    <Link href={href} className={cls}>
      {content}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls}>
      {content}
    </button>
  );
}

/** Moves focus to the first field marked invalid once the errors are drawn. */
function focusFirstError(form: HTMLFormElement) {
  requestAnimationFrame(() => form.querySelector<HTMLElement>("[aria-invalid=true]")?.focus());
}

const ERROR_KEYS = { required: "required", invalid: "invalid" } as const;

function ContactStep({ contact, signedIn, onDone }: { contact: ContactForm; signedIn: boolean; onDone: (c: ContactForm) => void }) {
  const t = useTranslations("store.checkout");
  const [form, setForm] = useState(contact);
  const [errors, setErrors] = useState<ContactErrors>({});
  // The profile may arrive after the form was opened.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setForm((f) => (f.firstName || f.lastName || f.phone || f.email ? f : contact)), [contact]);
  const set = (key: keyof ContactForm) => (event: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [key]: event.target.value }));
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }));
  };
  const error = (key: keyof ContactForm) => (errors[key] ? t(`errors.${key}.${ERROR_KEYS[errors[key]]}`) : undefined);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = checkContact(form);
    setErrors(found);
    if (Object.keys(found).length === 0) onDone(form);
    else focusFirstError(event.currentTarget);
  }

  return (
    <>
      {!signedIn && (
        <Card padding={24} className="flex flex-wrap items-center justify-between gap-3 max-sm:p-4">
          <div className="flex flex-col gap-0.5">
            <b className="font-semibold">{t("haveAccount")}</b>
            <span className="text-sm text-mut">{t("haveAccountText")}</span>
          </div>
          <Link href={`/login?${new URLSearchParams({ returnTo: "/checkout" })}`} className={buttonClasses({ variant: "outline", size: "sm" })}>
            {t("signIn")}
          </Link>
        </Card>
      )}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5 rounded-xl border border-bd bg-white p-8 max-sm:p-4">
        <div className="flex flex-col gap-1">
          <h1 className="t-h2">{t("contactTitle")}</h1>
          <p className="text-tx2">{t("contactText")}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("firstName")} error={error("firstName")}>
            {(c) => <Input {...c} value={form.firstName} onChange={set("firstName")} maxLength={NAME_MAX} autoComplete="given-name" />}
          </Field>
          <Field label={t("lastName")} error={error("lastName")}>
            {(c) => <Input {...c} value={form.lastName} onChange={set("lastName")} maxLength={NAME_MAX} autoComplete="family-name" />}
          </Field>
        </div>
        <Field label={t("phone")} help={t("phoneHelp")} error={error("phone")}>
          {(c) => <PhoneInput {...c} value={form.phone} onChange={set("phone")} maxLength={16} placeholder="788 000 111" />}
        </Field>
        <Field
          label={
            <>
              {t("email")} <span className="font-normal text-mut">{t("optional")}</span>
            </>
          }
          help={t("emailHelp")}
          error={error("email")}
        >
          {(c) => (
            <Input {...c} type="email" value={form.email} onChange={set("email")} maxLength={EMAIL_MAX} autoComplete="email" placeholder="you@example.com" />
          )}
        </Field>
        <StepNav back={<BackLink label={t("backToCart")} href="/cart" />} nextLabel={t("toDelivery")} />
      </form>
    </>
  );
}

function DeliveryStep({
  addresses,
  selected,
  onSelect,
  address,
  zones,
  districts,
  customer,
  cart,
  onBack,
  onDone,
}: {
  addresses: SavedAddress[];
  selected: string;
  onSelect: (id: string) => void;
  address: AddressForm;
  zones: Zone[];
  districts: string[];
  customer: boolean;
  cart: Cart;
  onBack: () => void;
  onDone: (a: AddressForm) => void;
}) {
  const t = useTranslations("store.checkout");
  const [form, setForm] = useState(address);
  const [errors, setErrors] = useState<AddressErrors>({});
  const [zoneError, setZoneError] = useState(false);
  const usingNew = selected === NEW;
  const current = usingNew ? form : savedAddressForm(addresses.find((a) => a.id === selected)!);
  const zone = zones.find((z) => z.district === current.district);
  const set = (key: keyof AddressForm) => (event: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [key]: event.target.value }));
    if (key in errors) setErrors((e) => ({ ...e, [key]: undefined }));
  };
  const error = (key: "district" | "street") => (errors[key] ? t(`errors.${key}.${ERROR_KEYS[errors[key]]}`) : undefined);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!usingNew) {
      setZoneError(!zone);
      if (zone) onDone(form);
      return;
    }
    const found = checkAddress(form, districts);
    setErrors(found);
    if (Object.keys(found).length === 0) onDone(form);
    else focusFirstError(event.currentTarget);
  }

  const quote = cart.delivery;
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-[22px] rounded-xl border border-bd bg-white p-8 max-sm:p-4">
      <div className="flex flex-col gap-1">
        <h1 className="t-h2">{t("deliveryTitle")}</h1>
        <p className="text-tx2">{t("deliveryText")}</p>
      </div>
      {customer && addresses.length > 0 && (
        <fieldset className="m-0 flex flex-col gap-3 border-0 p-0">
          <legend className="t-h4 mb-3 p-0">{t("savedAddresses")}</legend>
          {addresses.map((a) => {
            const inZone = zones.some((z) => z.district === a.district);
            return (
              <RadioOption
                key={a.id}
                name="address"
                checked={selected === a.id}
                onChange={() => (onSelect(a.id), setZoneError(false))}
                className="items-start"
                label={
                  <span className="flex min-w-0 flex-1 items-start gap-3">
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex items-center gap-2">
                        <b className="font-semibold">{a.label || t("addressFallback")}</b>
                        {a.is_default && <Badge tone="soft-info">{t("default")}</Badge>}
                        {!inZone && <Badge tone="soft-warn">{t("outsideZones")}</Badge>}
                      </span>
                      <span className="text-sm text-tx2">
                        {a.recipient_name} · {formatPhone(a.phone)}
                      </span>
                      <span className="text-sm text-tx2">{[a.street_address, a.sector, a.district].filter(Boolean).join(", ")}</span>
                    </span>
                  </span>
                }
              />
            );
          })}
          <div className="flex flex-wrap gap-4">
            <RadioOption
              name="address"
              checked={usingNew}
              onChange={() => (onSelect(NEW), setZoneError(false))}
              className="w-full"
              label={
                <span className="flex items-center gap-2 font-semibold text-pri-h">
                  <Plus size={16} aria-hidden="true" />
                  {t("addAddress")}
                </span>
              }
            />
          </div>
          <Link href="/account/addresses" className="self-start text-sm font-medium">
            {t("manageAddresses")}
          </Link>
        </fieldset>
      )}
      {usingNew && (
        <div className={cx("flex flex-col gap-4", customer && addresses.length > 0 && "border-t border-bd pt-[18px]")}>
          <h2 className="t-h4">{t("newAddress")}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("district")} error={error("district")}>
              {(c) => (
                <Select {...c} value={form.district} onChange={set("district")} autoComplete="address-level2">
                  <option value="">{t("chooseDistrict")}</option>
                  {districts.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("sector")}>
              {(c) => <Input {...c} value={form.sector} onChange={set("sector")} maxLength={TEXT_MAX} placeholder={t("sectorPlaceholder")} autoComplete="address-level3" />}
            </Field>
          </div>
          <Field label={t("street")} error={error("street")}>
            {(c) => (
              <Input {...c} value={form.street} onChange={set("street")} maxLength={STREET_MAX} placeholder={t("streetPlaceholder")} autoComplete="street-address" />
            )}
          </Field>
          <Field
            label={
              <>
                {t("landmark")} <span className="font-normal text-mut">{t("optional")}</span>
              </>
            }
          >
            {(c) => <Input {...c} value={form.landmark} onChange={set("landmark")} maxLength={STREET_MAX} placeholder={t("landmarkPlaceholder")} />}
          </Field>
          {customer && (
            <Checkbox label={t("saveAddress")} checked={form.save} onChange={(e) => setForm((f) => ({ ...f, save: e.target.checked }))} />
          )}
        </div>
      )}
      <div className={cx("flex items-start gap-3 rounded-xl px-4 py-3.5", zoneError ? "bg-err-bg" : "bg-light")} role={zoneError ? "alert" : undefined}>
        <Info size={18} className={cx("mt-0.5 flex-none", zoneError ? "text-err" : "text-pri")} aria-hidden="true" />
        <div className="flex flex-col gap-0.5">
          {zone && (
            <b className="text-sm font-semibold text-navy">
              {t("zoneLine", {
                zone: zone.name,
                fee:
                  quote && quote.zone_code === zone.code
                    ? quote.free_delivery
                      ? t("freeOver", { amount: formatMoney(quote.free_delivery_threshold) })
                      : formatMoney(quote.delivery_fee)
                    : formatMoney(zone.fee),
              })}
            </b>
          )}
          {zoneError && <b className="text-sm font-semibold text-err-tx">{t("zoneMissing")}</b>}
          <span className="text-cap text-tx2">
            {t("outsideText")}{" "}
            <Link href="/contact" className="font-medium text-pri-h">
              {t("contactUs")}
            </Link>
          </span>
        </div>
      </div>
      <StepNav back={<BackLink label={t("back")} onClick={onBack} />} nextLabel={t("toPayment")} />
    </form>
  );
}

function PaymentStep({
  methods,
  method,
  phone,
  onBack,
  onDone,
}: {
  methods: PaymentMethod[];
  method: PaymentMethod | null;
  phone: string;
  onBack: () => void;
  onDone: (m: PaymentMethod) => void;
}) {
  const t = useTranslations("store.checkout");
  const [value, setValue] = useState<PaymentMethod | null>(method);
  const [error, setError] = useState(false);
  const number = formatPhone(`0${localPhone(phone) ?? ""}`);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (value) onDone(value);
    else setError(true);
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-[18px] rounded-xl border border-bd bg-white p-8 max-sm:p-4">
      <div className="flex flex-col gap-1">
        <h1 className="t-h2 max-sm:hidden">{t("paymentTitle")}</h1>
        <h1 className="t-h3 sm:hidden">{t("paymentTitleMobile")}</h1>
        <p className="text-tx2">{t("paymentText")}</p>
      </div>
      <fieldset className="m-0 flex flex-col gap-3 border-0 p-0" aria-describedby={error ? "method-error" : undefined}>
        <legend className="sr-only">{t("paymentTitle")}</legend>
        {methods.map((m) => (
          <div key={m} className={cx("flex flex-col", value === m && MOBILE_MONEY.includes(m) && "rounded-xl border-2 border-pri bg-light")}>
            <RadioOption
              name="method"
              checked={value === m}
              onChange={() => (setValue(m), setError(false))}
              className={cx(value === m && MOBILE_MONEY.includes(m) && "border-0! bg-transparent! p-4!")}
              label={
                <span className="flex min-w-0 flex-1 items-center gap-3.5">
                  <PaymentMark method={m} size="lg" />
                  <span className="flex min-w-0 flex-col">
                    <b className="font-semibold">{t(`methods.${m}.name`)}</b>
                    <span className="text-cap text-tx2">{t(`methods.${m}.text`)}</span>
                  </span>
                </span>
              }
            />
            {value === m && MOBILE_MONEY.includes(m) && (
              <div className="flex flex-col gap-1 px-4 pb-4 sm:pl-[50px]">
                <span className="text-sm font-medium">{t(m === "mtn_momo" ? "momoNumber" : "airtelNumber")}</span>
                <span className="font-semibold">{number}</span>
                <span className="text-cap text-mut">{t("numberHelp")}</span>
              </div>
            )}
          </div>
        ))}
      </fieldset>
      {error && (
        <p id="method-error" role="alert" className="text-sm text-err">
          {t("errors.method")}
        </p>
      )}
      <p className="flex items-center gap-1.5 text-cap text-mut">
        <ShieldCheck size={14} className="flex-none text-ok" aria-hidden="true" />
        {t("providersNote")}
      </p>
      <StepNav back={<BackLink label={t("back")} onClick={onBack} />} nextLabel={t("toReview")} />
    </form>
  );
}

function ReviewMain({
  contact,
  place,
  zone,
  method,
  cart,
  note,
  setNote,
  go,
}: {
  contact: ContactForm;
  place: AddressForm;
  zone: Zone | undefined;
  method: PaymentMethod;
  cart: Cart;
  note: string;
  setNote: (note: string) => void;
  go: (step: CheckoutStep) => void;
}) {
  const t = useTranslations("store.checkout");
  const phone = formatPhone(`0${localPhone(contact.phone) ?? ""}`);
  const edit = (step: CheckoutStep, label: string) => (
    <button type="button" onClick={() => go(step)} aria-label={`${t("edit")}: ${label}`} className="cursor-pointer border-0 bg-transparent p-0 text-cap font-medium text-pri">
      {t("edit")}
    </button>
  );
  return (
    <>
      <h1 className="t-h2">{t("reviewTitle")}</h1>
      <Card padding={24} className="grid gap-5 sm:grid-cols-3 max-sm:p-4">
        <div className="flex flex-col gap-1">
          <span className="flex items-center justify-between">
            <b className="text-sm font-semibold">{t("contact")}</b>
            {edit("contact", t("contact"))}
          </span>
          <span className="text-sm text-tx2">{fullName(contact)}</span>
          <span className="text-sm text-tx2">{phone}</span>
          {contact.email.trim() && <span className="text-sm break-all text-tx2">{contact.email.trim()}</span>}
        </div>
        <div className="flex flex-col gap-1">
          <span className="flex items-center justify-between">
            <b className="text-sm font-semibold">{t("delivery")}</b>
            {edit("delivery", t("delivery"))}
          </span>
          <span className="text-sm text-tx2">{placeLine(place)}</span>
          {place.landmark.trim() && <span className="text-cap text-mut">{place.landmark.trim()}</span>}
          {zone && <span className="text-cap font-medium text-ok-tx">{zone.name}</span>}
        </div>
        <div className="flex flex-col gap-1">
          <span className="flex items-center justify-between">
            <b className="text-sm font-semibold">{t("payment")}</b>
            {edit("payment", t("payment"))}
          </span>
          <span className="flex items-center gap-2 text-sm text-tx2">
            <PaymentMark method={method} size="sm" />
            {t(`methods.${method}.name`)}
          </span>
          {MOBILE_MONEY.includes(method) && <span className="text-sm text-tx2">{phone}</span>}
        </div>
      </Card>
      <Card padding={24} className="flex flex-col max-sm:p-4">
        <h2 className="t-h4 pb-2">{t("items", { count: cart.item_count })}</h2>
        {cart.lines.map((line, i) => (
          <div key={line.id} className={cx("flex items-center gap-4 py-4", i < cart.lines.length - 1 && "border-b border-bd")}>
            <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-[72px]" iconSize={24} />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <b className="font-semibold">{line.product_name}</b>
              <span className="text-sm text-mut">
                {line.variant_name} · {t("qty", { count: line.quantity })}
              </span>
            </span>
            <b className="font-semibold">{line.line_subtotal !== null ? formatMoney(line.line_subtotal) : "—"}</b>
          </div>
        ))}
      </Card>
      <Card padding={24} className="max-sm:p-4">
        <Field
          label={
            <>
              {t("note")} <span className="font-normal text-mut">{t("optional")}</span>
            </>
          }
          help={t("noteCount", { count: note.length, max: NOTE_MAX })}
        >
          {(c) => <Textarea {...c} value={note} maxLength={NOTE_MAX} onChange={(e) => setNote(e.target.value)} placeholder={t("notePlaceholder")} className="min-h-20" />}
        </Field>
      </Card>
    </>
  );
}

/** The order summary beside steps 1–3: the lines, the totals the backend quoted and, from the
 * second step, what was chosen before with a link to change it. */
function Summary({ cart, step, contact, place, go }: { cart: Cart; step: CheckoutStep; contact: ContactForm; place: AddressForm; go: (s: CheckoutStep) => void }) {
  const t = useTranslations("store.checkout");
  return (
    <aside className="flex w-full flex-[1_1_320px] flex-col gap-4 rounded-xl border border-bd bg-white p-6 max-sm:p-4 sm:max-w-[400px]">
      <h2 className="t-h3">{t("summary")}</h2>
      {step !== "payment" &&
        cart.lines.map((line) => (
          <div key={line.id} className="flex items-center gap-3">
            <ProductImage image={line.image ?? null} alt="" sizes={IMAGE_SIZES.thumb} className="size-14" iconSize={20} />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="text-sm font-medium">{line.product_name}</span>
              <span className="text-cap text-mut">
                {step === "contact" ? `${line.variant_name} · ` : ""}
                {t("qty", { count: line.quantity })}
              </span>
            </span>
            <span className="text-sm font-medium">{line.line_subtotal !== null ? formatMoney(line.line_subtotal) : "—"}</span>
          </div>
        ))}
      {step !== "payment" && <hr className="hr" />}
      <Totals cart={cart} pending={step === "contact"} />
      {step === "contact" && (
        <p className="flex items-center gap-1.5 text-cap text-mut">
          <Lock size={14} className="flex-none text-ok" aria-hidden="true" />
          {t("encrypted")}
        </p>
      )}
      {step === "delivery" && (
        <ChosenBox title={t("contact")} text={`${fullName(contact)} · ${formatPhone(`0${localPhone(contact.phone) ?? ""}`)}`} onChange={() => go("contact")} />
      )}
      {step === "payment" && <ChosenBox title={t("deliverTo")} text={placeLine(place)} onChange={() => go("delivery")} />}
    </aside>
  );
}

function Totals({ cart, pending, total = "total" }: { cart: Cart; pending: boolean; total?: "total" | "totalToPay" }) {
  const t = useTranslations("store.checkout");
  const quote = cart.delivery;
  return (
    <>
      <div className="kv">
        <span>{t("subtotal", { count: cart.item_count })}</span>
        <b className="font-medium">{formatMoney(cart.merchandise_subtotal)}</b>
      </div>
      {cart.discount?.applied && (
        <div className="kv">
          <span>{t("discount", { code: cart.discount.code })}</span>
          <b className="font-medium text-ok-tx">− {formatMoney(cart.discount_total)}</b>
        </div>
      )}
      <div className="kv">
        {quote && !pending ? (
          <>
            <span>{t("deliveryTo", { zone: quote.zone_name })}</span>
            {quote.free_delivery ? <b className="font-medium text-ok-tx">{t("free")}</b> : <b className="font-medium">{formatMoney(quote.delivery_fee)}</b>}
          </>
        ) : (
          <>
            <span>{t("delivery")}</span>
            <span className="text-mut">{t("deliveryNextStep")}</span>
          </>
        )}
      </div>
      <hr className="hr" />
      <div className="flex items-center justify-between">
        <span className="t-h4">{t(total)}</span>
        <span className={cx(total === "totalToPay" ? "t-price-l" : "t-price", "text-navy")}>
          {formatMoney(!pending && cart.grand_total != null ? cart.grand_total : cart.subtotal_after_discount)}
        </span>
      </div>
    </>
  );
}

function ChosenBox({ title, text, onChange }: { title: string; text: string; onChange: () => void }) {
  const t = useTranslations("store.checkout");
  return (
    <div className="flex flex-col gap-0.5 rounded-lg bg-page p-3">
      <span className="text-cap font-semibold">{title}</span>
      <span className="text-cap text-tx2">{text}</span>
      <button type="button" onClick={onChange} aria-label={`${t("change")}: ${title}`} className="cursor-pointer self-start border-0 bg-transparent p-0 text-cap font-medium text-pri">
        {t("change")}
      </button>
    </div>
  );
}

/** CheckoutReview's right column: the order total, the terms and "Place order". */
function PlaceOrder({
  cart,
  contact,
  place,
  saveAddress,
  method,
  note,
  onBack,
  onPlacing,
  onPaymentRefused,
  onDeliveryRefused,
}: {
  cart: Cart;
  contact: ContactForm;
  place: AddressForm;
  saveAddress: boolean;
  method: PaymentMethod;
  note: string;
  onBack: () => void;
  /** True when the order is sent; false again if it is refused. */
  onPlacing: (placing: boolean) => void;
  onPaymentRefused: () => void;
  onDeliveryRefused: () => void;
}) {
  const t = useTranslations("store.checkout");
  const toast = useToast();
  const router = useRouter();
  const placeOrder = usePlaceOrder();
  const save = useSaveAddress();
  const [agreed, setAgreed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [termsError, setTermsError] = useState(false);
  const total = cart.grand_total ?? cart.subtotal_after_discount;

  function onPlace() {
    if (!agreed) {
      setTermsError(true);
      return;
    }
    setError(null);
    onPlacing(true);
    const address = orderAddress(contact, place);
    placeOrder.mutate(
      { address, payment_method: method, email: contact.email.trim() || null, note: note.trim() || null },
      {
        onSuccess: (result) => {
          const number = result.order.order_number;
          rememberOrder({
            number,
            phone: address.phone,
            methods: result.payment_methods_available.filter((m): m is PaymentMethod => m !== "card"),
          });
          if (saveAddress)
            save.mutate(
              { ...address, is_default: false },
              { onError: () => toast.show(t("addressNotSaved"), "error") },
            );
          router.replace(method === "cash_on_delivery" ? `/order/${number}/confirmed` : `/checkout/pay/${number}`);
        },
        onError: (err) => {
          onPlacing(false);
          const code = err instanceof ApiError ? err.code : "";
          if (code === "payment_method_unavailable") {
            toast.show(t("errors.methodUnavailable"), "error");
            onPaymentRefused();
          } else if (code === "delivery_unavailable" || code === "delivery_quote_unavailable") {
            toast.show(t("errors.deliveryUnavailable"), "error");
            onDeliveryRefused();
          } else if (code === "cart_needs_attention" || code === "insufficient_stock" || code === "cart_empty" || code === "cart_not_found")
            setError(t("errors.cartChanged"));
          else if (code === "rate_limited") setError(t("errors.tooMany"));
          else if (err instanceof ApiError && err.status === 422) setError(t("errors.checkDetails"));
          else setError(t("errors.placeFailed"));
        },
      },
    );
  }

  const policy = (href: string) => (chunks: ReactNode) => (
    <Link href={href} target="_blank" className="underline">
      {chunks}
    </Link>
  );
  return (
    <aside className="flex w-full flex-[1_1_320px] flex-col gap-3.5 sm:max-w-[400px]">
      <Card padding={24} className="flex flex-col gap-3.5 max-sm:p-4">
        <h2 className="t-h3">{t("orderTotal")}</h2>
        <Totals cart={cart} pending={false} total="totalToPay" />
        <p className="text-cap text-mut">{t("vatIncluded")}</p>
      </Card>
      <div className="flex flex-col gap-1">
        <Checkbox
          className="items-start"
          checked={agreed}
          aria-invalid={termsError || undefined}
          aria-describedby={termsError ? "terms-error" : undefined}
          onChange={(e) => (setAgreed(e.target.checked), setTermsError(false))}
          label={
            <span className="text-sm text-tx2">
              {t.rich("terms", { terms: policy(INFO_PAGES.terms), delivery: policy(INFO_PAGES.delivery), returns: policy(INFO_PAGES.returns) })}
            </span>
          }
        />
        {termsError && (
          <span id="terms-error" role="alert" className="text-cap text-err">
            {t("errors.terms")}
          </span>
        )}
      </div>
      {error && (
        <div role="alert" className="flex flex-col gap-1 rounded-lg bg-err-bg px-3 py-2.5 text-sm text-err-tx">
          {error}
          {error === t("errors.cartChanged") && (
            <Link href="/cart" className="font-medium text-err-tx underline">
              {t("backToCart")}
            </Link>
          )}
        </div>
      )}
      <Button size="lg" block disabled={placeOrder.isPending || placeOrder.isSuccess} onClick={onPlace}>
        <Lock size={18} aria-hidden="true" />
        {placeOrder.isPending ? t("placing") : t("place", { amount: formatMoney(total) })}
      </Button>
      <span className="flex justify-center">
        <BackLink label={t("backToPayment")} onClick={onBack} />
      </span>
    </aside>
  );
}
