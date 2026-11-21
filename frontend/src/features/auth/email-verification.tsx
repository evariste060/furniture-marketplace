"use client";

import { ArrowLeft, CircleAlert, CircleCheck, Clock, MailCheck, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button, buttonClasses } from "@/components/ui/button";
import { useModal } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { FormAlert } from "@/features/auth/auth-forms";
import { Link, useRouter } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { emailOk } from "@/lib/auth";
import { EMAIL_MAX } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { readLinkToken, retryAfterSeconds, withoutToken } from "@/lib/email-verification";

/** Email verification (backend ADR-006 amendment 2026-11-12; docs/api/email-verification.md):
 * the "check your inbox" modal after registration, the /verify-email page the email links to,
 * and the form that asks for a new link. Both calls go through this app's backend proxy (public
 * endpoints, no credentials). The token is read once from the link, removed from the address bar
 * and kept in memory only: never stored, logged or sent anywhere but the verify endpoint.
 *
 * Both screens use the branded card of the owner's references (2026-11-13): a navy band with the
 * store name and tagline, then a white body with a round icon, the title, the text and one
 * full-width navy action. Nothing spins: every state is static and usable at once. The backend
 * answers registration before the email leaves (it is sent in the background), so the copy says
 * the link is being sent, never that it was delivered. */

// The verify request gives up after this long and offers "Try again" instead of waiting forever.
const VERIFY_TIMEOUT_MS = 15_000;

// The backend's resend cooldown (EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS, 60 by default): the
// button waits as long. The backend enforces it; this only avoids requests that would do nothing.
const COOLDOWN_SECONDS = 60;

type Resend = { kind: "sent" } | { kind: "invalid" } | { kind: "limited"; seconds: number | null } | { kind: "unavailable" };

/** POST /auth/email/verification/resend. Its 202 is the same whether or not a link was sent. */
export async function requestNewLink(email: string): Promise<Resend> {
  try {
    const { response } = await browserApi.POST("/api/v1/auth/email/verification/resend", { body: { email } });
    if (response.status === 202) return { kind: "sent" };
    if (response.status === 422) return { kind: "invalid" };
    if (response.status === 429) return { kind: "limited", seconds: retryAfterSeconds(response.headers.get("retry-after")) };
    return { kind: "unavailable" };
  } catch {
    return { kind: "unavailable" };
  }
}

type Verify = "verified" | "invalid" | "expired" | "used" | "limited" | "unavailable";

/** POST /auth/email/verify, mapped to the page's states. Unknown answers count as unavailable. */
export async function confirmEmail(token: string, timeoutMs = VERIFY_TIMEOUT_MS): Promise<{ outcome: Verify; seconds: number | null }> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const { response, error } = await browserApi.POST("/api/v1/auth/email/verify", { body: { token }, signal: abort.signal });
    if (response.status === 200) return { outcome: "verified", seconds: null };
    const code = (error as { error?: { code?: unknown } } | undefined)?.error?.code;
    if (response.status === 429) return { outcome: "limited", seconds: retryAfterSeconds(response.headers.get("retry-after")) };
    if (code === "verification_token_expired") return { outcome: "expired", seconds: null };
    if (code === "verification_token_used") return { outcome: "used", seconds: null };
    if (code === "verification_token_invalid" || response.status === 422) return { outcome: "invalid", seconds: null };
    return { outcome: "unavailable", seconds: null };
  } catch {
    return { outcome: "unavailable", seconds: null }; // network failure, or the timeout above
  } finally {
    clearTimeout(timer);
  }
}

function minutes(seconds: number | null): number {
  return Math.max(1, Math.ceil((seconds ?? 3600) / 60));
}

function useCountdown(initial = 0) {
  const [left, setLeft] = useState(initial);
  useEffect(() => {
    if (left <= 0) return;
    const timer = setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [left]);
  return [left, setLeft] as const;
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** The round icon of the reference screens: the brand's light blue, or the success green. */
function Badge({ children, tone = "pri" }: { children: ReactNode; tone?: "pri" | "ok" | "err" }) {
  return (
    <span
      className={cx(
        "flex size-20 flex-none items-center justify-center rounded-full max-sm:size-16",
        tone === "ok" ? "bg-ok-bg text-ok-tx" : tone === "err" ? "bg-err-bg text-err-tx" : "bg-light text-pri",
      )}
    >
      {children}
    </span>
  );
}

/** The navy band at the top of the card: the store name in the brand's cyan, the tagline below. */
function BrandBand() {
  const t = useTranslations("store.auth.verify");
  const brand = useTranslations("meta");
  return (
    <div className="bg-navy px-6 py-6 text-center max-sm:px-4 max-sm:py-5">
      <p className="m-0 text-[15px] font-bold text-cyan">{brand("title")}</p>
      <p className="m-0 mt-1.5 text-xs font-semibold tracking-[0.2em] text-white/90 uppercase max-sm:tracking-[0.12em]">{t("tagline")}</p>
    </div>
  );
}

/** The card of the references: band, then the centred body. */
function BrandCard({ children, labelledBy, className }: { children: ReactNode; labelledBy: string; className?: string }) {
  return (
    <section aria-labelledby={labelledBy} className={cx("mx-auto w-full max-w-[600px] overflow-hidden rounded-2xl bg-white shadow-sh2", className)}>
      <BrandBand />
      <div className="flex flex-col items-center gap-4 px-12 pt-10 pb-11 text-center max-sm:px-5 max-sm:pt-8 max-sm:pb-7">{children}</div>
    </section>
  );
}

function CardTitle({ id, children, focus = false }: { id: string; children: ReactNode; focus?: boolean }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) heading.current?.focus();
  }, [focus]);
  return (
    <h1 id={id} ref={heading} tabIndex={-1} className="m-0 t-h2 text-tx outline-none">
      {children}
    </h1>
  );
}

function CardText({ children }: { children: ReactNode }) {
  return <p className="m-0 max-w-[460px] text-base leading-relaxed text-tx2">{children}</p>;
}

function BackToSignIn() {
  const t = useTranslations("store.auth");
  return (
    <Link href="/login" className="flex items-center justify-center gap-1.5 text-sm font-medium">
      <ArrowLeft size={16} aria-hidden="true" />
      {t("backToSignIn")}
    </Link>
  );
}

// ---- asking for a new link -----------------------------------------------------------------------

/** Ask for a new verification link. With `email` (known already: after registration, or the
 * address typed at sign-in) it is one button; without, an email field first. The reply is the
 * same whatever the backend did, so the page never says an email was delivered. `nested`: inside
 * another form (sign-in), so it must not be a <form> itself: a group with a plain button, and
 * Enter in its field sends this request rather than the outer form. */
export function NewLinkForm({ email, cooldown = 0, nested = false }: { email?: string; cooldown?: number; nested?: boolean }) {
  const t = useTranslations("store.auth.verify");
  const ta = useTranslations("store.auth");
  const [value, setValue] = useState(email ?? "");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [pending, setPending] = useState(false);
  const [wait, setWait] = useCountdown(cooldown);
  const root = useRef<HTMLDivElement & HTMLFormElement>(null);
  const focusField = () => root.current?.querySelector<HTMLInputElement>("input")?.focus();

  async function send() {
    if (pending || wait > 0) return; // one request at a time, none during the cooldown
    const address = (email ?? value).trim();
    if (!emailOk(address)) {
      setError(ta(address ? "emailInvalid" : "verify.emailRequired"));
      focusField();
      return;
    }
    setError(null);
    setNotice(null);
    setPending(true);
    const result = await requestNewLink(address);
    setPending(false);
    if (result.kind === "sent") {
      setNotice({ tone: "ok", text: t("sentNeutral") });
      setWait(COOLDOWN_SECONDS);
    } else if (result.kind === "invalid") {
      setError(ta("emailInvalid"));
      focusField();
    } else if (result.kind === "limited") {
      setNotice({ tone: "err", text: t("limited", { minutes: minutes(result.seconds) }) });
      setWait(result.seconds ?? COOLDOWN_SECONDS);
    } else setNotice({ tone: "err", text: t("unavailable") });
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send();
  }

  const body = (
    <>
      {notice && <FormAlert tone={notice.tone}>{notice.text}</FormAlert>}
      {email === undefined && (
        <Field label={ta("email")} error={error ?? undefined}>
          {(c) => (
            <Input
              {...c}
              type="email"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="email"
              maxLength={EMAIL_MAX}
              onKeyDown={(e) => {
                if (nested && e.key === "Enter") {
                  e.preventDefault(); // not the sign-in form around it
                  void send();
                }
              }}
            />
          )}
        </Field>
      )}
      {email !== undefined && error && (
        <span role="alert" className="text-cap text-err">
          {error}
        </span>
      )}
      <Button
        type={nested ? "button" : "submit"}
        onClick={nested ? () => void send() : undefined}
        variant="outline"
        block
        disabled={pending || wait > 0}
        aria-busy={pending || undefined}
      >
        {pending ? t("sending") : wait > 0 ? t("sendAgainIn", { time: clock(wait) }) : t("sendNew")}
      </Button>
    </>
  );
  return nested ? (
    <div ref={root} role="group" aria-label={t("sendNew")} className="flex flex-col gap-3">
      {body}
    </div>
  ) : (
    <form ref={root} onSubmit={onSubmit} noValidate className="flex flex-col gap-3">
      {body}
    </form>
  );
}

// ---- after registration --------------------------------------------------------------------------

/** "Resend confirmation email": a text button under the message, with its cooldown and its
 * outcome right below it (polite live region, so screen readers hear it too). */
function ResendLink({ email }: { email: string }) {
  const t = useTranslations("store.auth.verify");
  const [pending, setPending] = useState(false);
  // The registration just asked for a link: the backend sends no other within its cooldown.
  const [wait, setWait] = useCountdown(COOLDOWN_SECONDS);
  const [notice, setNotice] = useState<{ tone: "ok" | "err"; text: string } | null>(null);

  async function resend() {
    if (pending || wait > 0) return;
    setPending(true);
    setNotice(null);
    const result = await requestNewLink(email);
    setPending(false);
    if (result.kind === "sent") {
      setNotice({ tone: "ok", text: t("sentNeutral") });
      setWait(COOLDOWN_SECONDS);
    } else if (result.kind === "limited") {
      setNotice({ tone: "err", text: t("limited", { minutes: minutes(result.seconds) }) });
      setWait(result.seconds ?? COOLDOWN_SECONDS);
    } else setNotice({ tone: "err", text: t("unavailable") });
  }

  return (
    <div className="flex flex-col items-center gap-1.5">
      <button
        type="button"
        onClick={resend}
        disabled={pending || wait > 0}
        aria-busy={pending || undefined}
        className="cursor-pointer border-0 bg-transparent p-0 text-base font-semibold text-navy hover:underline disabled:cursor-default disabled:text-tx2 disabled:no-underline"
      >
        {pending ? t("sending") : wait > 0 ? t("resendIn", { time: clock(wait) }) : t("resendLink")}
      </button>
      <p role="status" aria-live="polite" className={cx("m-0 min-h-5 text-sm", notice?.tone === "err" ? "text-err-tx" : "text-ok-tx")}>
        {notice?.text}
      </p>
    </div>
  );
}

/** Screen 1 (owner's reference, 2026-11-13): over the registration page as soon as the account
 * is created. A modal on the native <dialog> (focus trapped, Escape closes); closing it, or
 * "Back to Sign In", goes to sign-in: the account exists, so the form behind is done with. */
export function CheckYourEmail({ email }: { email: string }) {
  const t = useTranslations("store.auth.verify");
  const ta = useTranslations("store.auth");
  const router = useRouter();
  const titleId = useId();
  const close = () => router.push("/login");
  const ref = useModal(true, close);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className="m-auto w-[calc(100%-32px)] max-w-[600px] overflow-visible bg-transparent p-0 backdrop:bg-overlay"
    >
      <div className="relative">
        <BrandCard labelledBy={titleId}>
          <Badge>
            <MailCheck size={32} strokeWidth={1.75} aria-hidden="true" />
          </Badge>
          <CardTitle id={titleId} focus>
            {t("checkTitle")}
          </CardTitle>
          <CardText>{t.rich("checkText", { email, b: (chunks) => <b className="font-semibold break-all text-tx">{chunks}</b> })}</CardText>
          <p className="m-0 max-w-[460px] text-sm text-tx2">{t("spamNote")}</p>
          <ResendLink email={email} />
          <Link href="/login" className={buttonClasses({ variant: "dark", size: "lg", block: true })}>
            {t("backToSignIn")}
          </Link>
        </BrandCard>
        <button
          type="button"
          onClick={close}
          aria-label={ta("verify.close")}
          className="absolute -top-4 -right-4 flex size-11 cursor-pointer items-center justify-center rounded-full border-0 bg-white text-tx2 shadow-sh2 hover:text-tx max-sm:top-2 max-sm:right-2 max-sm:size-9 max-sm:bg-white/15 max-sm:text-white max-sm:shadow-none"
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
    </dialog>
  );
}

/** At sign-in: the account exists, the password was right, the email is not verified yet. */
export function EmailNotVerified({ identifier }: { identifier: string }) {
  const t = useTranslations("store.auth.verify");
  const email = identifier.includes("@") ? identifier.trim() : undefined;
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg bg-light px-4 py-3.5">
      <div className="flex items-start gap-2.5">
        <MailCheck size={18} aria-hidden="true" className="mt-0.5 flex-none text-pri-h" />
        <div className="flex flex-col gap-0.5">
          <b className="text-sm font-semibold text-tx">{t("notVerifiedTitle")}</b>
          <span className="text-sm text-tx2">{t("notVerifiedText")}</span>
        </div>
      </div>
      <NewLinkForm email={email} nested />
    </div>
  );
}

// ---- /verify-email -------------------------------------------------------------------------------

type PageState = "checking" | "missing" | Verify;

/** /verify-email. Screen 2 (owner's reference, 2026-11-13) is shown only after the backend
 * answered 200 for this token; every other answer has its own state. */
export function VerifyEmailView() {
  const t = useTranslations("store.auth.verify");
  const [state, setState] = useState<PageState>("checking");
  const [seconds, setSeconds] = useState<number | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const token = useRef<string | null>(null);
  // The last link handled: each link is sent once, even when React runs effects twice. Not a
  // one-off flag: another link opened in this same tab changes only the #fragment, which the
  // browser does not reload for, and it must be checked too (it once kept showing the previous
  // link's "Email confirmed" for any later link, 2026-11-13).
  const handled = useRef<string | null>(null);
  // Only the newest request may set the state: a slow answer for an earlier link is ignored.
  const latest = useRef(0);
  const titleId = useId();

  async function submit() {
    const current = token.current;
    if (!current) return;
    const run = ++latest.current;
    setState("checking");
    const result = await confirmEmail(current);
    if (run !== latest.current) return;
    // A token that worked, or can never work, is dropped; one that met an outage is kept for a retry.
    if (result.outcome !== "unavailable" && result.outcome !== "limited") token.current = null;
    setCanRetry(token.current !== null);
    setSeconds(result.seconds);
    setState(result.outcome);
  }

  useEffect(() => {
    function readLink(initial: boolean) {
      // React runs this effect twice in development: the first run already read the link (and
      // removed it from the address), so the second must not read the now empty address.
      if (initial && handled.current !== null) return;
      const hasToken = /^#(.*&)?token=/.test(window.location.hash) || /[?&]token=/.test(window.location.search);
      // A later fragment change without a token (e.g. "#") leaves the current result alone.
      if (!initial && !hasToken) return;
      const link = readLinkToken(window.location.hash, window.location.search);
      // Out of the address bar, history and any later Referer before anything else happens.
      if (hasToken) {
        window.history.replaceState(window.history.state, "", withoutToken(window.location.pathname, window.location.search));
      }
      // Every link opened later (a hashchange) is checked again, even the same one: it then shows
      // "already used", never the earlier success.
      handled.current = link.kind === "ok" ? link.token : `:${link.kind}`;
      if (link.kind === "ok") {
        token.current = link.token;
        void submit();
      } else {
        latest.current++; // any answer still on its way is for another link
        token.current = null;
        setCanRetry(false);
        setState(link.kind === "missing" ? "missing" : "invalid");
      }
    }
    // The link is read in the browser only (the fragment never reaches the server).
    readLink(true);
    const onHashChange = () => readLink(false);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  if (state === "checking") {
    // Static, no spinner: the request usually answers at once, and gives up after 15 seconds.
    return (
      <BrandCard labelledBy={titleId}>
        <div role="status" aria-live="polite" className="flex flex-col items-center gap-4">
          <Badge>
            <MailCheck size={32} strokeWidth={1.75} aria-hidden="true" />
          </Badge>
          <CardTitle id={titleId}>{t("checkingTitle")}</CardTitle>
          <CardText>{t("checkingText")}</CardText>
        </div>
      </BrandCard>
    );
  }

  const copy: Record<Exclude<PageState, "checking">, { title: string; text: string; tone: "ok" | "err" | "pri"; icon: ReactNode }> = {
    verified: { title: t("verifiedTitle"), text: t("verifiedText"), tone: "ok", icon: <CircleCheck size={32} strokeWidth={1.75} aria-hidden="true" /> },
    used: { title: t("usedTitle"), text: t("usedText"), tone: "pri", icon: <CircleCheck size={32} strokeWidth={1.75} aria-hidden="true" /> },
    expired: { title: t("expiredTitle"), text: t("expiredText"), tone: "err", icon: <Clock size={32} strokeWidth={1.75} aria-hidden="true" /> },
    invalid: { title: t("invalidTitle"), text: t("invalidText"), tone: "err", icon: <CircleAlert size={32} strokeWidth={1.75} aria-hidden="true" /> },
    missing: { title: t("missingTitle"), text: t("missingText"), tone: "pri", icon: <MailCheck size={32} strokeWidth={1.75} aria-hidden="true" /> },
    limited: { title: t("limitedTitle"), text: t("limited", { minutes: minutes(seconds) }), tone: "err", icon: <Clock size={32} strokeWidth={1.75} aria-hidden="true" /> },
    unavailable: { title: t("unavailableTitle"), text: t("unavailableText"), tone: "err", icon: <CircleAlert size={32} strokeWidth={1.75} aria-hidden="true" /> },
  };
  const shown = copy[state];
  const askForLink = state === "expired" || state === "invalid" || state === "missing" || state === "used";
  const signIn = state === "verified" || state === "used";

  return (
    <BrandCard labelledBy={titleId}>
      <Badge tone={shown.tone}>{shown.icon}</Badge>
      <CardTitle id={titleId} focus>
        {shown.title}
      </CardTitle>
      <p role={state === "verified" ? "status" : undefined} className="m-0 max-w-[460px] text-base leading-relaxed text-tx2">
        {shown.text}
      </p>
      {signIn && (
        <Link href="/login?verified=1" className={cx(buttonClasses({ variant: "dark", size: "lg", block: true }), "mt-2")}>
          {t("goToLogin")}
        </Link>
      )}
      {state === "unavailable" && canRetry && (
        <Button variant="dark" size="lg" block className="mt-2" onClick={() => void submit()}>
          {t("tryAgain")}
        </Button>
      )}
      {askForLink && (
        <div className="mt-2 flex w-full flex-col gap-2 border-t border-bd pt-5 text-left">
          <h2 className="m-0 t-h3">{t("resendTitle")}</h2>
          <p className="m-0 text-sm text-tx2">{t("resendText")}</p>
          <NewLinkForm />
        </div>
      )}
      {!signIn && <BackToSignIn />}
    </BrandCard>
  );
}
