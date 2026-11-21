"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronRight, CircleCheck, LayoutGrid, PackageOpen, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { buttonClasses } from "@/components/ui/button";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { ServiceIcon, type ServiceIconKey } from "@/features/services/service-icon";
import { Link, usePathname } from "@/i18n/navigation";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { categoryIcon } from "@/lib/category-icon";
import { MENU_PRODUCTS, menuProduct, menuProductQuery, type MenuBrand, type MenuCategory, type MenuProduct } from "@/lib/catalogue";
import { cx } from "@/lib/cx";
import { formatMoney } from "@/lib/format";
import { IMAGE_SIZES } from "@/lib/images";
import { NavDropdown } from "./nav-dropdown";

/** Hovering a category waits this long before showing what is under it, so a cursor moving
 * diagonally towards the next column does not switch to the categories it crosses on the way. */
const SWITCH_DELAY = 110;

type MenuProducts = { items: MenuProduct[]; total: number };

/** A technical service in the menu (ADR-013): its card text and its "What we offer" items. */
export type MenuService = { slug: string; name: string; short_description: string; icon: ServiceIconKey; items: string[] };

/** The left column's id for the Services entry (category ids are UUIDs, so it cannot clash). */
const SERVICES_ID = "services";
/** How many of a service's items its panel lists. */
const MENU_SERVICE_ITEMS = 8;

/** Where the menu leads: the category's own page, the same as its link on the store menu bar
 * (owner, 2026-11-17; it was the search page), with the brand filter ticked when one is given. */
export function categoryHref(slug: string, brand?: string | null) {
  const path = `/category/${encodeURIComponent(slug)}`;
  return brand ? `${path}?${new URLSearchParams({ brand })}` : path;
}

/** "All Categories": a mega menu in three steps. The main categories are down the left; hovering
 * (or focusing, or tapping) one shows its brands (Phones, Laptops, TVs & Audio: staff's menu
 * list) or, for a category without brands listed, its subcategories (Home Appliances,
 * Accessories, Cameras); hovering one of those shows its best sellers ("All <category>" shows
 * the category's). Clicking a category or subcategory opens its page, a brand its category's page filtered to
 * it, and a product opens its page. The middle column and the categories' best sellers come with
 * the page (the header loads them on the server, cached); a brand's or subcategory's products are
 * loaded the first time it is shown and then kept. Services comes last, with the services as its
 * subcategories (owner, 2026-11-17). */
export function CategoryMegaMenu({ categories, services = [] }: { categories: MenuCategory[]; services?: MenuService[] }) {
  const t = useTranslations("store");
  const pathname = usePathname();
  // Category pages light their own link in the row; this one stands for the full catalogue.
  const active = pathname === "/products";
  return (
    <NavDropdown
      label={t("header.allCategories")}
      active={active}
      width={1000}
      panelLabel={t("header.allCategories")}
      variant="box"
    >
      {(close) => <MegaMenuPanel categories={categories} services={services} close={close} />}
    </NavDropdown>
  );
}

/** Hover with a short delay, focus at once, and a first tap that previews instead of opening. */
function usePreview() {
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const soon = useCallback((show: () => void) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(show, SWITCH_DELAY);
  }, []);
  const stay = useCallback(() => window.clearTimeout(timer.current), []);
  const pointer = useRef("");
  /** Props for a link that previews `show` (when it is not `on`) and otherwise opens and closes. */
  const linkProps = (on: boolean, show: () => void, close: () => void) => ({
    onPointerEnter: (e: ReactPointerEvent) => e.pointerType === "mouse" && soon(show),
    onPointerLeave: stay,
    onPointerDown: (e: ReactPointerEvent) => {
      pointer.current = e.pointerType;
    },
    onFocus: () => {
      stay();
      show();
    },
    onClick: (e: { preventDefault: () => void }) => {
      const touch = pointer.current === "touch" || pointer.current === "pen";
      pointer.current = "";
      if (touch && !on) {
        e.preventDefault();
        stay();
        show();
        return;
      }
      close();
    },
  });
  return { stay, linkProps };
}

/** Services is the last main entry (owner, 2026-11-17): it lists the services, and a service
 * shows its card text and what it includes instead of products. */
export function MegaMenuPanel({ categories, services = [], close }: { categories: MenuCategory[]; services?: MenuService[]; close: () => void }) {
  const t = useTranslations("store");
  const pathname = usePathname();
  const isHere = (slug: string) => pathname === `/category/${slug}`;
  const current = categories.find((c) => isHere(c.slug));
  const hasServices = services.length > 0;
  const onServices = hasServices && (pathname === "/services" || pathname.startsWith("/services/"));
  const [mainId, setMainId] = useState(current?.id ?? (onServices ? SERVICES_ID : null) ?? categories[0]?.id ?? (hasServices ? SERVICES_ID : null));
  // The brand or subcategory whose products are shown; null shows the main category's own.
  const [choiceKey, setChoiceKey] = useState<string | null>(null);
  const main = categories.find((c) => c.id === mainId) ?? null;
  const choices = main ? menuChoices(main, t) : [];
  const choice = choices.find((c) => c.key === choiceKey) ?? null;
  const bySubcategory = Boolean(main && main.brands.length === 0 && main.subcategories.length > 0);
  const { stay, linkProps } = usePreview();
  const showMain = (id: string) => {
    if (id === mainId) return;
    setMainId(id);
    setChoiceKey(null);
  };

  return (
    <div className="flex max-h-[min(560px,calc(100dvh-140px))]">
      <div className="flex w-64 flex-none flex-col border-r border-bd bg-page">
        <span className="t-over px-4 pt-4 pb-2 text-tx2">{t("menu.shopByCategory")}</span>
        {categories.length || hasServices ? (
          <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0 pb-2">
            {categories.map((c) => {
              const Icon = categoryIcon(c);
              const on = c.id === mainId;
              // Two separate states: `on` is the category shown (solid blue), `here` is the page
              // you are on (bold blue with a dot), so it stays visible while another is previewed.
              const here = isHere(c.slug);
              return (
                <li key={c.id}>
                  <MainEntry href={categoryHref(c.slug)} name={c.name} icon={<Icon size={17} />} on={on} here={here} {...linkProps(on, () => showMain(c.id), close)} />
                </li>
              );
            })}
            {hasServices && (
              <li>
                <MainEntry
                  href="/services"
                  name={t("header.services")}
                  icon={<Wrench size={17} />}
                  on={mainId === SERVICES_ID}
                  here={onServices}
                  {...linkProps(mainId === SERVICES_ID, () => showMain(SERVICES_ID), close)}
                />
              </li>
            )}
          </ul>
        ) : (
          <p className="m-0 flex-1 px-4 py-2 text-sm text-tx2">{t("megaMenu.noCategories")}</p>
        )}
        <Link
          href="/products"
          onClick={close}
          className="flex items-center gap-2 border-t border-bd px-4 py-3 text-sm font-semibold text-pri hover:text-pri-h"
        >
          <LayoutGrid size={16} aria-hidden="true" />
          {t("megaMenu.browseAll")}
        </Link>
      </div>
      {mainId === SERVICES_ID && <ServicesColumns services={services} close={close} />}
      {main && choices.length > 0 && (
        <nav
          key={main.id}
          aria-label={t(bySubcategory ? "megaMenu.subcategoriesOf" : "megaMenu.brandsIn", { name: main.name })}
          onPointerEnter={stay}
          className="flex w-56 flex-none animate-mega-in flex-col border-r border-bd bg-white motion-reduce:animate-none"
        >
          <span className="t-over px-4 pt-4 pb-2 text-tx2">{bySubcategory ? t("listing.subcategories") : t("header.brands")}</span>
          <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0 pb-2">
            {[{ key: null, name: t("listing.allOf", { name: main.name }), href: categoryHref(main.slug), count: null }, ...choices].map((c) => {
              const on = c.key === choiceKey;
              return (
                <li key={c.key ?? ""}>
                  <Link
                    href={c.href}
                    {...linkProps(on, () => setChoiceKey(c.key), close)}
                    className={cx(
                      "mx-2 flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 motion-reduce:transition-none",
                      on ? "bg-light font-semibold text-pri-h hover:text-pri-h" : "font-medium text-tx hover:bg-page hover:text-pri",
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate">{c.name}</span>
                    {c.count ? <span className={cx("flex-none text-cap", on ? "text-pri-h" : "text-tx2")}>{c.count}</span> : null}
                    {c.key !== null && <ChevronRight size={15} aria-hidden="true" className={cx("flex-none", on ? "text-pri-h" : "text-bd2")} />}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
      {mainId !== SERVICES_ID && (
        <div className="min-w-0 flex-1 overflow-y-auto" onPointerEnter={stay}>
          {main &&
            (choice ? (
              <ChoiceProducts key={choice.key} choice={choice} close={close} />
            ) : (
              <ProductsPanel key={main.id} id={main.id} name={main.name} href={categoryHref(main.slug)} products={main.products} close={close} />
            ))}
        </div>
      )}
    </div>
  );
}

/** A main entry of the left column: a category, or Services. Two separate states: `on` is the
 * entry shown (solid blue), `here` is the page you are on (bold blue with a dot), so it stays
 * visible while another is previewed. */
function MainEntry({
  href,
  name,
  icon,
  on,
  here,
  ...events
}: { href: string; name: string; icon: ReactNode; on: boolean; here: boolean } & ReturnType<ReturnType<typeof usePreview>["linkProps"]>) {
  return (
    <Link
      href={href}
      aria-current={here ? "page" : undefined}
      {...events}
      className={cx(
        "mx-2 flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 motion-reduce:transition-none",
        on
          ? "bg-pri font-medium text-white shadow-sh hover:text-white"
          : here
            ? "font-semibold text-pri-h hover:bg-white hover:text-pri-h"
            : "font-medium text-tx hover:bg-white hover:text-pri",
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "flex size-8 flex-none items-center justify-center rounded-md transition-colors duration-150 motion-reduce:transition-none",
          on ? "bg-white/15 text-white" : here ? "bg-light text-pri-h" : "bg-white text-tx2",
        )}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1 truncate">{name}</span>
      {here && <span aria-hidden="true" className={cx("size-1.5 flex-none rounded-full", on ? "bg-white" : "bg-pri")} />}
      <ChevronRight
        size={16}
        aria-hidden="true"
        className={cx("flex-none transition-colors duration-150 motion-reduce:transition-none", on ? "text-white" : "text-bd2")}
      />
    </Link>
  );
}

/** Services' middle and right columns: "All services" and each service down the middle (the
 * services are its subcategories); on the right every service with its card text, or the
 * previewed service's text, what it includes and "Request this service". The data comes with the
 * page (GET /services, cached), so nothing loads on hover. */
function ServicesColumns({ services, close }: { services: MenuService[]; close: () => void }) {
  const t = useTranslations("store");
  const pathname = usePathname();
  const [slug, setSlug] = useState<string | null>(null);
  const { stay, linkProps } = usePreview();
  const shown = services.find((s) => s.slug === slug) ?? null;
  const entries = [
    { slug: null, name: t("header.allServices"), href: "/services", icon: null },
    ...services.map((s) => ({ slug: s.slug, name: s.name, href: `/services/${s.slug}`, icon: s.icon })),
  ];
  return (
    <>
      <nav
        aria-label={t("header.services")}
        onPointerEnter={stay}
        className="flex w-56 flex-none animate-mega-in flex-col border-r border-bd bg-white motion-reduce:animate-none"
      >
        <span className="t-over px-4 pt-4 pb-2 text-tx2">{t("header.services")}</span>
        <ul className="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0 pb-2">
          {entries.map((e) => {
            const on = e.slug === slug;
            return (
              <li key={e.slug ?? ""}>
                <Link
                  href={e.href}
                  aria-current={pathname === e.href ? "page" : undefined}
                  {...linkProps(on, () => setSlug(e.slug), close)}
                  className={cx(
                    "mx-2 flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors duration-150 motion-reduce:transition-none",
                    on ? "bg-light font-semibold text-pri-h hover:text-pri-h" : "font-medium text-tx hover:bg-page hover:text-pri",
                  )}
                >
                  {e.icon && (
                    <span aria-hidden="true" className={cx("flex flex-none", on ? "text-pri-h" : "text-tx2")}>
                      <ServiceIcon icon={e.icon} size={15} />
                    </span>
                  )}
                  <span className="min-w-0 flex-1 truncate">{e.name}</span>
                  {e.slug !== null && <ChevronRight size={15} aria-hidden="true" className={cx("flex-none", on ? "text-pri-h" : "text-bd2")} />}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="min-w-0 flex-1 overflow-y-auto" onPointerEnter={stay}>
        {shown ? <ServicePanel key={shown.slug} service={shown} close={close} /> : <ServicesOverview services={services} close={close} />}
      </div>
    </>
  );
}

function ServicesOverview({ services, close }: { services: MenuService[]; close: () => void }) {
  const t = useTranslations("store");
  return (
    <section aria-labelledby="mega-services" className="flex h-full animate-mega-in flex-col p-5 motion-reduce:animate-none">
      <div className="flex items-center justify-between gap-4">
        <p id="mega-services" className="m-0 t-h4 text-navy">
          {t("header.services")}
        </p>
        <Link href="/services" onClick={close} className="flex flex-none items-center gap-1 text-sm font-semibold text-pri hover:text-pri-h">
          {t("header.allServices")}
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
      <ul className="m-0 mt-4 grid list-none grid-cols-1 gap-2 p-0 lg:grid-cols-2">
        {services.map((s) => (
          <li key={s.slug}>
            <Link
              href={`/services/${s.slug}`}
              onClick={close}
              className="group flex items-start gap-3 rounded-lg border border-transparent p-2 text-tx transition-colors duration-150 hover:border-bd hover:bg-page hover:text-tx motion-reduce:transition-none"
            >
              <span aria-hidden="true" className="flex size-10 flex-none items-center justify-center rounded-lg bg-light text-pri">
                <ServiceIcon icon={s.icon} size={18} />
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm font-semibold group-hover:text-pri">{s.name}</span>
                <span className="line-clamp-2 text-cap text-tx2">{s.short_description}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ServicePanel({ service, close }: { service: MenuService; close: () => void }) {
  const t = useTranslations("store");
  const href = `/services/${service.slug}`;
  const items = service.items.slice(0, MENU_SERVICE_ITEMS);
  return (
    <section aria-labelledby={`mega-service-${service.slug}`} className="flex h-full animate-mega-in flex-col p-5 motion-reduce:animate-none">
      <div className="flex items-center justify-between gap-4">
        <p id={`mega-service-${service.slug}`} className="m-0 t-h4 text-navy">
          {service.name}
        </p>
        <Link href={href} onClick={close} className="flex flex-none items-center gap-1 text-sm font-semibold text-pri hover:text-pri-h">
          {t("megaMenu.viewService")}
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
      <p className="m-0 mt-2 text-sm text-tx2">{service.short_description}</p>
      {items.length > 0 && (
        <>
          <span className="t-over mt-4 mb-2 text-tx2">{t("services.offerTitle")}</span>
          <ul className="m-0 grid list-none grid-cols-1 gap-x-4 gap-y-2 p-0 lg:grid-cols-2">
            {items.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-tx">
                <CircleCheck size={16} aria-hidden="true" className="mt-0.5 flex-none text-pri" />
                {item}
              </li>
            ))}
          </ul>
        </>
      )}
      <Link href={`${href}/request`} onClick={close} className={cx(buttonClasses({ size: "sm" }), "mt-5 self-start")}>
        {t("services.requestThis")}
      </Link>
    </section>
  );
}

/** An entry of the middle column: a brand within the main category, or a subcategory. */
type MenuChoice = {
  key: string;
  name: string;
  /** The products column's heading. */
  title: string;
  href: string;
  /** Products there; null when unknown (subcategories), 0 when there are none (nothing loads). */
  count: number | null;
  query: { category: string; brand?: string[] };
  empty: string;
};

/** The middle column for a main category: its brands when it has any (staff's menu list, or the
 * brands of its products), otherwise its subcategories (approved 2026-11-16). */
function menuChoices(main: MenuCategory, t: ReturnType<typeof useTranslations<"store">>): MenuChoice[] {
  if (main.brands.length > 0) {
    return main.brands.map((b: MenuBrand) => ({
      key: `brand:${b.slug}`,
      name: b.name,
      title: `${b.name} · ${main.name}`,
      href: categoryHref(main.slug, b.slug),
      count: b.count,
      query: { category: main.slug, brand: [b.slug] },
      empty: t("megaMenu.emptyBrand", { brand: b.name, category: main.name }),
    }));
  }
  return main.subcategories.map((s) => ({
    key: `category:${s.slug}`,
    name: s.name,
    title: s.name,
    href: categoryHref(s.slug),
    count: null,
    query: { category: s.slug },
    empty: t("megaMenu.empty"),
  }));
}

/** A brand's or subcategory's best sellers, loaded through the site's API proxy when first
 * shown; a brand listed without products there loads nothing. */
function ChoiceProducts({ choice, close }: { choice: MenuChoice; close: () => void }) {
  const none = choice.count === 0;
  const { data, isPending, isError } = useQuery({
    enabled: !none,
    queryKey: ["menu-products", choice.key, choice.query.category],
    queryFn: async ({ signal }): Promise<MenuProducts> => {
      const query = { ...menuProductQuery(choice.query.category), ...(choice.query.brand ? { brand: choice.query.brand } : {}) };
      const { data, error, response } = await browserApi.GET("/api/v1/catalog/products", { params: { query }, signal });
      if (!data) throw ApiError.from(response.status, error);
      return { items: data.items.slice(0, MENU_PRODUCTS).map(menuProduct), total: data.total };
    },
    staleTime: 5 * 60_000,
    retry: 1,
  });
  return (
    <ProductsPanel
      id={choice.key.replace(":", "-")}
      name={choice.title}
      href={choice.href}
      products={none ? { items: [], total: 0 } : isPending ? undefined : isError ? null : data}
      empty={choice.empty}
      close={close}
    />
  );
}

/** The products column: the category's name, "View all" and its best sellers. `products` is
 * undefined while loading and null when it could not be loaded. */
function ProductsPanel({
  id,
  name,
  href,
  products,
  empty,
  close,
}: {
  id: string;
  name: string;
  href: string;
  products: MenuProducts | null | undefined;
  /** The message when there are no products (default: the category's). */
  empty?: string;
  close: () => void;
}) {
  const t = useTranslations("store");
  return (
    <section aria-labelledby={`mega-${id}`} aria-busy={products === undefined || undefined} className="flex h-full animate-mega-in flex-col p-5 motion-reduce:animate-none">
      <div className="flex items-center justify-between gap-4">
        <p id={`mega-${id}`} className="m-0 t-h4 text-navy">
          {name}
        </p>
        <Link href={href} onClick={close} className="flex flex-none items-center gap-1 text-sm font-semibold text-pri hover:text-pri-h">
          {products && products.total > 0 ? t("megaMenu.viewAllCount", { count: products.total }) : t("megaMenu.viewCategory")}
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
      {products === undefined ? (
        <ul className="m-0 mt-4 grid list-none grid-cols-1 gap-2 p-0 lg:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="flex items-center gap-3 p-2">
              <Skeleton className="size-14 flex-none" />
              <span className="flex flex-1 flex-col gap-1.5">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-20" />
              </span>
            </li>
          ))}
        </ul>
      ) : products === null ? (
        <MenuNotice>{t("megaMenu.productsError")}</MenuNotice>
      ) : products.items.length === 0 ? (
        <MenuNotice>{empty ?? t("megaMenu.empty")}</MenuNotice>
      ) : (
        <>
          <span className="t-over mt-4 mb-2 text-tx2">{t("megaMenu.bestSellers")}</span>
          <ul className="m-0 grid list-none grid-cols-1 gap-2 p-0 lg:grid-cols-2">
            {products.items.map((p) => (
              <li key={p.id}>
                <MenuProductLink product={p} close={close} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function MenuProductLink({ product, close }: { product: MenuProduct; close: () => void }) {
  return (
    <Link
      href={`/product/${product.slug}`}
      onClick={close}
      className="group flex items-center gap-3 rounded-lg border border-transparent p-2 text-tx transition-colors duration-150 hover:border-bd hover:bg-page hover:text-tx motion-reduce:transition-none"
    >
      <ProductImage image={product.image} alt="" sizes={IMAGE_SIZES.thumb} iconSize={20} className="size-14 rounded-lg border border-bd bg-white" />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="line-clamp-2 text-sm font-medium group-hover:text-pri">{product.name}</span>
        {product.price !== null && <span className="text-sm font-semibold text-navy">{formatMoney(product.price)}</span>}
      </span>
    </Link>
  );
}

function MenuNotice({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 py-10 text-center">
      <PackageOpen size={28} strokeWidth={1.5} aria-hidden="true" className="text-bd2" />
      <p className="m-0 max-w-64 text-sm text-tx2">{children}</p>
    </div>
  );
}
