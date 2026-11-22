"use client";

import { CheckCheck, ChevronDown, LogOut, Menu, X, type LucideIcon } from "lucide-react";
import NextLink from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { Flag } from "@/components/store/flags";
import { Logo } from "@/components/store/logo";
import { ADMIN_LOCALES, saveAdminLocale, type PanelPath } from "@/i18n/admin-locale";
import { initials } from "@/lib/auth";
import { cx } from "@/lib/cx";

/** The frame the admin and the seller dashboard share (AdminSidebar.dc.html + AdminTopbar.dc.html,
 * ADR-014 phase 4): the navy sidebar with its groups, the top bar, the language menu and the
 * signed-in person. Below 1024 px the sidebar becomes a panel opened from the top bar. Each
 * panel supplies its own links, labels and top-bar tools. */

export type PanelLink = { key: string; href: string; Icon: LucideIcon; label: string; count?: number; active: boolean };
export type PanelGroup = { key: string; label: string; links: PanelLink[] };
export type PanelPerson = { name: string; subtitle: string };

export function PanelShell({
  home,
  homeLabel,
  panelLabel,
  navLabel,
  groups,
  person,
  topbar,
  cookiePath,
  children,
}: {
  home: string;
  homeLabel: string;
  panelLabel: string;
  navLabel: string;
  groups: PanelGroup[];
  person: PanelPerson;
  /** The top bar's own tools (search, notifications), before the language menu. */
  topbar?: { start?: ReactNode; end?: ReactNode };
  /** Where the language cookie is kept. */
  cookiePath: PanelPath;
  children: ReactNode;
}) {
  const t = useTranslations("admin.shell");
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
  const [lastPath, setLastPath] = useState(pathname);
  if (pathname !== lastPath) {
    // A link in the panel was followed: close it.
    setLastPath(pathname);
    setMenuOpen(false);
  }
  const sidebar = (onClose?: () => void) => (
    <Sidebar home={home} homeLabel={homeLabel} panelLabel={panelLabel} navLabel={navLabel} groups={groups} person={person} onClose={onClose} />
  );

  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        {t("skipToContent")}
      </a>
      <div className="flex min-h-dvh bg-page">
        <aside className="sticky top-0 hidden h-dvh w-60 flex-none overflow-y-auto bg-deep text-white lg:flex">{sidebar()}</aside>
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button type="button" aria-label={t("closeMenu")} className="absolute inset-0 cursor-default border-0 bg-overlay" onClick={() => setMenuOpen(false)} />
            <aside id="admin-menu" className="relative flex h-full w-72 max-w-[85vw] overflow-y-auto bg-deep text-white">
              {sidebar(() => setMenuOpen(false))}
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex min-h-[68px] flex-wrap items-center gap-5 border-b border-bd bg-white px-7 py-3 max-md:gap-3 max-md:px-4">
            <button
              type="button"
              onClick={() => setMenuOpen(true)}
              aria-label={t("openMenu")}
              aria-expanded={menuOpen}
              aria-controls="admin-menu"
              className="flex size-10 cursor-pointer items-center justify-center rounded-lg border border-bd bg-white text-tx transition-colors duration-150 hover:bg-page lg:hidden"
            >
              <Menu size={20} aria-hidden="true" />
            </button>
            {topbar?.start}
            <span className="grow max-md:hidden" />
            <div className="flex items-center gap-1.5 max-md:ml-auto">
              <LanguageMenu cookiePath={cookiePath} />
              {topbar?.end}
            </div>
            <div className="flex items-center gap-2.5 border-l border-bd pl-5 max-sm:hidden">
              <span aria-hidden="true" className="inline-flex size-[38px] flex-none items-center justify-center rounded-full bg-pri text-xs font-semibold text-white ring-2 ring-light">
                {initials(person.name)}
              </span>
              <span className="flex flex-col">
                <b className="text-sm font-medium">{person.name}</b>
                <span className="text-cap text-tx2">{person.subtitle}</span>
              </span>
            </div>
          </header>
          <main id="main" className="flex flex-col gap-5 p-7 max-md:p-4">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}

function Sidebar({
  home,
  homeLabel,
  panelLabel,
  navLabel,
  groups,
  person,
  onClose,
}: {
  home: string;
  homeLabel: string;
  panelLabel: string;
  navLabel: string;
  groups: PanelGroup[];
  person: PanelPerson;
  onClose?: () => void;
}) {
  const t = useTranslations("admin.shell");
  return (
    <div className="flex min-h-full w-full flex-col">
      <div className="flex items-start justify-between gap-2 px-5 pt-[18px] pb-4">
        <div className="flex flex-col gap-1.5">
          <NextLink href={home} aria-label={homeLabel} className="block w-fit rounded-lg bg-white px-2.5 py-1.5">
            <Logo height={34} alt="" />
          </NextLink>
          <span className="text-cap text-odm">{panelLabel}</span>
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
      <nav aria-label={navLabel} className="flex flex-col gap-3.5 px-3 pt-1 pb-4">
        {groups
          .filter((g) => g.links.length > 0)
          .map(({ key, label, links }) => (
            <div key={key} className="flex flex-col gap-0.5">
              <span className="px-3 pb-1 text-[11px] font-semibold tracking-[0.06em] text-odm uppercase">{label}</span>
              {links.map(({ key: linkKey, href, Icon, label: text, count, active: on }) => (
                <NextLink
                  key={linkKey}
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
                  <span className="grow">{text}</span>
                  {count ? (
                    <span className="min-w-[20px] rounded-full bg-err px-1.5 text-center text-[11px] leading-5 font-semibold text-white tabular-nums ring-2 ring-deep">
                      {count}
                      <span className="sr-only"> ({t("newCount", { count })})</span>
                    </span>
                  ) : null}
                </NextLink>
              ))}
            </div>
          ))}
      </nav>
      <span className="grow" />
      <div className="mx-3 mb-3 flex items-center gap-2.5 rounded-xl border border-white/10 bg-white/6 px-3 py-3">
        <span aria-hidden="true" className="inline-flex size-9 flex-none items-center justify-center rounded-full bg-pri text-xs font-semibold text-white ring-2 ring-white/15">
          {initials(person.name)}
        </span>
        <span className="flex min-w-0 grow flex-col">
          <b className="truncate text-sm font-medium">{person.name}</b>
          <span className="text-cap text-odm">{person.subtitle}</span>
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

/** Closes a popup on a click outside it or on Escape (which returns focus to its button). */
export function useDismiss(open: boolean, close: () => void, box: RefObject<HTMLElement | null>, button: RefObject<HTMLButtonElement | null>) {
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

export const POPUP = "absolute top-[calc(100%+8px)] right-0 z-40 m-0 rounded-xl border border-bd bg-white shadow-sh2";
export const TOP_BUTTON =
  "flex h-10 cursor-pointer items-center gap-1.5 rounded-lg border border-transparent bg-transparent px-2.5 text-sm font-medium text-tx transition-colors duration-150 hover:bg-page aria-expanded:border-bd aria-expanded:bg-page motion-reduce:transition-none";

/** AdminTopbar.dc.html "EN ▾": the panel's language. The choice is kept in a cookie for the
 * panel's path and the page reloads its messages from the server. */
function LanguageMenu({ cookiePath }: { cookiePath: PanelPath }) {
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
    saveAdminLocale(next, cookiePath);
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
