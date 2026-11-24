"use client";

import { ChevronDown, Heart, Menu, Moon, ShoppingCart, Sun, Truck, User } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Suspense, useEffect, useId, useRef, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { CountBadge } from "@/components/ui/badge";
import { useCart } from "@/features/cart/use-cart";
import { firstName, useSession } from "@/features/session/use-session";
import { useWishlistIds } from "@/features/wishlist/use-wishlist";
import { Link, usePathname } from "@/i18n/navigation";
import { routing, type Locale } from "@/i18n/routing";
import { cx } from "@/lib/cx";
import { useTheme } from "@/lib/theme";
import { Flag } from "./flags";
import { useMenuState } from "./menu-state";

/** The current page with its query, for switching language on the same page. */
function useCurrentHref(): string {
  const pathname = usePathname();
  const [search, setSearch] = useState("");
  // The query is read after mount so cached pages need no Suspense boundary for it.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setSearch(window.location.search), [pathname]);
  return `${pathname}${search}`;
}

/** Renders `render(href)` with the current page's href. Pages with a dynamic segment know their
 * URL only at request time, so the build's shell uses the home page and the real link streams in
 * with the page. */
function WithCurrentHref({ render }: { render: (href: string) => ReactNode }) {
  return (
    <Suspense fallback={render("/")}>
      <CurrentHref render={render} />
    </Suspense>
  );
}

function CurrentHref({ render }: { render: (href: string) => ReactNode }) {
  return render(useCurrentHref());
}

/** Header "EN ▾": a small menu with the two languages. */
export function LanguageMenu() {
  return <WithCurrentHref render={(href) => <LanguageMenuView href={href} />} />;
}

function LanguageMenuView({ href }: { href: string }) {
  const t = useTranslations("store");
  const locale = useLocale() as Locale;
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const listId = useId();
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((o) => !o)}
        className="flex cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 text-sm font-medium text-tx"
      >
        <Flag locale={locale} />
        <span className="sr-only">{t("header.language", { name: t(`languages.${locale}`) })}, </span>
        {locale.toUpperCase()}
        <ChevronDown size={14} aria-hidden="true" className="text-mut" />
      </button>
      <ul
        id={listId}
        hidden={!open}
        className="absolute top-8 right-0 z-30 m-0 w-40 list-none flex-col rounded-lg border border-bd bg-card p-1 shadow-sh2 [&:not([hidden])]:flex"
      >
        {routing.locales.map((l) => (
          <li key={l}>
            <Link
              href={href}
              locale={l}
              lang={l}
              aria-current={l === locale ? "true" : undefined}
              onClick={() => setOpen(false)}
              className={cx(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm",
                l === locale ? "bg-light font-semibold text-pri-h" : "text-tx hover:bg-page",
              )}
            >
              <Flag locale={l} />
              {t(`languages.${l}`)}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Light / dark mode (SC-07): an icon button in the header's actions row, and a labelled row in
 * the phone menu (`withLabel`). The choice applies to the whole site and is kept in this browser. */
export function ThemeToggle({ withLabel = false }: { withLabel?: boolean }) {
  const t = useTranslations("store.header");
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const label = t(dark ? "lightMode" : "darkMode");
  const Icon = dark ? Sun : Moon;
  if (withLabel) {
    return (
      <button
        type="button"
        onClick={toggle}
        aria-pressed={dark}
        className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-bd bg-card px-3 py-1.5 text-cap font-semibold text-tx2 hover:text-tx"
      >
        <Icon size={15} aria-hidden="true" />
        {label}
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="flex size-9 flex-none cursor-pointer items-center justify-center rounded-full border-0 bg-transparent text-tx hover:bg-subtle hover:text-pri-fg"
    >
      <Icon size={19} aria-hidden="true" />
    </button>
  );
}

/** The menu's EN | RW switch (MobileMenu.dc.html). */
export function LanguageToggle() {
  return <WithCurrentHref render={(href) => <LanguageToggleView href={href} />} />;
}

function LanguageToggleView({ href }: { href: string }) {
  const t = useTranslations("store");
  const locale = useLocale() as Locale;
  return (
    <span className="flex overflow-hidden rounded-lg border border-bd">
      {routing.locales.map((l) => (
        <Link
          key={l}
          href={href}
          locale={l}
          lang={l}
          aria-current={l === locale ? "true" : undefined}
          className={cx(
            "px-3 py-1.5 text-cap font-semibold",
            l === locale ? "bg-pri text-white hover:text-white" : "bg-card text-tx2 hover:text-tx",
          )}
        >
          {l.toUpperCase()}
          <span className="sr-only"> {t(`languages.${l}`)}</span>
        </Link>
      ))}
    </span>
  );
}

/** Where the account link goes: sign in, the customer's account, or the admin for staff. */
export function useAccountLink(): { href: string; external: boolean; label: string | null; signedIn: boolean } {
  const { data: user } = useSession();
  if (!user) return { href: "/login", external: false, label: null, signedIn: false };
  if (user.is_staff) return { href: "/admin", external: true, label: firstName(user.full_name), signedIn: true };
  return { href: "/account", external: false, label: firstName(user.full_name), signedIn: true };
}

export function AccountAnchor({
  className,
  children,
  onClick,
  "aria-label": ariaLabel,
}: {
  className?: string;
  children: ReactNode;
  onClick?: () => void;
  "aria-label"?: string;
}) {
  const { href, external } = useAccountLink();
  // The admin is outside the storefront's locale routing, so it gets a plain link.
  return external ? (
    <a href={href} className={className} aria-label={ariaLabel} onClick={onClick}>
      {children}
    </a>
  ) : (
    <Link href={href} className={className} aria-label={ariaLabel} onClick={onClick}>
      {children}
    </Link>
  );
}

const HLINK = "flex items-center gap-2 text-sm font-medium whitespace-nowrap text-tx hover:text-pri-fg";

export function AccountLink() {
  const t = useTranslations("store.header");
  const { label } = useAccountLink();
  return (
    <AccountAnchor className={HLINK}>
      <User size={22} aria-hidden="true" />
      <span className="flex flex-col max-lg:sr-only">
        <span className="text-cap font-normal text-mut">{t("myAccount")}</span>
        <span>{label ?? t("signIn")}</span>
      </span>
    </AccountAnchor>
  );
}

export function AccountIconLink() {
  const t = useTranslations("store.header");
  return (
    <AccountAnchor aria-label={t("account")} className="flex size-10 w-9 items-center justify-center text-tx2">
      <User size={22} aria-hidden="true" />
    </AccountAnchor>
  );
}

/** "Track order" in the actions row (owner, 2026-11-17; it was on the category bar). */
export function TrackOrderLink() {
  const t = useTranslations("store.header");
  return (
    <Link href="/track" className={HLINK}>
      <Truck size={22} aria-hidden="true" />
      <span className="ml-1 max-lg:sr-only">{t("trackOrder")}</span>
    </Link>
  );
}

export function WishlistLink() {
  const t = useTranslations("store.header");
  const { data } = useWishlistIds();
  const count = data?.count ?? 0;
  return (
    <Link href="/account/wishlist" className={HLINK}>
      <span className="relative inline-flex">
        <Heart size={22} aria-hidden="true" />
        {count > 0 && (
          <CountBadge aria-hidden="true" className="absolute -top-2 -right-2.5">
            {count}
          </CountBadge>
        )}
      </span>
      <span className={cx("max-lg:sr-only", count ? "ml-1" : undefined)}>{t("wishlist")}</span>
      {count > 0 && <span className="sr-only">{t("itemCount", { count })}</span>}
    </Link>
  );
}

function useCartCount(): number {
  const { data } = useCart();
  return data?.item_count ?? 0;
}

export function CartLink() {
  const t = useTranslations("store.header");
  const count = useCartCount();
  return (
    <Link href="/cart" className={HLINK}>
      <span className="relative inline-flex">
        <ShoppingCart size={24} aria-hidden="true" />
        <CountBadge aria-hidden="true" className="absolute -top-2 -right-2.5">
          {count}
        </CountBadge>
      </span>
      <span className="ml-1 max-lg:sr-only">{t("cart")}</span>
      <span className="sr-only">{t("itemCount", { count })}</span>
    </Link>
  );
}

export function CartIconLink() {
  const t = useTranslations("store.header");
  const count = useCartCount();
  return (
    <Link
      href="/cart"
      aria-label={t("cartCount", { count })}
      className="relative flex size-10 w-9 items-center justify-center text-tx2"
    >
      <ShoppingCart size={22} aria-hidden="true" />
      <CountBadge className="absolute top-0 -right-0.5">{count}</CountBadge>
    </Link>
  );
}

/** The mobile header's ☰: opens the category drawer (desktop "All Categories" links to /products). */
export function MenuButton() {
  const t = useTranslations();
  const { setOpen } = useMenuState();
  return (
    <button
      type="button"
      aria-label={t("ui.openMenu")}
      aria-haspopup="dialog"
      onClick={() => setOpen(true)}
      className="flex size-10 w-9 cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-tx2"
    >
      <Menu size={22} aria-hidden="true" />
    </button>
  );
}

/** The store header's scroll behaviour and height. At the top of the page the whole header (the
 * actions row and the blue store menu) sits in the page and scrolls away with it. Once it has
 * scrolled out of view, it slides back in and stays pinned to the top as one block (data-compact
 * on <header>: sticky), so the actions row and the store menu never separate (SC-09). Back at the
 * top of the page it returns to its place.
 *
 * Also publishes the header's height as --store-header-h on <html>, so the listing filters stick
 * right under it (the height also changes when the desktop row wraps on tablets). globals.css
 * holds a per-breakpoint fallback for the first paint. */
export function HeaderHeight() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const header = ref.current?.closest("header");
    if (!header) return;
    const root = document.documentElement;
    let compact = false;
    let frame = 0;
    // Where the header starts: under the announcement bar.
    const start = () => (header.previousElementSibling as HTMLElement | null)?.offsetHeight ?? 0;
    const publish = () => root.style.setProperty("--store-header-h", `${header.offsetHeight}px`);
    const update = () => {
      frame = 0;
      const y = window.scrollY;
      // Pinned once the full header is out of view; in place again only back where it starts
      // (the gap between the two keeps it from flickering at the edge).
      const next = compact ? y > start() : y > start() + header.offsetHeight;
      if (next === compact) return;
      compact = next;
      // The header keeps its place in the page either way (sticky), so nothing below it moves.
      header.toggleAttribute("data-compact", compact);
      publish();
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const observer = new ResizeObserver(publish);
    observer.observe(header);
    window.addEventListener("scroll", onScroll, { passive: true });
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
      root.style.removeProperty("--store-header-h");
    };
  }, []);
  return <span ref={ref} hidden />;
}

type NavLinkProps = { href: string; children: ReactNode; tone?: "default" | "deal" | "muted"; className?: string };

/** A category-nav link on the blue nav bar: white, on a slightly rounded --pri-h block on its own
 * pages, the same block hovering shows (white on --pri-h is 6.6:1; known at request time on pages
 * with a dynamic segment, so the build's shell shows it plain). Deals is set apart in red (owner,
 * 2026-11-18): a solid --err block with white text (4.83:1), --err-tx on hover and on its own
 * page; red text itself on the blue bar would be unreadable (--err on --nav is about 1.6:1). */
export function NavLink(props: NavLinkProps) {
  return (
    <Suspense fallback={<NavLinkView {...props} active={false} />}>
      <ActiveNavLink {...props} />
    </Suspense>
  );
}

function ActiveNavLink(props: NavLinkProps) {
  const pathname = usePathname();
  return <NavLinkView {...props} active={pathname === props.href || pathname.startsWith(`${props.href}/`)} />;
}

function NavLinkView({ href, children, tone = "default", active, className }: NavLinkProps & { active: boolean }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cx(
        "flex h-9 flex-none items-center rounded-md px-2.5 text-sm whitespace-nowrap xl:px-3 transition-colors duration-150 focus-visible:outline-white motion-reduce:transition-none",
        tone === "deal" ? "bg-err font-semibold text-white hover:text-white" : "font-medium text-white hover:text-white",
        tone === "deal" ? (active ? "bg-err-tx" : "hover:bg-err-tx") : active ? "bg-nav-h" : "hover:bg-nav-h",
        className,
      )}
    >
      {children}
    </Link>
  );
}

type SearchInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "defaultValue" | "value">;

/** The header's search box. On /search it shows the text searched for (Search.dc.html). */
export function SearchInput(props: SearchInputProps) {
  return (
    <Suspense fallback={<input {...props} />}>
      <LiveSearchInput {...props} />
    </Suspense>
  );
}

function LiveSearchInput(props: SearchInputProps) {
  const pathname = usePathname();
  const params = useSearchParams();
  const q = pathname === "/search" ? (params.get("q") ?? "") : "";
  return <input key={q} defaultValue={q} {...props} />;
}
