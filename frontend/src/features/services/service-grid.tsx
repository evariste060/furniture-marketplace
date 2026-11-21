import { Fragment, Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { SERVICE_GRID, type ServiceSummary } from "./card-layout";
import { ServiceCard } from "./service-card";
import { promoIndex, ServicesPromo } from "./services-promo";

/** The service cards four to a desktop row with the "Tell us what you need" card two places wide
 * closing the 2nd row (or right after the last service when there are fewer). Used by the
 * Services page and the home page's Our Services (owner, 2026-11-18). */
export function ServiceGrid({ services, label }: { services: ServiceSummary[]; label?: string }) {
  const at = promoIndex(services.length);
  const promo = (
    <li key="promo" className="flex min-[520px]:col-span-2">
      <Suspense fallback={<Skeleton className="h-full min-h-[340px] w-full rounded-xl" />}>
        <ServicesPromo services={services} />
      </Suspense>
    </li>
  );
  return (
    <ul aria-label={label} className={`m-0 list-none p-0 ${SERVICE_GRID}`}>
      {services.map((service, i) => (
        <Fragment key={service.slug}>
          {i === at && promo}
          <li className="flex">
            <ServiceCard service={service} headingLevel={3} />
          </li>
        </Fragment>
      ))}
      {at === services.length && promo}
    </ul>
  );
}
