"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, CheckCheck, ChevronRight, ClipboardList, Headset, MessageSquare, Search, ShoppingBag, Wrench, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { browserApi } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import { StaffAccessProvider, useStaffAccess, type ClientStaffAccess } from "./access";
import { activeNav, canOpen, NAV, type NavKey } from "./nav";
import { PanelShell, POPUP, TOP_BUTTON, useDismiss, type PanelGroup } from "./panel-shell";

/** AdminSidebar.dc.html + AdminTopbar.dc.html around every admin page, in the frame the seller
 * dashboard shares (panel-shell.tsx). */
export function AdminShell({ access, children }: { access: ClientStaffAccess; children: ReactNode }) {
  return (
    <StaffAccessProvider access={access}>
      <AdminFrame>{children}</AdminFrame>
    </StaffAccessProvider>
  );
}

function AdminFrame({ children }: { children: ReactNode }) {
  const t = useTranslations("admin.shell");
  const access = useStaffAccess();
  const pathname = usePathname();
  const active = activeNav(pathname);
  const counts = useNavCounts();
  const groups: PanelGroup[] = NAV.map(({ group, items }) => ({
    key: group,
    label: t(`groups.${group}`),
    links: items
      .filter((item) => canOpen(access.permissions, item.anyOf))
      .map(({ key, href, Icon }) => ({ key, href, Icon, label: t(`nav.${key}`), count: counts[key], active: key === active })),
  }));
  return (
    <PanelShell
      home="/admin"
      homeLabel={t("home")}
      panelLabel={t("panel")}
      navLabel={t("navLabel")}
      groups={groups}
      person={{ name: access.fullName, subtitle: t(`roles.${access.role}`) }}
      cookiePath="/admin"
      topbar={{ start: <AdminSearch />, end: <Notifications /> }}
    >
      {children}
    </PanelShell>
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

/** AdminTopbar.dc.html's search (Ctrl+K). */
function AdminSearch() {
  const t = useTranslations("admin.shell");
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
