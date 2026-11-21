"use client";

import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { GoogleIcon } from "@/components/ui/google-icon";

/** Continue with Google on the login, register and profile pages (ADR-006 amendment 2026-11-11).
 * The page only asks this app's /api/auth/google/*start to begin and then goes to the Google URL it
 * gets back; the flow token stays in an httpOnly cookie and the callback sets the session cookie,
 * so no credential ever reaches this code. */

/** Message keys (store.auth.google.*) for every code a Google attempt can end with. */
const MESSAGES: Record<string, string> = {
  google_auth_cancelled: "cancelled",
  google_state_invalid: "expired",
  google_auth_failed: "failed",
  google_code_invalid: "failed",
  google_token_invalid: "failed",
  google_email_unverified: "unverified",
  google_email_invalid: "emailInvalid",
  google_staff_not_allowed: "staff",
  account_inactive: "inactive",
  google_account_exists: "exists",
  rate_limited: "limited",
  google_unavailable: "unavailable",
  google_auth_unavailable: "unavailable",
  login_unavailable: "unavailable",
  backend_unavailable: "unavailable",
  google_account_in_use: "inUse",
  google_already_linked: "alreadyLinked",
  token_missing: "signedOut",
  session_invalid: "signedOut",
};

/** The message for a code from the callback's redirect or a failed start; unknown codes get the
 * generic one. */
export function useGoogleMessage() {
  const t = useTranslations("store.auth.google");
  return (code: string | null | undefined): string | null => (code ? t(MESSAGES[code] ?? "failed") : null);
}

type Start = { returnTo?: string; wishlist?: string | null; page?: "login" | "register" };

/** Asks this app to start a Google flow and goes to Google. Resolves with the failure code if it
 * could not start (it never resolves on success: the page is navigating away). */
export async function startGoogle(path: "/api/auth/google/start" | "/api/auth/google/link/start", body: Start & { locale: string }): Promise<string> {
  let res: Response;
  try {
    res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    return "backend_unavailable";
  }
  const data = (await res.json().catch(() => null)) as { authorization_url?: unknown; error?: { code?: unknown } } | null;
  const url = data?.authorization_url;
  // This app's handler already checked it; checked again before navigating anywhere.
  if (res.ok && typeof url === "string" && url.startsWith("https://accounts.google.com/")) {
    window.location.assign(url);
    return new Promise<string>(() => undefined);
  }
  return typeof data?.error?.code === "string" ? data.error.code : "backend_unavailable";
}

/** Coming back from Google with the Back button can restore this page from the back/forward cache
 * exactly as it was left, still "Opening Google…". A restored page (pageshow with persisted) gets
 * its button back. */
export function useResetWhenRestored(setPending: (pending: boolean) => void) {
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) setPending(false);
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [setPending]);
}

/** The "Continue with Google" button (.btn-n, the design system's white bordered button). */
export function ContinueWithGoogle({
  page,
  returnTo,
  wishlist,
  disabled = false,
  onFailure,
}: Start & { page: "login" | "register"; disabled?: boolean; onFailure: (code: string) => void }) {
  const t = useTranslations("store.auth.google");
  const locale = useLocale();
  const [pending, setPending] = useState(false);
  useResetWhenRestored(setPending);

  async function onClick() {
    setPending(true);
    const code = await startGoogle("/api/auth/google/start", { page, returnTo, wishlist: wishlist ?? undefined, locale });
    setPending(false);
    onFailure(code);
  }

  return (
    <Button type="button" variant="neutral" size="lg" block disabled={disabled || pending} aria-busy={pending || undefined} onClick={onClick}>
      <GoogleIcon size={20} />
      {pending ? t("starting") : t("continue")}
    </Button>
  );
}

/** The design's "or" divider (a rule either side), between sign-in options. */
export function OrDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2.5 text-cap text-tx2">
      <span className="hr flex-1" />
      {label}
      <span className="hr flex-1" />
    </div>
  );
}
