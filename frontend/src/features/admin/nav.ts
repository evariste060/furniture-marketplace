import {
  Building2,
  ChartLine,
  Headset,
  History,
  House,
  Layers,
  MapPin,
  MessageSquare,
  Settings,
  ShieldCheck,
  Store,
  Tag,
  Users,
  type LucideIcon,
} from "lucide-react";

/** The staff permissions the admin checks (backend app/core/roles.py). The backend enforces every
 * one again; the admin only uses them to decide what to show. */
export type Permission =
  | "staff:self_read"
  | "staff:read"
  | "staff:manage"
  | "audit:read"
  | "orders:fulfil"
  | "orders:read"
  | "inventory:read"
  | "inventory:adjust"
  | "catalog:manage"
  | "catalog:read"
  | "catalog:edit"
  | "delivery:read"
  | "delivery:manage"
  | "settings:read"
  | "settings:manage"
  | "promotions:read"
  | "promotions:manage"
  | "payments:read"
  | "payments:manage"
  | "invoices:recover"
  | "reports:read"
  | "content:manage"
  | "reviews:moderate"
  | "quotes:manage"
  | "support:read"
  | "support:reply"
  | "services:read"
  | "services:manage"
  | "sellers:read"
  | "sellers:manage";

export type NavKey =
  | "dashboard"
  | "sellers"
  | "products"
  | "categories"
  | "promotions"
  | "reviews"
  | "messages"
  | "quotes"
  | "analytics"
  | "settings"
  | "delivery"
  | "staff"
  | "audit";

export type NavItem = {
  key: NavKey;
  href: string;
  Icon: LucideIcon;
  /** Any one of these opens the page. */
  anyOf: Permission[];
  /** Other pages this item stands for in the sidebar. */
  also?: string[];
};

/** The marketplace administrator's sidebar (SC-06, ADR-014 phase 7): marketplace governance,
 * platform support, analytics and platform settings. Store operations (orders, payments, stock,
 * catalogue editing, imports) are the sellers' and have no page here. Quote requests stay under
 * Support; Services and service requests were removed (SC-07). */
export const NAV: {
  group: "overview" | "marketplace" | "support" | "insights" | "platform";
  items: NavItem[];
}[] = [
  {
    group: "overview",
    items: [
      {
        key: "dashboard",
        href: "/admin",
        Icon: House,
        anyOf: ["staff:self_read"],
      },
    ],
  },
  {
    group: "marketplace",
    items: [
      // ADR-014 phase 5: stores and seller applications.
      {
        key: "sellers",
        href: "/admin/sellers",
        Icon: Store,
        anyOf: ["sellers:read"],
      },
      {
        key: "products",
        href: "/admin/products",
        Icon: ShieldCheck,
        anyOf: ["catalog:read"],
      },
      {
        key: "categories",
        href: "/admin/categories",
        Icon: Layers,
        anyOf: ["catalog:read"],
        also: ["/admin/brands"],
      },
      {
        key: "promotions",
        href: "/admin/promotions",
        Icon: Tag,
        anyOf: ["promotions:read"],
      },
      {
        key: "reviews",
        href: "/admin/reviews",
        Icon: MessageSquare,
        anyOf: ["reviews:moderate"],
      },
    ],
  },
  {
    group: "support",
    items: [
      {
        key: "messages",
        href: "/admin/messages",
        Icon: Headset,
        anyOf: ["support:read"],
      },
      {
        key: "quotes",
        href: "/admin/quotes",
        Icon: Building2,
        anyOf: ["quotes:manage"],
      },
    ],
  },
  {
    group: "insights",
    items: [
      {
        key: "analytics",
        href: "/admin/analytics",
        Icon: ChartLine,
        anyOf: ["reports:read"],
      },
    ],
  },
  {
    group: "platform",
    items: [
      {
        key: "settings",
        href: "/admin/settings",
        Icon: Settings,
        anyOf: ["settings:read", "content:manage"],
      },
      {
        key: "delivery",
        href: "/admin/delivery",
        Icon: MapPin,
        anyOf: ["delivery:read"],
      },
      {
        key: "staff",
        href: "/admin/staff",
        Icon: Users,
        anyOf: ["staff:read"],
      },
      {
        key: "audit",
        href: "/admin/audit",
        Icon: History,
        anyOf: ["audit:read"],
      },
    ],
  },
];

export function canOpen(
  permissions: ReadonlySet<string> | readonly string[],
  anyOf: readonly Permission[],
): boolean {
  const held = permissions instanceof Set ? permissions : new Set(permissions);
  return anyOf.some((p) => held.has(p));
}

/** The nav item a path belongs to: the longest matching href. */
export function activeNav(pathname: string): NavKey | null {
  let best: NavItem | null = null;
  for (const { items } of NAV) {
    for (const item of items) {
      const match =
        item.href === "/admin"
          ? pathname === "/admin"
          : [item.href, ...(item.also ?? [])].some(
              (href) => pathname === href || pathname.startsWith(`${href}/`),
            );
      if (match && (!best || item.href.length > best.href.length)) best = item;
    }
  }
  return best?.key ?? null;
}
