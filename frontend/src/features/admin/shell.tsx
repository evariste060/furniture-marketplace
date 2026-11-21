"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, CheckCheck, ChevronDown, ChevronRight, ClipboardList, Headset, LogOut, Menu, MessageSquare, Search, ShoppingBag, Wrench, X, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { Flag } from "@/components/store/flags";
import { Logo } from "@/components/store/logo";
import { ADMIN_LOCALES, saveAdminLocale } from "@/i18n/admin-locale";
import { browserApi } from "@/lib/api/client";
import { initials } from "@/lib/auth";
import { cx } from "@/lib/cx";
import { StaffAccessProvider, useStaffAccess, type ClientStaffAccess } from "./access";
import { activeNav, canOpen, NAV, type NavKey } from "./nav";

/** AdminSidebar.dc.html + AdminTopbar.dc.html around every admin page. Below 1024 px the sidebar
 * becomes a panel opened from the top bar (the designs show desktop only). */
export function AdminShell({ access, children }: { access: ClientStaffAccess; children: ReactNode }) {
  const t = useTranslations("admin.shell");
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
  const [lastPath, setLastPath] = useState(pathname);
  if (pathname !== lastPath) {
    // A link in the panel was followed: close it.
    setLastPath(pathname);
    setMenuOpen(false);
  }

  return (
    <StaffAccessProvider access={access}>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        {t("skipToContent")}
      </a>
      <div className="flex min-h-dvh bg-page">
        <aside className="sticky top-0 hidden h-dvh w-60 flex-none overflow-y-auto bg-deep text-white lg:flex">
          <Sidebar />
        </aside>
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button type="button" aria-label={t("closeMenu")} className="absolute inset-0 cursor-default border-0 bg-overlay" onClick={() => setMenuOpen(false)} />
            <aside id="admin-menu" className="relative flex h-full w-72 max-w-[85vw] overflow-y-auto bg-deep text-white">
              <Sidebar onClose={() => setMenuOpen(false)} />
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar menuOpen={menuOpen} onMenu={() => setMenuOpen(true)} />
          <main id="main" className="flex flex-col gap-5 p-7 max-md:p-4">
            {children}
          </main>
        </div>
      </div>
    </StaffAccessProvider>
  );
}

function useNavCounts(): Partial<Record<NavKey, number>> {
  const { can } = useStaffAccess();
  const orders = useQuery({
    queryKey: ["admin", "count", "orders-received"],
    enabled: can("orders:read"),
    queryFn: async () =>
      (
        await browserApi.GET("/api/v1/staff/orders", {
          params: { query: { status: "received", size: 1 } },
        })
      ).data?.total ?? 0,
  });
  const reviews = useQuery({
    queryKey: ["admin", "count", "reviews-pending"],
    enabled: can("reviews:moderate"),
    queryFn: async () =>
      (
        await browserApi.GET("/api/v1/staff/reviews", {
          params: { query: { status: "pending", size: 1 } },
        })
      ).data?.total ?? 0,
  });
  const quotes = useQuery({
    queryKey: ["admin", "count", "quotes-new"],
    enabled: can("quotes:manage"),
    queryFn: async () =>
      (
        await browserApi.GET("/api/v1/staff/quote-requests", {
          params: { query: { status: "new", size: 1 } },
        })
      ).data?.total ?? 0,
  });
  const serviceRequests = useQuery({
    queryKey: ["admin", "count", "service-requests-new"],
    enabled: can("services:read"),
    queryFn: async () =>
      (
        await browserApi.GET("/api/v1/staff/service-requests", {
          params: { query: { status: "new", size: 1 } },
        })
      ).data?.total ?? 0,
  });
  const messages = useQuery({
    queryKey: ["admin", "count", "support-open"],
    enabled: can("support:read"),
    queryFn: async () =>
      (
        await browserApi.GET("/api/v1/staff/support-threads", {
          params: { query: { status: "open", size: 1 } },
        })
      ).data?.total ?? 0,
  });
  return { orders: orders.data, reviews: reviews.data, quotes: quotes.data, serviceRequests: serviceRequests.data, messages: messages.data };
}

function Sidebar({ onClose }: { onClose?: () => void }) {
  const t = useTranslations("admin.shell");
  const access = useStaffAccess();
  const pathname = usePathname();
  const active = activeNav(pathname);
  const counts = useNavCounts();

  return (
    <div className="flex min-h-full w-full flex-col">
      <div className="flex items-start justify-between gap-2 px-5 pt-[18px] pb-4">
        <div className="flex flex-col gap-1.5">
          <NextLink href="/admin" aria-label={t("home")} className="block w-[150px] rounded-lg bg-white px-2 py-1">
            <Logo height={50} alt="" eager className="h-auto! w-full" />
          </NextLink>
          <span className="text-cap text-odm">{t("panel")}</span>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t("closeMenu")}
            className="flex size-9 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-odm hover:text-white"
          >
            <X size={20} aria-hidden="true" />
          </button>
        )}
      </div>
      <nav aria-label={t("navLabel")} className="flex flex-col gap-3.5 px-3 pt-1 pb-4">
        {NAV.map(({ group, items }) => {
          const visible = items.filter((item) => canOpen(access.permissions, item.anyOf));
          if (visible.length === 0) return null;
          return (
            <div key={group} className="flex flex-col gap-0.5">
              <span className="px-3 pb-1 text-[11px] font-semibold tracking-[0.06em] text-odm uppercase">{t(`groups.${group}`)}</span>
              {visible.map(({ key, href, Icon }) => {
                const on = key === active;
                const count = counts[key];
                return (
                  <NextLink
                    key={key}
                    href={href}
                    aria-current={on ? "page" : undefined}
                    className={cx(
                      "group flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium no-underline transition-colors duration-150 focus-visible:outline-white motion-reduce:transition-none",
                      on ? "bg-pri text-white shadow-sh hover:text-white" : "text-odm hover:bg-white/8 hover:text-white",
                    )}
                  >
                    <Icon
                      size={18}
                      aria-hidden="true"
                      className={cx("flex-none transition-colors duration-150 motion-reduce:transition-none", on ? "text-white" : "text-odm group-hover:text-white")}
                    />
                    <span className="grow">{t(`nav.${key}`)}</span>
                    {count ? (
                      <span className="min-w-[20px] rounded-full bg-err px-1.5 text-center text-[11px] leading-5 font-semibold text-white tabular-nums ring-2 ring-deep">
                        {count}
                        <span className="sr-only"> ({t("newCount", { count })})</span>
                      </span>
                    ) : null}
                  </NextLink>
                );
              })}
            </div>
          );
        })}
      </nav>
      <span className="grow" />
      <div className="mx-3 mb-3 flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/6 px-3 py-3">
        <span aria-hidden="true" className="inline-flex size-9 flex-none items-center justify-center rounded-full bg-pri text-xs font-semibold text-white ring-2 ring-white/15">
          {initials(access.fullName)}
        </span>
        <span className="flex min-w-0 grow flex-col">
          <b className="truncate text-sm font-medium">{access.fullName}</b>
          <span className="text-cap text-odm">{t(`roles.${access.role}`)}</span>
        </span>
        <LogoutButton />
      </div>
    </div>
  );
}

function LogoutButton() {
  const t = useTranslations("admin.shell");
  const [pending, setPending] = useState(false);
  async function logOut() {
    setPending(true);
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.assign("/login");
  }
  return (
    <button
      type="button"
      onClick={logOut}
      disabled={pending}
      aria-label={t("logout")}
      title={t("logout")}
      className="flex size-8 flex-none cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-odm transition-colors duration-150 hover:bg-white/10 hover:text-white focus-visible:outline-white disabled:opacity-60 motion-reduce:transition-none"
    >
      <LogOut size={18} aria-hidden="true" />
    </button>
  );
}

/** Orders by number or phone, otherwise products by name, model or SKU (the API's own searches). */
export function adminSearchTarget(query: string): string | null {
  const q = query.trim();
  if (!q) return null;
  const digits = q.replace(/[\s()-]/g, "");
  const isPhone = /^(\+?250|0)7\d{8}$/.test(digits);
  const isOrder = /^ORD-/i.test(q) || /^\d{6}-[A-Z0-9]{1,6}$/i.test(q);
  const params = new URLSearchParams({ q });
  return isPhone || isOrder ? `/admin/orders?${params}` : `/admin/products?${params}`;
}

function Topbar({ menuOpen, onMenu }: { menuOpen: boolean; onMenu: () => void }) {
  const t = useTranslations("admin.shell");
  const access = useStaffAccess();
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = adminSearchTarget(input.current?.value ?? "");
    if (target) router.push(target);
  }

  return (
    <header className="sticky top-0 z-30 flex min-h-[68px] flex-wrap items-center gap-5 border-b border-bd bg-white px-7 py-3 max-md:gap-3 max-md:px-4">
      <button
        type="button"
        onClick={onMenu}
        aria-label={t("openMenu")}
        aria-expanded={menuOpen}
        aria-controls="admin-menu"
        className="flex size-10 cursor-pointer items-center justify-center rounded-lg border border-bd bg-white text-tx transition-colors duration-150 hover:bg-page lg:hidden"
      >
        <Menu size={20} aria-hidden="true" />
      </button>
      <form
        role="search"
        onSubmit={onSubmit}
        className="flex h-[42px] max-w-[560px] min-w-0 flex-[1_1_280px] items-center gap-2.5 rounded-lg border border-transparent bg-page px-3.5 text-tx2 transition-[background-color,border-color,box-shadow] duration-150 hover:not-focus-within:border-bd focus-within:border-pri focus-within:bg-white focus-within:shadow-focus motion-reduce:transition-none"
      >
        <Search size={18} aria-hidden="true" />
        <input
          ref={input}
          type="search"
          aria-label={t("searchLabel")}
          placeholder={t("searchPlaceholder")}
          className="min-w-0 flex-1 border-0 bg-transparent text-sm text-tx outline-none placeholder:text-tx2"
        />
        <span aria-hidden="true" className="rounded-md border border-bd bg-white px-1.5 py-0.5 text-cap font-medium text-tx2 shadow-sh max-sm:hidden">
          {t("searchShortcut")}
        </span>
      </form>
      <span className="grow max-md:hidden" />
      <div className="flex items-center gap-1.5 max-md:ml-auto">
        <LanguageMenu />
        <Notifications />
      </div>
      <div className="flex items-center gap-2.5 border-l border-bd pl-5 max-sm:hidden">
        <span aria-hidden="true" className="inline-flex size-[38px] flex-none items-center justify-center rounded-full bg-pri text-xs font-semibold text-white ring-2 ring-light">
          {initials(access.fullName)}
        </span>
        <span className="flex flex-col">
          <b className="text-sm font-medium">{access.fullName}</b>
          <span className="text-cap text-tx2">{t(`roles.${access.role}`)}</span>
        </span>
      </div>
    </header>
  );
}

/** Closes a popup on a click outside it or on Escape (which returns focus to its button). */
function useDismiss(open: boolean, close: () => void, box: RefObject<HTMLElement | null>, button: RefObject<HTMLButtonElement | null>) {
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      close();
      button.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close, box, button]);
}

const POPUP = "absolute top-[calc(100%+8px)] right-0 z-40 m-0 rounded-xl border border-bd bg-white shadow-sh2";
const TOP_BUTTON =
  "flex h-10 cursor-pointer items-center gap-1.5 rounded-lg border border-transparent bg-transparent px-2.5 text-sm font-medium text-tx transition-colors duration-150 hover:bg-page aria-expanded:border-bd aria-expanded:bg-page motion-reduce:transition-none";

/** AdminTopbar.dc.html "EN ▾": the admin's language. The choice is kept in a cookie for /admin and
 * the page reloads its messages from the server. */
function LanguageMenu() {
  const t = useTranslations("admin.shell");
  const locale = useLocale() as (typeof ADMIN_LOCALES)[number];
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();
  useDismiss(open, () => setOpen(false), box, button);

  function choose(next: (typeof ADMIN_LOCALES)[number]) {
    setOpen(false);
    if (next === locale) return;
    saveAdminLocale(next);
    router.refresh();
  }

  return (
    <div ref={box} className="relative">
      <button ref={button} type="button" aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)} className={TOP_BUTTON}>
        <Flag locale={locale} />
        <span className="sr-only">{t("languageOf", { language: t(`languages.${locale}`) })}, </span>
        <span aria-hidden="true">{locale.toUpperCase()}</span>
        <ChevronDown size={14} aria-hidden="true" className="text-tx2" />
      </button>
      <ul id={listId} hidden={!open} aria-label={t("language")} className={cx(POPUP, "w-48 list-none flex-col p-1 [&:not([hidden])]:flex")}>
        {ADMIN_LOCALES.map((l) => (
          <li key={l}>
            <button
              type="button"
              lang={l}
              aria-current={l === locale ? "true" : undefined}
              onClick={() => choose(l)}
              className={cx(
                "flex w-full cursor-pointer items-center gap-2.5 rounded-lg border-0 px-3 py-2 text-left text-sm",
                l === locale ? "bg-light font-semibold text-pri-h" : "bg-transparent text-tx hover:bg-page",
              )}
            >
              <Flag locale={l} />
              <span className="flex-1">{t(`languages.${l}`)}</span>
              {l === locale && <CheckCheck size={15} aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What can be waiting for the signed-in staff member, from the same counts as the sidebar's
 * badges (so only the areas their role can open). */
const WAITING: { key: "orders" | "messages" | "quotes" | "serviceRequests" | "reviews"; href: string; Icon: LucideIcon; tone: string }[] = [
  { key: "orders", href: "/admin/orders?status=received", Icon: ShoppingBag, tone: "bg-light text-pri" },
  { key: "messages", href: "/admin/messages", Icon: Headset, tone: "bg-warn-bg text-warn-tx" },
  { key: "quotes", href: "/admin/quotes", Icon: ClipboardList, tone: "bg-ok-bg text-ok-tx" },
  { key: "serviceRequests", href: "/admin/service-requests?status=new", Icon: Wrench, tone: "bg-light text-pri-h" },
  { key: "reviews", href: "/admin/reviews", Icon: MessageSquare, tone: "bg-pur-bg text-pur" },
];

/** AdminTopbar.dc.html's bell: a red count of everything waiting, opening a list of links to it. */
function Notifications() {
  const t = useTranslations("admin.shell");
  const counts = useNavCounts();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const pathname = usePathname();
  const [lastPath, setLastPath] = useState(pathname);
  if (pathname !== lastPath) {
    // A link in the list was followed: close it.
    setLastPath(pathname);
    setOpen(false);
  }
  useDismiss(open, () => setOpen(false), box, button);
  const items = WAITING.filter((w) => counts[w.key] !== undefined).map((w) => ({ ...w, count: counts[w.key] ?? 0 }));
  const total = items.reduce((sum, w) => sum + w.count, 0);
  const waiting = items.filter((w) => w.count > 0);

  return (
    <div ref={box} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={t("notifications", { count: total })}
        onClick={() => setOpen((o) => !o)}
        className={cx(TOP_BUTTON, "relative w-10 justify-center px-0 text-tx2 hover:text-tx")}
      >
        <Bell size={21} aria-hidden="true" />
        {total > 0 && (
          <span aria-hidden="true" className="absolute top-0.5 right-0 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-err px-1 text-cap font-semibold text-white tabular-nums ring-2 ring-white">
            {total > 99 ? "99+" : total}
          </span>
        )}
      </button>
      <div id={panelId} hidden={!open} role="region" aria-label={t("waitingTitle")} className={cx(POPUP, "w-[340px] max-w-[calc(100vw-32px)] flex-col overflow-hidden [&:not([hidden])]:flex")}>
        <div className="flex items-center justify-between gap-3 border-b border-bd px-4 py-3">
          <b className="text-sm font-semibold">{t("waitingTitle")}</b>
          {total > 0 && <span className="rounded-full bg-err-bg px-2 py-0.5 text-cap font-semibold text-err-tx tabular-nums">{t("newCount", { count: total })}</span>}
        </div>
        {waiting.length === 0 ? (
          <div className="flex flex-col items-center gap-2.5 px-6 py-8 text-center">
            <span aria-hidden="true" className="flex size-11 items-center justify-center rounded-full bg-ok-bg text-ok-tx">
              <CheckCheck size={20} />
            </span>
            <p className="m-0 text-sm text-tx2">{t("waitingEmpty")}</p>
          </div>
        ) : (
          <ul className="m-0 flex list-none flex-col p-1.5">
            {waiting.map(({ key, href, Icon, tone, count }) => (
              <li key={key}>
                <NextLink href={href} onClick={() => setOpen(false)} className="group flex items-center gap-3 rounded-lg px-2.5 py-2.5 text-tx no-underline hover:bg-page hover:text-tx">
                  <span aria-hidden="true" className={cx("flex size-9 flex-none items-center justify-center rounded-lg", tone)}>
                    <Icon size={18} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <b className="text-sm font-semibold">{t(`waiting.${key}`, { count })}</b>
                    <span className="text-cap text-tx2">{t(`nav.${key}`)}</span>
                  </span>
                  <ChevronRight size={16} aria-hidden="true" className="flex-none text-bd2 group-hover:text-pri" />
                </NextLink>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
