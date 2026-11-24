"use client";

import { LogOut, User } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { ACCOUNT_LINKS, isAccountLinkActive, SellerDashboardLink, useLogOut } from "@/features/account/account-shell";
import { useSession } from "@/features/session/use-session";
import { Link } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { AccountAnchor } from "./header-actions";

/** The phone tab bar's Account item. A signed-in customer gets a popup of the account pages and
 * Log out, above the bar on the right (the account pages' side menu is not shown on phones);
 * guests still go to sign in and staff to the admin. `tone` colours the item: active or not;
 * `pathname` is null until the current page is known (the tab bar's fallback). */
export function AccountTab({ className, tone, pathname }: { className: string; tone: (active: boolean) => string; pathname: string | null }) {
  const t = useTranslations("store.tabs");
  const { data: user } = useSession();
  const onAccount = Boolean(pathname?.startsWith("/account"));
  if (!user?.is_customer || pathname === null) {
    return (
      <AccountAnchor className={cx(className, tone(onAccount))}>
        <User size={22} aria-hidden="true" />
        {t("account")}
      </AccountAnchor>
    );
  }
  return <AccountPopup className={className} tone={tone} pathname={pathname} />;
}

const ROW = "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-base font-medium no-underline";

/** A disclosure: the Account button opens and closes the list. A tap outside it, Escape (focus
 * goes back to the button) or choosing a page closes it. */
function AccountPopup({ className, tone, pathname }: { className: string; tone: (active: boolean) => string; pathname: string }) {
  const t = useTranslations("store.tabs");
  const ta = useTranslations("store.account");
  const logOut = useLogOut();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const down = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className={cx(className, tone(open || pathname.startsWith("/account")))}
      >
        <User size={22} aria-hidden="true" />
        {t("account")}
      </button>
      <div
        ref={panel}
        id={id}
        hidden={!open}
        className="fixed right-2 bottom-[calc(4rem+0.5rem)] z-50 max-h-[calc(100dvh-5rem)] w-60 max-w-[calc(100vw-1rem)] overflow-y-auto overscroll-contain rounded-xl border border-bd bg-card p-2 shadow-sh2"
      >
        <nav aria-label={ta("navLabel")} className="flex flex-col gap-0.5">
          {ACCOUNT_LINKS.map(({ href, key, Icon }) => {
            const on = isAccountLinkActive(href, pathname);
            return (
              <Link
                key={href}
                href={href}
                aria-current={on ? "page" : undefined}
                onClick={() => setOpen(false)}
                className={cx(ROW, on ? "bg-light text-pri-h" : "text-tx hover:bg-page hover:text-pri-h")}
              >
                <Icon size={18} aria-hidden="true" />
                {ta(`nav.${key}`)}
              </Link>
            );
          })}
          <SellerDashboardLink enabled className={cx(ROW, "text-tx hover:bg-page hover:text-pri-h")} onClick={() => setOpen(false)} />
          <hr className="hr my-1" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              void logOut();
            }}
            className={cx(ROW, "cursor-pointer border-0 bg-transparent text-left text-err-fg hover:bg-err-bg")}
          >
            <LogOut size={18} aria-hidden="true" />
            {ta("nav.logout")}
          </button>
        </nav>
      </div>
    </>
  );
}
