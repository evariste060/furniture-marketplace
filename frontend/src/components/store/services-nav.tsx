"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { ServiceIcon, type ServiceIconKey } from "@/features/services/service-icon";
import { Link, usePathname } from "@/i18n/navigation";
import { cx } from "@/lib/cx";
import { NavLink } from "./header-actions";
import { NavDropdown } from "./nav-dropdown";

export type ServiceNavItem = { slug: string; name: string; short_description: string; icon: ServiceIconKey };

/** "Services" on the blue nav bar, after Deals and never folded into "More" (ADR-013): a link to
 * /services with a dropdown of the services, each with its icon and card text. No icon on the bar
 * itself (the bar is text only). Without services (or when they could not be loaded) it is a
 * plain link. */
export function ServicesNav({ services }: { services: ServiceNavItem[] }) {
  const t = useTranslations("store.header");
  const pathname = usePathname();
  const active = pathname === "/services" || pathname.startsWith("/services/");
  if (services.length === 0) return <NavLink href="/services">{t("services")}</NavLink>;
  return (
    <NavDropdown label={t("services")} href="/services" toggleLabel={t("servicesMenu")} active={active} width={380} panelLabel={t("servicesMenu")}>
      {(close) => (
        <div className="flex flex-col p-2">
          <ul className="m-0 flex max-h-[70vh] list-none flex-col gap-0.5 overflow-y-auto p-0">
            {services.map((s) => {
              const here = pathname === `/services/${s.slug}`;
              return (
                <li key={s.slug}>
                  <Link
                    href={`/services/${s.slug}`}
                    aria-current={here ? "page" : undefined}
                    onClick={close}
                    className={cx(
                      "flex items-start gap-3 rounded-md px-3 py-2.5 transition-colors duration-150 motion-reduce:transition-none",
                      here ? "bg-light text-pri-h" : "text-tx hover:bg-page hover:text-pri",
                    )}
                  >
                    <span aria-hidden="true" className="flex size-8 flex-none items-center justify-center rounded-lg bg-light text-pri">
                      <ServiceIcon icon={s.icon} size={16} />
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="text-sm font-semibold">{s.name}</span>
                      <span className="line-clamp-1 text-cap text-tx2">{s.short_description}</span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <Link href="/services" onClick={close} className="mt-1 flex items-center gap-1.5 border-t border-bd px-3 pt-2.5 pb-1.5 text-sm font-semibold text-pri hover:text-pri-h">
            {t("allServices")}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
      )}
    </NavDropdown>
  );
}
