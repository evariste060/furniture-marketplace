import { ArrowRight, Building2, Headset, Mail, MapPin, Phone, ShieldCheck, Truck } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense, type ReactNode } from "react";
import { BrandMarquee, brandCountLabel, marqueeBrands } from "@/components/store/brand-marquee";
import { CategorySpotlights } from "@/components/store/category-spotlight";
import { HeroCarousel, type HeroLink, type HeroSlide } from "@/components/store/hero-carousel";
import { HeroShowcase, type ShowcaseCategory, type ShowcaseServices } from "@/components/store/hero-showcase";
import { ProductCard, cardData } from "@/components/store/product-card";
import { buttonClasses } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { WhatsAppFab } from "@/features/contact/whatsapp-link";
import { SERVICE_GRID } from "@/features/services/card-layout";
import { ServiceGrid } from "@/features/services/service-grid";
import { Link } from "@/i18n/navigation";
import { getBanners, getBrands, getCategories, getProduct, getProducts, getServices, getStoreContact, type ProductQuery } from "@/lib/api/catalogue";
import type { components } from "@/lib/api/schema";
import { menuProduct, menuProductQuery, ORBIT_MAX, RELATED_MAX, topCategories, type CatalogCategory } from "@/lib/catalogue";
import { telHref } from "@/lib/contact";
import { cx } from "@/lib/cx";

type Banner = components["schemas"]["PublicBanner"];
type Localized = components["schemas"]["LocalizedText"];

/** Main.dc.html (desktop) and MobileHome.dc.html (≤700px), from the API: the hero (the showcase
 * of the categories' best sellers and the technical services, or the banners), the featured
 * products, the services (ADR-013), a spotlight per top-level category, the bestselling and newest
 * products, the business band and Trusted Brands. The order, the services section and Trusted
 * Brands: owner, 2026-11-17 (How Shopping Works removed). */
export default function HomePage() {
  return (
    <main id="main">
      <Suspense fallback={<div className="h-[480px] bg-light sm:h-[742px] lg:h-[493px]" />}>
        <Hero />
      </Suspense>
      <ProductSection id="featured" query={{ featured: true, size: 5 }} mobileCount={4} />
      <Suspense fallback={<ServicesFallback />}>
        <ServicesSection />
      </Suspense>
      <Suspense fallback={null}>
        <CategorySpotlights />
      </Suspense>
      <ProductSection id="best" query={{ sort_by: "bestselling", size: 5 }} tinted hideOnMobile />
      <ProductSection id="new" query={{ sort_by: "newest", size: 5 }} isNew mobileCount={2} />
      <BusinessBand />
      <Suspense fallback={null}>
        <TrustedBrands />
      </Suspense>
      <WhatsAppFab />
    </main>
  );
}

function pick(text: Localized | null | undefined, locale: string): string | null {
  if (!text) return null;
  return (locale === "rw" ? text.rw : text.en) || text.en || null;
}

/** A banner link: a path on this site, or an https URL. Anything else is not linked. */
function ctaHref(url: string | null | undefined): { href: string; external: boolean } | null {
  if (!url) return null;
  if (url.startsWith("/") && !url.startsWith("//")) return { href: url, external: false };
  if (/^https:\/\//.test(url)) return { href: url, external: true };
  return null;
}

/** The product a banner advertises: its link is a product page (/product/<slug>, also under /rw). */
function bannerProductSlug(url: string | null | undefined): string | null {
  return url?.match(/^(?:\/rw)?\/product\/([^/?#]+)\/?(?:[?#].*)?$/)?.[1] ?? null;
}

/** The hero: the product showcase (HeroShowcase) with each top category's best sellers, the same
 * request the category nav's mega menu makes (so it is cached once), then Services as one more
 * place with every active service (GET /services, the same cached read as the nav). Categories
 * without products are left out; with nothing at all it falls back to the banner carousel. */
async function Hero() {
  const t = await getTranslations("hero");
  const th = await getTranslations("store.header");
  const locale = (await getLocale()) === "rw" ? "rw" : "en";
  const [categories, services] = await Promise.all([getCategories().catch(() => []), getServices(locale).catch(() => [])]);
  const showcase = (await Promise.all(topCategories(categories).slice(0, ORBIT_MAX).map(showcaseCategory))).filter((c) => c !== null);
  const showcaseServices: ShowcaseServices | null = services.length
    ? {
        kind: "services",
        id: "services",
        name: th("services"),
        services: services.map(({ slug, name, icon, image }) => ({
          slug,
          name,
          icon,
          image,
        })),
      }
    : null;
  if (showcase.length || showcaseServices) return <HeroShowcase categories={showcase} services={showcaseServices} title={t("title")} />;
  return <BannerHero categories={categories} />;
}

async function showcaseCategory(category: CatalogCategory): Promise<ShowcaseCategory | null> {
  const page = await getProducts(menuProductQuery(category.slug)).catch(() => null);
  const [first, ...rest] = page?.items ?? [];
  if (!page || !first) return null;
  const related = rest.slice(0, RELATED_MAX).map((product) => ({
    ...menuProduct(product),
    cart: cardData(product).cart,
  }));
  return {
    id: category.id,
    name: category.name,
    slug: category.slug,
    total: page.total,
    featured: menuProduct(first),
    related,
  };
}

/** Every active banner from the API in its order (HeroCarousel rotates them), or the copy in
 * messages when there is none. A banner linking to a product page also gets Add to Cart for that
 * product's shown variant, as on the product cards. */
async function BannerHero({ categories }: { categories: CatalogCategory[] }) {
  const t = await getTranslations("hero");
  const locale = await getLocale();
  const banners = await getBanners().catch(() => null);
  const products = new Map(
    await Promise.all(
      (banners?.items ?? []).map(async (banner) => {
        const slug = bannerProductSlug(banner.cta_url);
        const product = slug ? await getProduct(slug).catch(() => null) : null;
        return [banner.id, product ? cardData(product).cart : null] as const;
      }),
    ),
  );
  const fallbackShop = topCategories(categories)[0];
  const fallbackCta: HeroLink | null = fallbackShop ? { href: `/category/${fallbackShop.slug}`, external: false } : null;
  const slide = (banner: Banner | null): HeroSlide => ({
    id: banner?.id ?? "default",
    overline: banner ? pick(banner.overline, locale) : t("overline"),
    title: (banner && pick(banner.title, locale)) ?? t("title"),
    subtitle: banner ? pick(banner.subtitle, locale) : t("subtitle"),
    cta: (banner && ctaHref(banner.cta_url)) ?? fallbackCta,
    ctaLabel: (banner && pick(banner.cta_label, locale)) || t("shopNow"),
    image: banner?.image ? { url: banner.image.url, alt: banner.image.alt } : null,
    cart: (banner && products.get(banner.id)) ?? null,
  });
  const slides = banners?.items.length ? banners.items.map(slide) : [slide(null)];
  return (
    <HeroCarousel
      slides={slides}
      viewDeals={t("viewDeals")}
      labels={{
        banners: t("banners"),
        show: slides.map((_, i) => t("showBanner", { n: i + 1, total: slides.length })),
      }}
      points={
        <>
          <HeroPoint icon={<Truck size={28} />} title={t("fast")} text={t("fastSub")} />
          <HeroPoint icon={<ShieldCheck size={28} />} title={t("genuine")} text={t("genuineSub")} />
          <HeroPoint icon={<Headset size={28} />} title={t("support")} text={t("supportSub")} />
        </>
      }
    />
  );
}

function HeroPoint({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-pri" aria-hidden="true">
        {icon}
      </span>
      <span className="flex flex-col">
        <b className="text-cap font-semibold">{title}</b>
        <span className="text-cap text-tx2">{text}</span>
      </span>
    </div>
  );
}

/** On the grey sections the description uses --tx2: --mut on --page is 4.47:1 (contrast
 * substitution approved 2026-10-27). */
function SectionHeading({ title, text, tinted = false }: { title: string; text?: string; tinted?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <h2 className="t-h3 sm:t-h2">{title}</h2>
      {text && <p className={cx("hidden sm:block", tinted ? "text-tx2" : "text-mut")}>{text}</p>}
    </div>
  );
}

const SECTIONS = {
  featured: { title: "featuredTitle", text: "featuredText" },
  best: { title: "bestTitle", text: "bestText" },
  new: { title: "newTitle", text: "newText" },
} as const;

const CARD_GRID = "grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-5";

function ProductSection({
  id,
  query,
  showButton = true,
  isNew = false,
  tinted = false,
  hideOnMobile = false,
  mobileCount = 5,
}: {
  id: keyof typeof SECTIONS;
  query: ProductQuery;
  showButton?: boolean;
  isNew?: boolean;
  tinted?: boolean;
  hideOnMobile?: boolean;
  mobileCount?: number;
}) {
  return (
    <section aria-labelledby={`${id}-title`} className={cx("px-4 py-3 sm:px-0 sm:py-4", tinted && "sm:bg-page", hideOnMobile && "hidden sm:block")}>
      <Suspense fallback={<SectionFallback id={id} />}>
        <SectionProducts id={id} query={query} showButton={showButton} isNew={isNew} mobileCount={mobileCount} />
      </Suspense>
    </section>
  );
}

async function SectionTitle({ id }: { id: keyof typeof SECTIONS }) {
  const t = await getTranslations("store.home");
  return (
    <div id={`${id}-title`}>
      <SectionHeading title={t(SECTIONS[id].title)} text={t(SECTIONS[id].text)} tinted={id === "best"} />
    </div>
  );
}

async function SectionProducts({
  id,
  query,
  showButton,
  isNew,
  mobileCount,
}: {
  id: keyof typeof SECTIONS;
  query: ProductQuery;
  showButton: boolean;
  isNew: boolean;
  mobileCount: number;
}) {
  const t = await getTranslations("store.home");
  let items;
  try {
    items = (await getProducts(query)).items;
  } catch {
    return (
      <div className="flex flex-col gap-3 sm:wrap sm:gap-4">
        <SectionTitle id={id} />
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("sectionError")}
        </p>
      </div>
    );
  }
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-3 sm:wrap sm:gap-4">
      <SectionTitle id={id} />
      <ul className={cx(CARD_GRID, "m-0 list-none p-0")}>
        {items.map((product, i) => (
          <li key={product.id} className={i >= mobileCount ? "hidden sm:block" : undefined}>
            <ProductCard dense showStock product={product} showButton={showButton} isNew={isNew} preload={id === "featured" && i < 2} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function SectionFallback({ id }: { id: keyof typeof SECTIONS }) {
  return (
    <div className="flex flex-col gap-3 sm:wrap sm:gap-4">
      <SectionTitle id={id} />
      <div className={CARD_GRID}>
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className={cx("h-[330px] rounded-xl", i >= 2 && "hidden sm:block")} />
        ))}
      </div>
    </div>
  );
}

/** Our Services (owner, 2026-11-17): the active technical services as their cards with the
 * "Tell us what you need" card (owner, 2026-11-18), as on the Services page, under the
 * featured products, from the same cached read as the nav and the Services page. Without
 * services it is left out; a failed read shows the section's error. */
async function ServicesSection() {
  const t = await getTranslations("store");
  const locale = (await getLocale()) === "rw" ? "rw" : "en";
  let services;
  try {
    services = await getServices(locale);
  } catch {
    return (
      <ServicesFrame>
        <p role="alert" className="rounded-xl bg-err-bg px-4 py-3 text-sm text-err-tx">
          {t("home.sectionError")}
        </p>
      </ServicesFrame>
    );
  }
  if (!services.length) return null;
  return (
    <ServicesFrame>
      <ServiceGrid services={services} label={t("services.listLabel")} />
    </ServicesFrame>
  );
}

/** The services section's grey band and heading, with "All services" beside it. */
async function ServicesFrame({ children }: { children: ReactNode }) {
  const t = await getTranslations("store");
  return (
    <section aria-labelledby="services-title" className="bg-page px-4 py-6 sm:px-0 sm:py-8">
      <div className="flex flex-col gap-3 sm:wrap sm:gap-4">
        <div className="flex items-end justify-between gap-4">
          <div id="services-title">
            <SectionHeading title={t("home.servicesTitle")} text={t("home.servicesText")} tinted />
          </div>
          <Link href="/services" className="flex flex-none items-center gap-1 text-sm font-semibold text-pri-h hover:text-pri">
            {t("header.allServices")}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        {children}
      </div>
    </section>
  );
}

function ServicesFallback() {
  return (
    <section aria-hidden="true" className="bg-page px-4 py-6 sm:px-0 sm:py-8">
      <div className="flex flex-col gap-3 sm:wrap sm:gap-4">
        <Skeleton className="h-8 w-48" />
        <div className={SERVICE_GRID}>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className={cx("h-[340px] rounded-xl", i >= 1 && "hidden sm:block")} />
          ))}
        </div>
      </div>
    </section>
  );
}

/** Trusted Brands, just above the footer (owner, 2026-11-17): the registered brands' logos moving
 * past on white cards, and how many brands the store has, both from GET /catalog/brands (the
 * active brands, the same cached read as the Brands page). Brands without a logo are counted but
 * not shown. Without any logo, or when the brands cannot be loaded, the section is left out. */
async function TrustedBrands() {
  const t = await getTranslations("store.home");
  const brands = await getBrands().catch(() => null);
  const shown = brands ? marqueeBrands(brands) : [];
  if (!brands || !shown.length) return null;
  const { count, over } = brandCountLabel(brands.length);
  return (
    <section aria-labelledby="brands-title" className="py-8 sm:py-12">
      <div className="flex flex-col items-center gap-5 sm:wrap sm:gap-6">
        <h2 id="brands-title" className="t-h3 px-4 text-center text-navy sm:t-h2 sm:px-0">
          {t("brandsTitle")}
        </h2>
        <div className="w-full">
          <BrandMarquee brands={shown} label={t("brandsTitle")} />
        </div>
        <Link
          href="/brands"
          className="flex items-center gap-1.5 rounded-full border border-bd bg-page px-4 py-1.5 text-sm font-medium text-tx2 transition-colors hover:border-pri hover:text-pri-h"
        >
          {over ? t("brandsCountOver", { count }) : t("brandsCount", { count })}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}

/** The business band, with the store's phone, email and address from GET /settings (module 19). */
/** The business buttons rise a little onto a soft shadow on hover (not with reduced motion). */
const BUSINESS_BUTTON = "transition-[translate,box-shadow] duration-200 ease-soft hover:-translate-y-0.5 hover:shadow-sh2 motion-reduce:translate-y-0!";

/** The business band above the footer, in a soft light blue so it stands apart from the navy
 * footer: a rounded card with a faint dot pattern and a large building outline for depth, the copy
 * and buttons on the left and the store's contact details on a white card on the right. Phones get
 * the short version of the copy and one button. */
async function BusinessBand() {
  const t = await getTranslations("store.home");
  return (
    <section aria-labelledby="business-title" className="px-4 py-6 sm:px-0 sm:py-8">
      <div className="relative overflow-hidden rounded-2xl border border-bd bg-linear-to-br from-light to-white text-tx sm:wrap">
        {/* A faint dot pattern, fading out towards the bottom left. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(rgb(8_102_245/0.14)_1px,transparent_1px)] [background-size:18px_18px] [mask-image:linear-gradient(to_bottom_left,black,transparent_70%)]"
        />
        {/* A large building outline in the corner. */}
        <Building2 aria-hidden="true" strokeWidth={1} className="pointer-events-none absolute -right-10 -bottom-14 size-64 text-pri/10 sm:size-80" />
        <div className="relative flex flex-wrap items-center justify-between gap-6 p-5 sm:gap-10 sm:p-8 lg:p-10">
          <div className="flex flex-[1_1_480px] flex-col gap-3">
            <span aria-hidden="true" className="flex size-11 items-center justify-center rounded-xl bg-white text-pri shadow-sh ring-1 ring-bd">
              <Building2 size={22} />
            </span>
            <h2 id="business-title" className="t-h4 text-navy sm:t-h1">
              <span className="sm:hidden">{t("businessShortTitle")}</span>
              <span className="hidden sm:inline">{t("businessTitle")}</span>
            </h2>
            <p className="max-w-[600px] text-sm text-tx2 sm:text-lg">
              <span className="sm:hidden">{t("businessShortText")}</span>
              <span className="hidden sm:inline">{t("businessText")}</span>
            </p>
            <div className="flex flex-wrap gap-3 pt-2">
              <Link
                href="/contact"
                className={buttonClasses({
                  size: "lg",
                  className: cx(BUSINESS_BUTTON, "max-sm:hidden!"),
                })}
              >
                {t("contactUs")}
              </Link>
              <Link
                href="/bulk-orders"
                className={buttonClasses({
                  variant: "outline",
                  size: "lg",
                  className: cx(BUSINESS_BUTTON, "hover:border-pri max-sm:hidden!"),
                })}
              >
                {t("requestQuote")}
                <ArrowRight size={18} aria-hidden="true" />
              </Link>
              <Link
                href="/bulk-orders"
                className={buttonClasses({
                  size: "sm",
                  className: "sm:hidden",
                })}
              >
                {t("requestQuoteShort")}
              </Link>
            </div>
          </div>
          <Suspense fallback={null}>
            <BusinessContact />
          </Suspense>
        </div>
      </div>
    </section>
  );
}

async function BusinessContact() {
  const t = await getTranslations("store.home");
  const contact = await getStoreContact().catch(() => null);
  if (!contact) return null;
  const rows = [
    contact.phone
      ? {
          Icon: Phone,
          label: t("callUs"),
          value: contact.phone,
          href: telHref(contact.phone),
        }
      : null,
    contact.email
      ? {
          Icon: Mail,
          label: t("emailUs"),
          value: contact.email,
          href: `mailto:${contact.email}`,
        }
      : null,
    contact.address
      ? {
          Icon: MapPin,
          label: t("visitUs"),
          value: contact.address,
          href: null,
        }
      : null,
  ].filter((row) => row !== null);
  if (rows.length === 0) return null;
  return (
    <address className="hidden flex-[0_1_360px] flex-col gap-4 rounded-2xl border border-bd bg-white p-6 not-italic text-tx shadow-sh sm:flex">
      {rows.map(({ Icon, label, value, href }) => (
        <div key={label} className="flex items-center gap-4">
          <span aria-hidden="true" className="flex size-11 flex-none items-center justify-center rounded-xl bg-light text-pri">
            <Icon size={20} />
          </span>
          <span className="flex min-w-0 flex-col">
            <b className="text-sm font-semibold text-navy">{label}</b>
            {href ? (
              <a href={href} className="text-sm break-words text-tx2 transition-colors hover:text-pri-h">
                {value}
              </a>
            ) : (
              <span className="text-sm text-tx2">{value}</span>
            )}
          </span>
        </div>
      ))}
    </address>
  );
}
