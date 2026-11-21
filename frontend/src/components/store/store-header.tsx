import { Search, Truck } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { getCategories, getDeliveryInfo, getFacets, getProducts, getServices, getStoreContact } from "@/lib/api/catalogue";
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
  SearchInput,
  TrackOrderLink,
  WishlistLink,
} from "./header-actions";
import { CategoryLinks } from "./category-links";
import { CategoryMegaMenu } from "./category-mega-menu";
import { Logo } from "./logo";
import { MobileMenu } from "./mobile-menu";
import { ServicesNav } from "./services-nav";

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
      {/* The whole header scrolls away with the page; then its actions row slides back in and
          stays pinned to the top, without the category row (HeaderHeight sets data-compact). */}
      <header
        data-sticky-header
        className="group/header relative z-40 border-b border-bd bg-white data-compact:sticky data-compact:top-0 data-compact:animate-header-in data-compact:shadow-sh motion-reduce:animate-none!"
      >
        <HeaderHeight />
        {/* Desktop */}
        {/* Below laptops the gaps are tighter, the logo smaller and the account, wishlist and cart
            links icons only, so the row never wraps. */}
        <div className="wrap hidden items-center gap-4 py-3 sm:flex lg:gap-7">
          <Link href="/" aria-label={t("homeLink")} className="block flex-none">
            <Logo height={52} alt={t("logoAlt")} eager className="max-lg:h-11!" />
          </Link>
          <form role="search" action={searchAction} className="flex h-11 min-w-[200px] flex-1 overflow-hidden rounded-lg border border-bd focus-within:border-pri">
            <label className="flex flex-1 items-center gap-2.5 px-3.5 text-mut">
              <Search size={18} aria-hidden="true" />
              <span className="sr-only">{t("header.searchLabel")}</span>
              <SearchInput
                type="search"
                name="q"
                required
                maxLength={160}
                placeholder={t("header.searchPlaceholder")}
                className="min-w-0 flex-1 border-0 bg-transparent text-sm text-tx outline-none placeholder:text-mut"
              />
            </label>
            <button type="submit" aria-label={t("header.search")} className="flex w-13 cursor-pointer items-center justify-center border-0 bg-pri text-white hover:bg-pri-h">
              <Search size={18} aria-hidden="true" />
            </button>
          </form>
          <LanguageMenu />
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
          <form role="search" action={searchAction}>
            <label className="flex h-[42px] items-center gap-2 rounded-lg bg-subtle px-3 text-mut">
              <Search size={18} aria-hidden="true" />
              <SearchInput
                type="search"
                name="q"
                required
                maxLength={160}
                aria-label={t("header.searchLabel")}
                placeholder={t("header.searchPlaceholderShort")}
                className="min-w-0 flex-1 border-0 bg-transparent text-base text-tx outline-none placeholder:text-mut"
              />
            </label>
          </form>
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
 * sellers), the top-level categories (each a dropdown of its own subcategories), Services (a
 * dropdown of the technical services, ADR-013) and Deals last, in red (owner, 2026-11-18); both
 * pinned, never under "More". Text
 * only, no icons; Track Order is in the actions row above (owner, 2026-11-17). The menus' data is
 * read here on the server with the cached catalogue reads (GET /catalog/categories and
 * /catalog/products per category), all at once, so opening a menu never waits for the network.
 * A failed read empties only its own part. */
async function CategoryNav() {
  const t = await getTranslations("store.header");
  const tree = await getCategories().catch(() => []);
  const categories = topCategories(tree);
  const locale = (await getLocale()) === "rw" ? "rw" : "en";
  const [menu, services] = await Promise.all([
    Promise.all(categories.map(menuCategory)),
    getServices(locale).then(
      (list) => list.map(({ slug, name, short_description, icon, items }) => ({ slug, name, short_description, icon, items: items.map((i) => i.title) })),
      () => [],
    ),
  ]);
  return (
    <>
      <nav aria-label={t("categories")} className="hidden bg-nav sm:block group-data-compact/header:hidden!">
        <div className="wrap flex items-center">
          <CategoryMegaMenu categories={menu} services={services} />
          {/* As many categories as fit, the rest under "More". */}
          <CategoryLinks
            items={categories.map((c) => ({
              id: c.id,
              name: c.name,
              slug: c.slug,
              subcategories: (c.children ?? []).map((s) => ({ id: s.id, name: s.name, slug: s.slug })),
            }))}
          />
          <ServicesNav services={services} />
          {/* Deals last, in red, so it stands apart from the categories (owner, 2026-11-18). */}
          <NavLink href="/deals" tone="deal" className="ml-1">
            {t("deals")}
          </NavLink>
          <span data-nav-spacer className="flex-1" />
        </div>
      </nav>
      <MobileMenu categories={categories} />
    </>
  );
}

/** A top-level category with what the mega menu lists beside it, and its best sellers
 * (subcategories included; null when they could not be loaded). ADR-012, 2026-11-16: the brands
 * staff chose for its menu, in their order, even those without products yet; without a list, its
 * subcategories; without either, the brands of its products. */
async function menuCategory(category: CatalogCategory): Promise<MenuCategory> {
  const [products, counted] = await Promise.all([
    getProducts(menuProductQuery(category.slug)).then(
      (page) => ({ items: page.items.slice(0, MENU_PRODUCTS).map(menuProduct), total: page.total }),
      () => null,
    ),
    getFacets({ category: category.slug }).then(
      (facets) => facets.brands.filter((b) => b.count > 0),
      () => [],
    ),
  ]);
  const chosen = category.menu_brands ?? [];
  const counts = new Map(counted.map((b) => [b.slug, b.count]));
  const subcategories = (category.children ?? []).map((c) => ({ id: c.id, name: c.name, slug: c.slug }));
  const brands = chosen.length
    ? chosen.map((b) => ({ name: b.name, slug: b.slug, count: counts.get(b.slug) ?? 0 }))
    : subcategories.length
      ? []
      : counted.map((b) => ({ name: b.name, slug: b.slug, count: b.count }));
  return { id: category.id, name: category.name, slug: category.slug, brands, subcategories, products };
}

function NavFallback() {
  return <div className="hidden h-12 bg-nav sm:block group-data-compact/header:hidden!" />;
}
