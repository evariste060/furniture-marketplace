"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Heart, House, LogOut, MapPin, MessageSquareText, Package, User } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { FormAlert } from "@/features/auth/auth-forms";
import { useProfile } from "@/features/checkout/use-checkout";
import { SESSION_KEY, useSession } from "@/features/session/use-session";
import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { initials } from "@/lib/auth";
import { cx } from "@/lib/cx";
import { formatPhone } from "@/lib/format";

/** The account area (Account.dc.html and siblings): customers only. Guests are sent to sign in
 * and back; staff accounts have no customer area and go to the admin. The backend refuses every
 * account call without a customer session anyway. */
export function AccountShell({ children }: { children: ReactNode }) {
  const { data: user, isPending } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (user) signingOut.current = false;
    if (isPending || signingOut.current) return;
    if (!user) router.replace(`/login?${new URLSearchParams({ returnTo: pathname }).toString()}`);
    else if (user.is_staff) window.location.assign("/admin");
  }, [user, isPending, pathname, router]);

  return (
    <div className="wrap flex flex-wrap items-start gap-6 pt-8 pb-16 max-sm:pt-4">
      <AccountNav ready={Boolean(user?.is_customer)} />
      <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-4">
        {user?.is_customer && <GoogleWelcome />}
        {user?.is_customer ? children : <AccountSkeleton />}
      </div>
    </div>
  );
}

/** After Continue with Google created the account (?google=created from the callback). */
function GoogleWelcome() {
  const t = useTranslations("store.account");
  const params = useSearchParams();
  if (params.get("google") !== "created") return null;
  return <FormAlert tone="ok">{t("googleWelcome")}</FormAlert>;
}

/** The account pages, in menu order: the side menu here and the phone tab bar's Account popup. */
export const ACCOUNT_LINKS = [
  { href: "/account", key: "overview", Icon: House },
  { href: "/account/orders", key: "orders", Icon: Package },
  { href: "/account/wishlist", key: "wishlist", Icon: Heart },
  { href: "/account/messages", key: "messages", Icon: MessageSquareText },
  { href: "/account/addresses", key: "addresses", Icon: MapPin },
  { href: "/account/profile", key: "profile", Icon: User },
] as const;

/** Whether an account menu link is the current page. */
export function isAccountLinkActive(href: string, pathname: string): boolean {
  return href === "/account" ? pathname === href : pathname.startsWith(href);
}

/** Set while signing out, so the account pages do not send the now signed-out visitor to sign in
 * on the way home. Cleared when someone is signed in again. */
const signingOut = { current: false };

/** Log out (the side menu and the phone Account popup): ends the session, drops the account data
 * and goes home. */
export function useLogOut() {
  const router = useRouter();
  const client = useQueryClient();
  return async function logOut() {
    signingOut.current = true;
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    client.setQueryData(SESSION_KEY, null);
    client.removeQueries({ queryKey: ["customer"] });
    router.replace("/");
    // Refreshed in the background: waiting for every refetch delayed leaving the page.
    void client.invalidateQueries();
  };
}

/** The side menu (wider screens). On phones the tab bar's Account popup takes its place. */
function AccountNav({ ready }: { ready: boolean }) {
  const t = useTranslations("store.account");
  const pathname = usePathname();
  const logOut = useLogOut();
  const { data: profile } = useProfile(ready);
  const linkClass = "flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2.5 font-medium no-underline";

  return (
    <nav aria-label={t("navLabel")} className="hidden w-full flex-col gap-1 rounded-xl border border-bd bg-white p-4 sm:flex sm:max-w-[260px] sm:flex-[1_1_240px]">
      <div className="flex items-center gap-3 px-3 pt-2 pb-4 max-sm:pb-2">
        <span className="inline-flex size-11 flex-none items-center justify-center rounded-full bg-pri text-[15px] font-semibold text-white" aria-hidden="true">
          {profile ? initials(profile.full_name) : ""}
        </span>
        <span className="flex min-w-0 flex-col">
          {profile ? <b className="truncate font-semibold">{profile.full_name}</b> : <Skeleton className="h-5 w-32" />}
          {profile?.phone && <span className="text-cap text-tx2">{formatPhone(profile.phone)}</span>}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {ACCOUNT_LINKS.map(({ href, key, Icon }) => {
          const on = isAccountLinkActive(href, pathname);
          return (
            <Link key={href} href={href} aria-current={on ? "page" : undefined} className={cx(linkClass, on ? "bg-light text-pri-h" : "text-tx2 hover:text-pri-h")}>
              <Icon size={18} aria-hidden="true" />
              {t(`nav.${key}`)}
            </Link>
          );
        })}
        <button type="button" onClick={logOut} className={cx(linkClass, "cursor-pointer border-0 bg-transparent text-left text-base text-err")}>
          <LogOut size={18} aria-hidden="true" />
          {t("nav.logout")}
        </button>
      </div>
    </nav>
  );
}

export function AccountSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-4">
      <Skeleton className="h-10 w-64" />
      <Skeleton className="h-40 w-full rounded-xl" />
      <Skeleton className="h-40 w-full rounded-xl" />
    </div>
  );
}
