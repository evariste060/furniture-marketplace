"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleCheck, Eye, EyeOff, KeyRound } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { Checkbox, Field, Input, PhoneInput } from "@/components/ui/form";
import { CheckYourEmail, EmailNotVerified } from "@/features/auth/email-verification";
import { ContinueWithGoogle, OrDivider, useGoogleMessage } from "@/features/auth/google-sign-in";
import { useSession } from "@/features/session/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import {
  emailOk,
  forgetResetIdentifier,
  maskIdentifier,
  PASSWORD_MAX,
  passwordOk,
  passwordStrength,
  rememberResetIdentifier,
  resetIdentifier,
  safeReturnTo,
} from "@/lib/auth";
import { EMAIL_MAX, localPhone, NAME_MAX, splitName } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { INFO_PAGES } from "@/lib/info-pages";

/** Login, Register, Forgot and Reset (frontend phase 5). Sign-in and registration go through
 * /api/auth/*, which keep the session token in an httpOnly cookie; the password pages call the
 * backend through the proxy. Every rule is checked again by the backend. Continue with Google
 * (./google-sign-in.tsx) sits above the login and register forms; its callback comes back here
 * with ?google_error=<code> when it did not sign in. */

type Failure = { status: number; code: string; retryAfter: number | null };
type Success = { user: { is_staff?: boolean }; verificationRequired: boolean };

async function postAuth(path: "/api/auth/login" | "/api/auth/register", body: unknown): Promise<Success | Failure> {
  let res: Response;
  try {
    res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    return { status: 0, code: "network", retryAfter: null };
  }
  const data = (await res.json().catch(() => null)) as { user?: { is_staff?: boolean }; verification_required?: boolean; error?: { code?: string } } | null;
  // Registration with an email (2026-11-12): the account exists, but no session until verified.
  if (res.ok && data?.user) return { user: data.user, verificationRequired: data.verification_required === true };
  const retry = Number(res.headers.get("retry-after"));
  return { status: res.status, code: data?.error?.code ?? "unknown", retryAfter: Number.isFinite(retry) && retry > 0 ? retry : null };
}

function minutes(seconds: number | null): number {
  return Math.max(1, Math.ceil((seconds ?? 900) / 60));
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function focusFirstError(form: HTMLFormElement | null) {
  requestAnimationFrame(() => form?.querySelector<HTMLElement>("[aria-invalid=true]")?.focus());
}

/** A password field with the eye button (.inp with padding-right 44px). */
function PasswordInput({
  control,
  value,
  onChange,
  autoComplete,
  placeholder,
}: {
  control: { id: string; "aria-describedby"?: string; "aria-invalid"?: true };
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  placeholder?: string;
}) {
  const t = useTranslations("store.auth");
  const [shown, setShown] = useState(false);
  return (
    <span className="relative block">
      <Input
        {...control}
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        maxLength={PASSWORD_MAX}
        placeholder={placeholder}
        className="pr-11"
      />
      <button
        type="button"
        aria-label={t(shown ? "hidePassword" : "showPassword")}
        aria-pressed={shown}
        onClick={() => setShown((s) => !s)}
        className="absolute top-1.5 right-1.5 flex size-8 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-tx2"
      >
        {shown ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
      </button>
    </span>
  );
}

function FormAlert({ children, tone = "err" }: { children: ReactNode; tone?: "err" | "ok" }) {
  return (
    <div
      role={tone === "err" ? "alert" : "status"}
      className={cx("flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm", tone === "err" ? "bg-err-bg text-err-tx" : "bg-ok-bg text-ok-tx")}
    >
      {tone === "ok" && <CircleCheck size={16} aria-hidden="true" className="flex-none" />}
      <span>{children}</span>
    </div>
  );
}

function policyLinks() {
  return {
    terms: (chunks: ReactNode) => (
      <Link href={INFO_PAGES.terms} className="underline">
        {chunks}
      </Link>
    ),
    privacy: (chunks: ReactNode) => (
      <Link href={INFO_PAGES.privacy} className="underline">
        {chunks}
      </Link>
    ),
  };
}

/** After signing in: staff go to the admin (outside the storefront's locale routing); customers
 * save the product they hearted, if any, then return to where they were. */
function useFinishSignIn() {
  const client = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const returnTo = safeReturnTo(params.get("returnTo"));
  const wishlist = params.get("wishlist");
  return async (user: { is_staff?: boolean }) => {
    if (user.is_staff) {
      window.location.assign("/admin");
      return;
    }
    if (wishlist && UUID.test(wishlist)) {
      // Best effort: the product may be gone or the wishlist full; signing in still succeeded.
      await browserApi.PUT("/api/v1/customers/me/wishlist/{product_id}", { params: { path: { product_id: wishlist } } }).catch(() => undefined);
    }
    await client.invalidateQueries();
    router.replace(returnTo);
  };
}

// ---- Login.dc.html -----------------------------------------------------------------------------

export function LoginView() {
  const t = useTranslations("store.auth");
  const params = useSearchParams();
  const returnTo = safeReturnTo(params.get("returnTo"));
  const finish = useFinishSignIn();
  const router = useRouter();
  const { data: user } = useSession();
  const form = useRef<HTMLFormElement>(null);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ identifier?: string; password?: string }>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const googleMessage = useGoogleMessage();
  const [googleFailure, setGoogleFailure] = useState<string | null>(() => params.get("google_error"));
  // The identifier of a sign-in refused because its email is not verified yet.
  const [unverified, setUnverified] = useState<string | null>(null);

  // Already signed in (another tab, the back button): carry on.
  useEffect(() => {
    if (pending || !user) return;
    if (user.is_staff) window.location.assign("/admin");
    else router.replace(returnTo);
  }, [user, pending, returnTo, router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    if (!identifier.trim()) found.identifier = t("identifierRequired");
    if (!password) found.password = t("passwordRequired");
    setErrors(found);
    setFailure(null);
    setGoogleFailure(null);
    setUnverified(null);
    if (Object.keys(found).length) return focusFirstError(form.current);
    setPending(true);
    const result = await postAuth("/api/auth/login", { identifier: identifier.trim(), password });
    if ("user" in result) {
      await finish(result.user);
      return;
    }
    setPending(false);
    if (result.code === "email_not_verified") {
      // The form keeps what was typed; the notice offers a new link for that address.
      setUnverified(identifier.trim());
      return;
    }
    setFailure(
      result.code === "invalid_credentials"
        ? t("invalid")
        : result.code === "rate_limited"
          ? t("limited", { minutes: minutes(result.retryAfter) })
          : result.code === "account_inactive"
            ? t("inactive")
            : t("unavailable"),
    );
  }

  const registerHref = `/register?${new URLSearchParams({ returnTo }).toString()}`;
  const guest = returnTo.startsWith("/checkout") || returnTo.startsWith("/cart");
  return (
    <div className="mx-auto flex max-w-[960px] flex-wrap items-stretch overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
      <div className="flex flex-[1_1_360px] flex-col gap-[18px] bg-navy p-10 text-white max-sm:order-2 max-sm:p-6">
        <h2 className="t-h2 text-white">{t("asideTitle")}</h2>
        <p className="text-odm">{t("asideText")}</p>
        <ul className="m-0 flex list-none flex-col gap-3 p-0 pt-2">
          {(["perkAddresses", "perkOrders", "perkTrack"] as const).map((key) => (
            <li key={key} className="flex items-center gap-2.5">
              <CircleCheck size={18} aria-hidden="true" className="flex-none text-cyan" />
              {t(key)}
            </li>
          ))}
        </ul>
        <span className="flex-1" />
        <p className="text-cap text-odm">{t("staffNote")}</p>
      </div>
      <form ref={form} onSubmit={onSubmit} noValidate className="flex flex-[1_1_400px] flex-col gap-[18px] p-10 max-sm:p-6">
        <div className="flex flex-col gap-1">
          <h1 className="t-h2">{t("loginTitle")}</h1>
          <p className="text-sm text-tx2">
            {t.rich("newHere", {
              link: (chunks) => (
                <Link href={registerHref} className="font-medium underline">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        </div>
        {params.get("reset") === "1" && !failure && !googleFailure && <FormAlert tone="ok">{t("passwordUpdated")}</FormAlert>}
        {params.get("verified") === "1" && !failure && !googleFailure && !unverified && <FormAlert tone="ok">{t("verify.verifiedNotice")}</FormAlert>}
        {failure && <FormAlert>{failure}</FormAlert>}
        {unverified && <EmailNotVerified key={unverified} identifier={unverified} />}
        {googleFailure && !failure && <FormAlert>{googleMessage(googleFailure)}</FormAlert>}
        <ContinueWithGoogle page="login" returnTo={returnTo} wishlist={params.get("wishlist")} disabled={pending} onFailure={setGoogleFailure} />
        <OrDivider label={t("or")} />
        <Field label={t("identifier")} error={errors.identifier}>
          {(c) => <Input {...c} value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" maxLength={EMAIL_MAX} />}
        </Field>
        <div className="relative">
          <Field label={t("password")} error={errors.password}>
            {(c) => <PasswordInput control={c} value={password} onChange={setPassword} autoComplete="current-password" />}
          </Field>
          <Link href="/forgot-password" className="absolute top-0 right-0 text-sm font-medium">
            {t("forgot")}
          </Link>
        </div>
        <Button type="submit" size="lg" block disabled={pending}>
          {pending ? t("signingIn") : t("signIn")}
        </Button>
        {guest && (
          <>
            <OrDivider label={t("or")} />
            <Link href="/checkout" className={buttonClasses({ variant: "neutral", block: true })}>
              {t("guest")}
            </Link>
          </>
        )}
        <p className="text-cap text-tx2">{t.rich("signInTerms", policyLinks())}</p>
      </form>
    </div>
  );
}

// ---- Register.dc.html --------------------------------------------------------------------------

type RegisterErrors = Partial<Record<"firstName" | "lastName" | "phone" | "email" | "password" | "terms", string>>;

export function RegisterView() {
  const t = useTranslations("store.auth");
  const params = useSearchParams();
  const returnTo = safeReturnTo(params.get("returnTo"));
  const finish = useFinishSignIn();
  const form = useRef<HTMLFormElement>(null);
  // The confirmation page fills in the guest's name and phone (owner decision 2026-10-27).
  const [initial] = useState(() => splitName(params.get("name")?.slice(0, NAME_MAX * 2)));
  const [firstName, setFirstName] = useState(initial.firstName.slice(0, NAME_MAX));
  const [lastName, setLastName] = useState(initial.lastName.slice(0, NAME_MAX));
  const [phone, setPhone] = useState(() => {
    const local = localPhone(params.get("phone") ?? "");
    return local ? `${local.slice(0, 3)} ${local.slice(3, 6)} ${local.slice(6)}` : "";
  });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [terms, setTerms] = useState(false);
  const [errors, setErrors] = useState<RegisterErrors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const googleMessage = useGoogleMessage();
  const [googleFailure, setGoogleFailure] = useState<string | null>(() => params.get("google_error"));
  // The address a verification link went to: the form gives way to "check your email".
  const [awaiting, setAwaiting] = useState<string | null>(null);
  const strength = passwordStrength(password);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: RegisterErrors = {};
    if (firstName.trim().length < 1) found.firstName = t("firstNameRequired");
    if (lastName.trim().length < 1) found.lastName = t("lastNameRequired");
    const local = localPhone(phone);
    if (!phone.trim()) found.phone = t("phoneRequired");
    else if (!local) found.phone = t("phoneInvalid");
    if (email.trim() && !emailOk(email.trim())) found.email = t("emailInvalid");
    if (!passwordOk(password)) found.password = t("passwordRule");
    if (!terms) found.terms = t("termsRequired");
    setErrors(found);
    setFailure(null);
    setGoogleFailure(null);
    if (Object.keys(found).length) return focusFirstError(form.current);
    setPending(true);
    const result = await postAuth("/api/auth/register", {
      full_name: `${firstName.trim()} ${lastName.trim()}`,
      phone: `0${local}`,
      email: email.trim() || undefined,
      password,
    });
    if ("user" in result) {
      if (result.verificationRequired) {
        setPending(false);
        setAwaiting(email.trim());
        return;
      }
      await finish(result.user);
      return;
    }
    setPending(false);
    if (result.code === "email_taken") setErrors({ email: t("emailTaken") });
    else if (result.code === "phone_taken") setErrors({ phone: t("phoneTaken") });
    else if (result.code === "email_verification_unavailable") setFailure(t("verify.registerUnavailable"));
    else setFailure(result.status === 422 ? t("checkDetails") : t("unavailable"));
    if (result.code === "email_taken" || result.code === "phone_taken") focusFirstError(form.current);
  }

  const loginHref = `/login?${new URLSearchParams({ returnTo }).toString()}`;
  return (
    <form ref={form} onSubmit={onSubmit} noValidate className="mx-auto flex max-w-[520px] flex-col gap-[18px] rounded-xl border border-bd bg-white p-8 shadow-sh max-sm:p-5">
      <div className="flex flex-col gap-1">
        <h1 className="t-h2">{t("registerTitle")}</h1>
        <p className="text-sm text-tx2">
          {t.rich("haveAccount", {
            link: (chunks) => (
              <Link href={loginHref} className="font-medium underline">
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
      {failure && <FormAlert>{failure}</FormAlert>}
      {googleFailure && !failure && <FormAlert>{googleMessage(googleFailure)}</FormAlert>}
      <ContinueWithGoogle page="register" returnTo={returnTo} wishlist={params.get("wishlist")} disabled={pending} onFailure={setGoogleFailure} />
      <OrDivider label={t("or")} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("firstName")} error={errors.firstName}>
          {(c) => <Input {...c} value={firstName} onChange={(e) => setFirstName(e.target.value)} autoComplete="given-name" maxLength={NAME_MAX} />}
        </Field>
        <Field label={t("lastName")} error={errors.lastName}>
          {(c) => <Input {...c} value={lastName} onChange={(e) => setLastName(e.target.value)} autoComplete="family-name" maxLength={NAME_MAX} />}
        </Field>
      </div>
      <Field label={t("phone")} error={errors.phone}>
        {(c) => <PhoneInput {...c} value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={16} placeholder="788 000 111" />}
      </Field>
      <Field
        label={
          <>
            {t("email")} <span className="font-normal text-tx2">{t("optional")}</span>
          </>
        }
        error={errors.email}
      >
        {(c) => <Input {...c} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={EMAIL_MAX} />}
      </Field>
      <Field label={t("password")} error={errors.password} help={password ? t(`strength${strength}`) : t("passwordRule")}>
        {(c) => (
          <>
            <PasswordInput control={c} value={password} onChange={setPassword} autoComplete="new-password" />
            <div className="flex gap-1" aria-hidden="true">
              {[1, 2, 3, 4].map((bar) => (
                <span key={bar} className="h-1 flex-1 overflow-hidden rounded-full bg-bd">
                  <span
                    className={cx("block h-full", bar <= strength && (strength >= 3 ? "bg-ok" : strength === 2 ? "bg-warn" : "bg-err"))}
                    style={{ width: bar <= strength ? "100%" : "0%" }}
                  />
                </span>
              ))}
            </div>
          </>
        )}
      </Field>
      <div className="flex flex-col gap-1.5">
        <Checkbox
          checked={terms}
          onChange={(e) => setTerms(e.target.checked)}
          aria-invalid={errors.terms ? true : undefined}
          aria-describedby={errors.terms ? "terms-error" : undefined}
          className="items-start [&>input]:mt-0.5"
          label={<span className="text-sm text-tx2">{t.rich("agree", policyLinks())}</span>}
        />
        {errors.terms && (
          <span id="terms-error" className="text-cap text-err">
            {errors.terms}
          </span>
        )}
      </div>
      <Button type="submit" size="lg" block disabled={pending}>
        {pending ? t("creating") : t("createAccount")}
      </Button>
      <p className="text-center text-cap text-tx2">{t("returnNote")}</p>
      {/* The owner's Screen 1: over this page once the account exists (2026-11-13). */}
      {awaiting && <CheckYourEmail email={awaiting} />}
    </form>
  );
}

// ---- Forgot.dc.html ----------------------------------------------------------------------------

async function requestCode(identifier: string): Promise<"ok" | "limited" | "unavailable" | "invalid"> {
  try {
    const { response } = await browserApi.POST("/api/v1/auth/forgot-password", { body: { identifier } });
    if (response.ok) return "ok";
    if (response.status === 429) return "limited";
    if (response.status === 422) return "invalid";
    return "unavailable";
  } catch {
    return "unavailable";
  }
}

function identifierOk(value: string): boolean {
  return value.includes("@") ? emailOk(value) : localPhone(value) !== null;
}

/** "788 000 111" → "0788000111"; emails as typed. The backend normalises both again. */
function identifierValue(value: string): string {
  const trimmed = value.trim();
  const local = trimmed.includes("@") ? null : localPhone(trimmed);
  return local ? `0${local}` : trimmed;
}

export function ForgotView() {
  const t = useTranslations("store.auth");
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const form = useRef<HTMLFormElement>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFailure(null);
    if (!identifierOk(identifier.trim())) {
      setError(t(identifier.trim() ? "identifierInvalid" : "identifierRequired"));
      return focusFirstError(form.current);
    }
    setError(null);
    setPending(true);
    const value = identifierValue(identifier);
    const result = await requestCode(value);
    setPending(false);
    if (result === "ok") {
      rememberResetIdentifier(value);
      router.push("/reset-password");
    } else if (result === "invalid") {
      setError(t("identifierInvalid"));
      focusFirstError(form.current);
    } else setFailure(t(result === "limited" ? "codeLimited" : "resetUnavailable"));
  }

  return (
    <form ref={form} onSubmit={onSubmit} noValidate className="mx-auto flex max-w-[480px] flex-col gap-[18px] rounded-xl border border-bd bg-white p-8 shadow-sh max-sm:p-5">
      <span className="flex size-14 items-center justify-center rounded-[14px] bg-light text-pri">
        <KeyRound size={28} aria-hidden="true" />
      </span>
      <div className="flex flex-col gap-1.5">
        <h1 className="t-h2">{t("forgotTitle")}</h1>
        <p className="text-tx2">{t("forgotText")}</p>
      </div>
      {failure && <FormAlert>{failure}</FormAlert>}
      <Field label={t("forgotIdentifier")} error={error}>
        {(c) => <Input {...c} value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" maxLength={EMAIL_MAX} />}
      </Field>
      <Button type="submit" size="lg" block disabled={pending}>
        {t("sendCode")}
      </Button>
      <Link href="/login" className="flex items-center justify-center gap-1.5 text-sm font-medium">
        <ArrowLeft size={16} aria-hidden="true" />
        {t("backToSignIn")}
      </Link>
    </form>
  );
}

// ---- Reset.dc.html -----------------------------------------------------------------------------

const RESEND_SECONDS = 60;

/** Six one-digit boxes; typing moves on, Backspace moves back, pasting fills them all. */
function CodeInput({ value, onChange, invalid, describedBy }: { value: string; onChange: (value: string) => void; invalid: boolean; describedBy?: string }) {
  const t = useTranslations("store.auth");
  const boxes = useRef<Array<HTMLInputElement | null>>([]);
  const digits = Array.from({ length: 6 }, (_, i) => value[i] ?? "");

  function set(index: number, digit: string) {
    const next = digits.slice();
    next[index] = digit;
    onChange(next.join("").slice(0, 6));
  }
  function onInput(index: number, raw: string) {
    const typed = raw.replace(/\D/g, "");
    if (!typed) return set(index, "");
    if (typed.length > 1) return fill(index, typed);
    set(index, typed);
    boxes.current[index + 1]?.focus();
  }
  function fill(start: number, typed: string) {
    const next = digits.slice();
    for (let i = 0; i < typed.length && start + i < 6; i++) next[start + i] = typed[i]!;
    onChange(next.join(""));
    boxes.current[Math.min(5, start + typed.length)]?.focus();
  }
  function onKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Backspace" && !digits[index] && index > 0) boxes.current[index - 1]?.focus();
  }
  function onPaste(index: number, event: ClipboardEvent<HTMLInputElement>) {
    const typed = event.clipboardData.getData("text").replace(/\D/g, "");
    if (!typed) return;
    event.preventDefault();
    fill(index, typed);
  }
  return (
    <div className="flex gap-2.5 max-sm:gap-1.5">
      {digits.map((digit, i) => (
        <input
          key={i}
          ref={(el) => {
            boxes.current[i] = el;
          }}
          aria-label={t("digit", { n: i + 1 })}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          maxLength={6}
          value={digit}
          onChange={(e) => onInput(i, e.target.value)}
          onKeyDown={(e) => onKeyDown(i, e)}
          onPaste={(e) => onPaste(i, e)}
          className="h-14 w-[52px] rounded-lg border border-bd bg-white p-0 text-center text-[22px] font-semibold outline-none focus:border-pri focus:shadow-focus aria-invalid:border-err max-sm:w-11"
        />
      ))}
    </div>
  );
}

export function ResetView() {
  const t = useTranslations("store.auth");
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const [stored, setStored] = useState<string | null | undefined>(undefined);
  const [identifier, setIdentifier] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Partial<Record<"identifier" | "code" | "password" | "confirm", string>>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [wait, setWait] = useState(RESEND_SECONDS);

  useEffect(() => {
    // sessionStorage exists only in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStored(resetIdentifier());
  }, []);
  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const target = stored ?? identifierValue(identifier);

  async function resend() {
    setFailure(null);
    setNotice(null);
    if (!identifierOk(target)) {
      setErrors({ identifier: t(identifier.trim() ? "identifierInvalid" : "identifierRequired") });
      return focusFirstError(form.current);
    }
    const result = await requestCode(target);
    if (result === "ok") {
      setWait(RESEND_SECONDS);
      setNotice(t("codeSent"));
    } else setFailure(t(result === "limited" ? "codeLimited" : "resetUnavailable"));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: typeof errors = {};
    if (!stored && !identifierOk(identifier.trim())) found.identifier = t(identifier.trim() ? "identifierInvalid" : "identifierRequired");
    if (!/^\d{6}$/.test(code)) found.code = t("codeRequired");
    if (!passwordOk(password)) found.password = t("passwordRule");
    if (confirm !== password) found.confirm = t("confirmMismatch");
    setErrors(found);
    setFailure(null);
    setNotice(null);
    if (Object.keys(found).length) return focusFirstError(form.current);
    setPending(true);
    let status = 0;
    let errorCode: string | undefined;
    try {
      const { response, error } = await browserApi.POST("/api/v1/auth/reset-password", { body: { identifier: target, code, new_password: password } });
      status = response.status;
      errorCode = (error as { error?: { code?: string } } | undefined)?.error?.code;
    } catch {
      // A network failure leaves status 0: shown as "unavailable" below.
    }
    if (status >= 200 && status < 300) {
      forgetResetIdentifier();
      router.push("/login?reset=1");
      return;
    }
    setPending(false);
    if (errorCode === "reset_code_invalid") {
      setErrors({ code: t("codeInvalid") });
      focusFirstError(form.current);
    } else if (status === 429) setFailure(t("codeLimited"));
    else if (status === 422) setFailure(t("checkDetails"));
    else setFailure(t("resetUnavailable"));
  }

  if (stored === undefined) return null;
  return (
    <form ref={form} onSubmit={onSubmit} noValidate className="mx-auto flex max-w-[480px] flex-col gap-[18px] rounded-xl border border-bd bg-white p-8 shadow-sh max-sm:p-5">
      <div className="flex flex-col gap-1.5">
        <h1 className="t-h2">{t("resetTitle")}</h1>
        <p className="text-tx2">
          {stored ? t.rich("resetSent", { target: maskIdentifier(stored), b: (chunks) => <b className="font-semibold text-tx">{chunks}</b> }) : t("resetSentUnknown")}
        </p>
      </div>
      {failure && <FormAlert>{failure}</FormAlert>}
      {notice && <FormAlert tone="ok">{notice}</FormAlert>}
      {!stored && (
        <Field label={t("forgotIdentifier")} error={errors.identifier}>
          {(c) => <Input {...c} value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" maxLength={EMAIL_MAX} />}
        </Field>
      )}
      <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
        <legend className="mb-2 p-0 text-sm font-medium">{t("codeLabel")}</legend>
        <CodeInput value={code} onChange={setCode} invalid={Boolean(errors.code)} describedBy="code-note" />
        <span id="code-note" className={cx("text-cap", errors.code ? "text-err" : "text-tx2")}>
          {errors.code ?? (
            <>
              {t("noCode")}{" "}
              <button
                type="button"
                onClick={resend}
                disabled={wait > 0}
                className="cursor-pointer border-0 bg-transparent p-0 font-medium text-pri-h disabled:cursor-default disabled:text-tx2"
              >
                {wait > 0 ? t("resendIn", { time: `0:${String(wait).padStart(2, "0")}` }) : t("resend")}
              </button>
            </>
          )}
        </span>
      </fieldset>
      <Field label={t("newPassword")} error={errors.password}>
        {(c) => <PasswordInput control={c} value={password} onChange={setPassword} autoComplete="new-password" placeholder={t("newPasswordPlaceholder")} />}
      </Field>
      <Field label={t("confirmPassword")} error={errors.confirm}>
        {(c) => <PasswordInput control={c} value={confirm} onChange={setConfirm} autoComplete="new-password" placeholder={t("confirmPlaceholder")} />}
      </Field>
      <Button type="submit" size="lg" block disabled={pending}>
        {t("resetSubmit")}
      </Button>
      <Link href="/login" className="flex items-center justify-center gap-1.5 text-sm font-medium">
        <ArrowLeft size={16} aria-hidden="true" />
        {t("backToSignIn")}
      </Link>
    </form>
  );
}

export { PasswordInput, FormAlert };
