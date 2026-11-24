import { Armchair, House, Search } from "lucide-react";
import { getLocale, getTranslations } from "next-intl/server";
import { SearchInput } from "@/components/store/header-actions";
import { buttonClasses } from "@/components/ui/button";
import { getPathname, Link } from "@/i18n/navigation";

/** NotFound.dc.html: an unknown address, or a product, category or order that does not exist. */
export async function NotFoundView() {
  const t = await getTranslations("store.notFound");
  const locale = await getLocale();
  return (
    <main id="main" className="bg-page">
      <div className="wrap flex flex-col items-center gap-4 pt-12 pb-16 text-center sm:pt-[72px] sm:pb-20">
        <div className="relative h-[150px] w-[220px]" aria-hidden="true">
          <span className="absolute inset-x-0 top-0 text-[120px] leading-[140px] font-extrabold tracking-[-0.04em] text-light">404</span>
          <Armchair size={110} strokeWidth={1.5} className="absolute top-4 left-[55px] -rotate-12 text-pri-fg" />
        </div>
        <h1 className="t-h1">{t("title")}</h1>
        <p className="text-lg max-w-[520px] text-tx2">{t("text")}</p>
        <form role="search" action={getPathname({ href: "/search", locale })} className="flex h-12 w-full max-w-[480px] overflow-hidden rounded-lg border border-bd bg-card focus-within:border-pri">
          <label className="flex flex-1 items-center gap-2.5 px-3.5 text-mut">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">{t("searchLabel")}</span>
            <SearchInput
              type="search"
              name="q"
              required
              maxLength={160}
              placeholder={t("searchPlaceholder")}
              className="min-w-0 flex-1 border-0 bg-transparent text-sm text-tx outline-none placeholder:text-mut"
            />
          </label>
          <button type="submit" className={buttonClasses({ className: "h-full rounded-none" })}>
            {t("search")}
          </button>
        </form>
        <div className="flex flex-wrap justify-center gap-3">
          <Link href="/" className={buttonClasses({ variant: "outline" })}>
            <House size={18} aria-hidden="true" />
            {t("home")}
          </Link>
          <Link href="/contact" className={buttonClasses({ variant: "ghost" })}>
            {t("contact")}
          </Link>
        </div>
      </div>
    </main>
  );
}
