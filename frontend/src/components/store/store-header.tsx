import { Store, Truck } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { getCategories, getDeliveryInfo, getProducts, getStoreContact } from "@/lib/api/catalogue";
import { getPathname, Link } from "@/i18n/navigation";
import { MENU_PRODUCTS, menuProduct, menuProductQuery, topCategories, type CatalogCategory, type MenuCategory } from "@/lib/catalogue";
import { telHref } from "@/lib/contact";
import { formatMoney } from "@/lib/format";
import {
  AccountIconLink,
  AccountLink,
  CartIconLink,
  CartLink,
  HeaderHeight,
  LanguageMenu,
  MenuButton,
  NavLink,
  ThemeToggle,
  TrackOrderLink,
  WishlistLink,
} from "./header-actions";
import { CategoryLinks } from "./category-links";
import { CategoryMegaMenu } from "./category-mega-menu";
import { Logo } from "./logo";
import { MobileMenu } from "./mobile-menu";
import { SearchBox } from "./search-box";

/** Header.dc.html (desktop) and the MobileHome.dc.html header (≤700px): announcement bar, logo,
 * search, language, account, wishlist and cart, then the category nav. Categories come from GET
 * /catalog/categories; the free-delivery amount from GET /delivery/zones; the staff announcement
 * (shown instead of the free-delivery line while it is switched on) and the store's phone from
 * GET /settings (module 19). The cart, wishlist and account parts load in the browser, so the
 * page itself stays cacheable. */
export async function StoreHeader() {
  const t = await getTranslations("store");
  const locale = await getLocale();
  const searchAction = getPathname({ href: "/search", locale });
  return (
    <>
      <div className="bg-navy text-white">
        <div className="wrap flex h-[30px] items-center justify-center gap-2 text-xs sm:h-9 sm:justify-between sm:text-cap">
          <Suspense fallback={<span />}>
            <Announcement />
          </Suspense>
          <div className="hidden items-center gap-3 whitespace-nowrap text-odm sm:flex">
            {/* Tablets keep only the delivery line and the phone, on one line. */}
            <span className="hidden lg:inline">{t("announcement.genuine")}</span>
            <span aria-hidden="true" className="hidden lg:inline">
              |
            </span>
            <span className="hidden lg:inline">{t("announcement.warranty")}</span>
            <Suspense fallback={null}>
              <HelpLine />
            </Suspense>
          </div>
        </div>
      </div>
      {/* The whole header scrolls away with the page; then it slides back in and stays pinned to
          the top as one block, the actions row and the store menu together (SC-09; HeaderHeight
          sets data-compact). */}
      <header
        data-sticky-header
        className="group/header relative z-40 border-b border-bd bg-card data-compact:sticky data-compact:top-0 data-compact:animate-header-in data-compact:shadow-sh motion-reduce:animate-none!"
      >
        <HeaderHeight />
        {/* Desktop */}
        {/* Below laptops the gaps are tighter, the logo smaller and the account, wishlist and cart
            links icons only, so the row never wraps. */}
        <div className="wrap hidden items-center gap-4 py-3 sm:flex lg:gap-7">
          <Link href="/" aria-label={t("homeLink")} className="block flex-none">
            <Logo height={52} alt={t("logoAlt")} eager className="max-lg:h-11!" />
          </Link>
          <SearchBox action={searchAction} variant="desktop" />
          <LanguageMenu />
          <ThemeToggle />
          <TrackOrderLink />
          <AccountLink />
          <WishlistLink />
          <CartLink />
        </div>
        {/* Mobile */}
        <div className="px-4 pt-2 pb-3 sm:hidden">
          <div className="flex h-12 items-center justify-between">
            <div className="flex items-center gap-2.5">
              <MenuButton />
              <Link href="/" aria-label={t("homeLink")} className="block">
                <Logo height={38} alt={t("logoAlt")} eager />
              </Link>
            </div>
            <div className="flex items-center gap-1">
              <AccountIconLink />
              <CartIconLink />
            </div>
          </div>
          <SearchBox action={searchAction} variant="mobile" />
        </div>
        <Suspense fallback={<NavFallback />}>
          <CategoryNav />
        </Suspense>
      </header>
    </>
  );
}

async function Announcement() {
  const t = await getTranslations("store.announcement");
  const locale = await getLocale();
  const [delivery, contact] = await Promise.all([getDeliveryInfo().catch(() => null), getStoreContact().catch(() => null)]);
  if (contact?.announcement) {
    return <span className="text-center font-medium">{locale === "rw" ? contact.announcement.rw : contact.announcement.en}</span>;
  }
  const threshold = delivery?.free_delivery_threshold;
  if (threshold === null || threshold === undefined) return <span />;
  const amount = formatMoney(threshold);
  return (
    <div className="flex items-center gap-2">
      <Truck size={16} aria-hidden="true" className="hidden sm:block" />
      <Truck size={14} aria-hidden="true" className="sm:hidden" />
      <span className="hidden font-medium sm:inline">{t("freeDelivery", { amount })}</span>
      <span className="sm:hidden">{t("freeDeliveryShort", { amount })}</span>
    </div>
  );
}

/** "Need help? Call …" (Header.dc.html), when the store's phone is set. */
async function HelpLine() {
  const t = await getTranslations("store.announcement");
  const contact = await getStoreContact().catch(() => null);
  if (!contact?.phone) return null;
  return (
    <>
      <span aria-hidden="true">|</span>
      <a href={telHref(contact.phone)} className="font-medium text-white hover:text-white">
        {t("help", { phone: contact.phone })}
      </a>
    </>
  );
}

/** The category nav: "All Categories" (a mega menu of the categories and each one's best
 * sellers), the top-level categories (each a dropdown of its own subcategories) and Deals, in red
 * (owner, 2026-11-18), pinned, never under "More"; "Become a seller" on the right (SC-07). Text
 * only, no icons; Track Order is in the actions row above (owner, 2026-11-17). The menus' data is
 * read here on the server with the cached catalogue reads (GET /catalog/categories and
 * /catalog/products per category), all at once, so opening a menu never waits for the network.
 * A failed read empties only its own part. */
async function CategoryNav() {
  const t = await getTranslations("store.header");
  const tree = await getCategories().catch(() => []);
  const categories = topCategories(tree);
  const menu = await Promise.all(categories.map(menuCategory));
  return (
    <>
      <nav aria-label={t("categories")} className="hidden bg-nav sm:block">
        <div className="wrap flex items-center">
          <CategoryMegaMenu categories={menu} />
          {/* As many categories as fit, the rest under "More". */}
          <CategoryLinks
            items={categories.map((c) => ({
              id: c.id,
              name: c.name,
              slug: c.slug,
              subcategories: (c.children ?? []).map((s) => ({ id: s.id, name: s.name, slug: s.slug })),
            }))}
          />
          {/* Deals last, in red, so it stands apart from the categories (owner, 2026-11-18). */}
          <NavLink href="/deals" tone="deal" className="ml-1">
            {t("deals")}
          </NavLink>
          <span data-nav-spacer className="flex-1" />
          {/* The existing seller application (/account/seller; sign-in first for guests). */}
          <Link
            href="/account/seller"
            className="ml-2 flex h-8 flex-none items-center gap-1.5 rounded-md border border-white/70 px-3 text-sm font-semibold whitespace-nowrap text-white transition-colors duration-150 hover:bg-card hover:text-nav focus-visible:outline-white motion-reduce:transition-none"
          >
            <Store size={15} aria-hidden="true" />
            {t("becomeSeller")}
          </Link>
        </div>
      </nav>
      <MobileMenu categories={categories} />
    </>
  );
}

/** A top-level category with what the mega menu lists beside it (its subcategories; brands are
 * not offered on the storefront, SC-09) and its best sellers (subcategories included; null when
 * they could not be loaded). */
async function menuCategory(category: CatalogCategory): Promise<MenuCategory> {
  const products = await getProducts(menuProductQuery(category.slug)).then(
    (page) => ({ items: page.items.slice(0, MENU_PRODUCTS).map(menuProduct), total: page.total }),
    () => null,
  );
  const subcategories = (category.children ?? []).map((c) => ({ id: c.id, name: c.name, slug: c.slug }));
  return { id: category.id, name: category.name, slug: category.slug, subcategories, products };
}

function NavFallback() {
  return <div className="hidden h-12 bg-nav sm:block" />;
}
