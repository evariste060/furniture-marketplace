import { Boxes, Building2, ClipboardCheck, CreditCard, FileUp, Headset, History, House, Layers, MapPin, MessageSquare, Package, Settings, ShoppingCart, Store, Tag, Upload, Users, Wrench, type LucideIcon } from "lucide-react";

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
  "dashboard" | "orders" | "payments" | "quotes" | "serviceRequests" | "messages" | "services" | "products" | "bulkImages" | "categories" | "import" | "inventory" | "reviews" | "delivery" | "promotions" | "sellers" | "staff" | "settings" | "audit";

export type NavItem = {
  key: NavKey;
  href: string;
  Icon: LucideIcon;
  /** Any one of these opens the page. */
  anyOf: Permission[];
  /** Other pages this item stands for in the sidebar. */
  also?: string[];
};

/** AdminSidebar.dc.html groups. Analytics, Reports and Notifications are left out until their
 * backend modules (17, 18) exist. */
export const NAV: {
  group: "overview" | "orders" | "catalogue" | "store" | "system";
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
    group: "orders",
    items: [
      {
        key: "orders",
        href: "/admin/orders",
        Icon: ShoppingCart,
        anyOf: ["orders:read"],
      },
      {
        key: "payments",
        href: "/admin/payments",
        Icon: CreditCard,
        anyOf: ["payments:read"],
      },
      {
        key: "quotes",
        href: "/admin/quotes",
        Icon: Building2,
        anyOf: ["quotes:manage"],
      },
      {
        key: "serviceRequests",
        href: "/admin/service-requests",
        Icon: ClipboardCheck,
        anyOf: ["services:read"],
      },
      {
        key: "messages",
        href: "/admin/messages",
        Icon: Headset,
        anyOf: ["support:read"],
      },
    ],
  },
  {
    group: "catalogue",
    items: [
      {
        key: "products",
        href: "/admin/products",
        Icon: Package,
        anyOf: ["catalog:read"],
      },
      {
        key: "bulkImages",
        href: "/admin/products/images",
        Icon: Upload,
        anyOf: ["catalog:manage"],
      },
      {
        key: "categories",
        href: "/admin/categories",
        Icon: Layers,
        anyOf: ["catalog:read"],
        also: ["/admin/brands"],
      },
      {
        key: "import",
        href: "/admin/import",
        Icon: FileUp,
        anyOf: ["catalog:manage"],
      },
      {
        key: "inventory",
        href: "/admin/inventory",
        Icon: Boxes,
        anyOf: ["inventory:read"],
      },
      {
        key: "reviews",
        href: "/admin/reviews",
        Icon: MessageSquare,
        anyOf: ["reviews:moderate"],
      },
      {
        key: "services",
        href: "/admin/services",
        Icon: Wrench,
        anyOf: ["services:read"],
      },
    ],
  },
  {
    group: "store",
    items: [
      {
        key: "delivery",
        href: "/admin/delivery",
        Icon: MapPin,
        anyOf: ["delivery:read"],
      },
      {
        key: "promotions",
        href: "/admin/promotions",
        Icon: Tag,
        anyOf: ["promotions:read"],
      },
      {
        // ADR-014 phase 5: stores and seller applications.
        key: "sellers",
        href: "/admin/sellers",
        Icon: Store,
        anyOf: ["sellers:read"],
      },
    ],
  },
  {
    group: "system",
    items: [
      {
        key: "staff",
        href: "/admin/staff",
        Icon: Users,
        anyOf: ["staff:read"],
      },
      {
        key: "settings",
        href: "/admin/settings",
        Icon: Settings,
        anyOf: ["settings:read", "content:manage"],
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

export function canOpen(permissions: ReadonlySet<string> | readonly string[], anyOf: readonly Permission[]): boolean {
  const held = permissions instanceof Set ? permissions : new Set(permissions);
  return anyOf.some((p) => held.has(p));
}

/** The nav item a path belongs to: the longest matching href ("/admin/products/images" before
 * "/admin/products"). */
export function activeNav(pathname: string): NavKey | null {
  let best: NavItem | null = null;
  for (const { items } of NAV) {
    for (const item of items) {
      const match =
        item.href === "/admin"
          ? pathname === "/admin"
          : [item.href, ...(item.also ?? [])].some((href) => pathname === href || pathname.startsWith(`${href}/`));
      if (match && (!best || item.href.length > best.href.length)) best = item;
    }
  }
  return best?.key ?? null;
}
