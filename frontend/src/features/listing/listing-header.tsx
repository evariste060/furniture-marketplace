import { getLocale, getTranslations } from "next-intl/server";
import { Breadcrumb, type Crumb } from "@/components/ui/breadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import { getPathname } from "@/i18n/navigation";

/** The compact listing header (category pages, All Products): Home / … / title, with the title centred beside it.
 * `trail` is the crumbs between Home and the page, as paths without locale. */
export async function ListingHeader({ title, trail = [] }: { title: string; trail?: { label: string; href: string }[] }) {
  const tu = await getTranslations("ui");
  const th = await getTranslations("store.tabs");
  const locale = await getLocale();
  const items: Crumb[] = [
    { label: th("home"), href: getPathname({ href: "/", locale }) },
    ...trail.map((c) => ({ label: c.label, href: getPathname({ href: c.href, locale }) })),
    { label: title },
  ];
  return (
    <section className="bg-light">
      {/* One row from 640px: crumbs on the left, the name centred; stacked on phones. */}
      <div className="wrap flex flex-col gap-0.5 pt-0 pb-3 sm:grid sm:grid-cols-[1fr_auto_1fr] sm:items-center sm:gap-4">
        <Breadcrumb label={tu("breadcrumb")} items={items} className="min-w-0" />
        <h1 className="t-h2 text-head sm:text-center">{title}</h1>
      </div>
    </section>
  );
}

/** ListingHeader's loading state, the same height. */
export function ListingHeaderFallback() {
  return (
    <section className="bg-light">
      <div className="wrap flex flex-col gap-0.5 pt-0 pb-3 sm:grid sm:grid-cols-[1fr_auto_1fr] sm:items-center sm:gap-4">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-8 w-56 sm:justify-self-center" />
      </div>
    </section>
  );
}
