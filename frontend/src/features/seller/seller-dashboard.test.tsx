import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import admin from "../../../messages/admin.json";
import en from "../../../messages/en.json";
import { ToastProvider } from "@/components/ui/toast";
import { SellerApplicationView } from "@/features/account/seller-application";
import { CatalogScopeProvider, SELLER_SCOPE } from "@/features/admin/catalog-scope";
import { InventoryView } from "@/features/admin/inventory";
import { ProductEditorView } from "@/features/admin/product-editor";
import { ProductsView } from "@/features/admin/products";
import { SellerOrderDetailView } from "./order-detail";
import { SellerStoreProvider } from "./store-context";

/** ADR-014 phase 4: the seller dashboard's screens call only the seller's own /seller/* routes,
 * never send the platform's merchandising fields and show only the store's own part of an order. */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/seller",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/account/seller",
}));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

// jsdom has no modal dialogs.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.open = false;
};

const ok = (data: unknown, status = 200) => Promise.resolve({ data, error: undefined, response: { ok: true, status } });
const refused = (status: number, code: string) => Promise.resolve({ data: undefined, error: { error: { code, message: code } }, response: { ok: false, status } });
const PAGE = { items: [], total: 0, page: 1, size: 20 };

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ ...en, admin }} timeZone="Africa/Kigali">
        <ToastProvider closeLabel="Close">
          <SellerStoreProvider store={{ id: "s1", name: "Oak Works", slug: "oak-works", commissionRateBps: 1500 }}>
            <CatalogScopeProvider scope={SELLER_SCOPE}>{children}</CatalogScopeProvider>
          </SellerStoreProvider>
        </ToastProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

/** Every path the screens asked for. */
const called = () => [...api.GET.mock.calls, ...api.POST.mock.calls, ...api.PUT.mock.calls, ...api.PATCH.mock.calls, ...api.DELETE.mock.calls].map((c) => c[0] as string);

afterEach(() => vi.clearAllMocks());

describe("the seller's catalogue", () => {
  it("lists only the seller's products, offers New product and no platform merchandising", async () => {
    api.GET.mockImplementation((path: string) => {
      if (path === "/api/v1/catalog/categories" || path === "/api/v1/catalog/brands") return ok([]);
      return ok(PAGE);
    });
    wrap(<ProductsView />);
    await screen.findByText(admin.products.empty);
    expect(screen.getByRole("link", { name: admin.seller.products.new })).toHaveAttribute("href", "/seller/products/new");
    expect(screen.queryByRole("link", { name: admin.products.import })).toBeNull();
    expect(screen.getByText(admin.seller.products.description)).toBeInTheDocument();
    expect(called().every((p) => p.startsWith("/api/v1/seller/") || p.startsWith("/api/v1/catalog/"))).toBe(true);
  });

  it("creates a product in the seller's store without the featured flag", async () => {
    api.GET.mockImplementation((path: string) => {
      if (path === "/api/v1/catalog/categories")
        return ok([{ id: "living", name: "Living room", slug: "living", sort_order: 1, parent_id: null, children: [{ id: "sofas", name: "Sofas", slug: "sofas", sort_order: 1, parent_id: "living", children: [] }] }]);
      if (path === "/api/v1/catalog/brands") return ok([]);
      if (path === "/api/v1/catalog/attributes") return ok({ attributes: [], default_set: [], sets: {} });
      return ok(PAGE);
    });
    api.POST.mockImplementation(() => ok({ id: "p1" }, 201));
    const user = userEvent.setup();
    wrap(<ProductEditorView />);
    expect(screen.queryByRole("checkbox", { name: admin.editor.featured })).toBeNull();
    await user.type(screen.getByLabelText(admin.editor.name), "Oak sofa");
    const main = screen.getByLabelText(admin.editor.mainCategory);
    await waitFor(() => expect(within(main).getByRole("option", { name: "Living room" })).toBeInTheDocument());
    await user.selectOptions(main, "living");
    await user.selectOptions(screen.getByLabelText(admin.editor.subcategory), "sofas");
    await user.click(screen.getByRole("button", { name: admin.editor.create }));
    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    const [path, { body }] = api.POST.mock.calls[0];
    expect(path).toBe("/api/v1/seller/products");
    expect(body).toMatchObject({ name: "Oak sofa", category_id: "sofas", status: "draft" });
    expect(body).not.toHaveProperty("is_featured");
    expect(called().some((p) => p.startsWith("/api/v1/staff/"))).toBe(false);
  });

  it("reads and adjusts stock through the seller's own inventory routes", async () => {
    const row = { variant_id: "v1", product_id: "p1", product_name: "Oak sofa", variant_name: "Grey", sku: "OAK-1", on_hand: 4, reserved_quantity: 1, committed_quantity: 0, available_quantity: 3, low_stock_threshold: 2, is_low_stock: false, is_sellable: true };
    api.GET.mockImplementation(() => ok({ ...PAGE, items: [row], total: 1 }));
    api.POST.mockImplementation(() => ok({}, 201));
    const user = userEvent.setup();
    wrap(<InventoryView />);
    await user.click(await screen.findByRole("button", { name: admin.inventory.adjustOf.replace("{sku}", "OAK-1") }));
    await user.type(screen.getByLabelText(admin.inventory.quantity), "2");
    await user.click(screen.getByRole("button", { name: admin.inventory.save }));
    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    const [path, options] = api.POST.mock.calls[0];
    expect(path).toBe("/api/v1/seller/inventory/{sku}/adjustments");
    expect(options.params.path.sku).toBe("OAK-1");
    expect(options.params.header["Idempotency-Key"]).toBeTruthy();
    expect(options.body).toMatchObject({ quantity_delta: 2 });
    expect(called().every((p) => p.startsWith("/api/v1/seller/"))).toBe(true);
  });
});

const ORDER = {
  id: "so1",
  order_number: "ORD-260101-AB12",
  status: "pending",
  order_status: "received",
  payment_method: "cash_on_delivery",
  payment_status: "pending",
  units: 2,
  recipient_name: "Aline Uwase",
  recipient_phone: "+250788123456",
  created_at: "2026-11-22T08:00:00Z",
  updated_at: "2026-11-22T08:00:00Z",
  subtotal: 60000,
  discount_total: 3000,
  merchandise_total: 57000,
  commission_rate_bps: 1500,
  commission_amount: 8550,
  seller_net_amount: 48450,
  delivery_zone: "Gasabo",
  delivery_address: { district: "Gasabo", sector: "Kimironko", street_address: "KG 11 Ave" },
  lines: [{ sku: "OAK-1", product_name: "Oak sofa", variant_name: "Grey", quantity: 2, unit_price: 30000, line_subtotal: 60000, discount_amount: 3000, line_total: 57000 }],
  status_history: [{ status: "pending", reason: null, created_at: "2026-11-22T08:00:00Z" }],
};

describe("a seller order", () => {
  it("shows the store's own part and takes its one next step", async () => {
    api.GET.mockImplementation(() => ok(ORDER));
    api.PATCH.mockImplementation(() => ok({ ...ORDER, status: "confirmed" }));
    const user = userEvent.setup();
    wrap(<SellerOrderDetailView id="so1" />);
    expect(await screen.findByText("Oak sofa")).toBeInTheDocument();
    expect(screen.getByText("Aline Uwase")).toBeInTheDocument();
    expect(screen.getByText("KG 11 Ave")).toBeInTheDocument();
    expect(screen.getByText(admin.seller.order.money.commission.replace("{rate}", "15"))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: admin.seller.order.action.confirmed }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: admin.seller.order.action.confirmed }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalled());
    const [path, options] = api.PATCH.mock.calls[0];
    expect(path).toBe("/api/v1/seller/orders/{seller_order_id}/status");
    expect(options).toEqual({ params: { path: { seller_order_id: "so1" } }, body: { status: "confirmed", reason: null } });
  });

  it("explains a refused step", async () => {
    api.GET.mockImplementation(() => ok({ ...ORDER, status: "confirmed", order_status: "received" }));
    api.PATCH.mockImplementation(() => refused(409, "seller_order_awaiting_other_stores"));
    const user = userEvent.setup();
    wrap(<SellerOrderDetailView id="so1" />);
    await user.click(await screen.findByRole("button", { name: admin.seller.order.action.processing }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: admin.seller.order.action.processing }));
    expect(await screen.findByRole("alert")).toHaveTextContent(admin.seller.order.errors.awaitingOtherStores);
  });

  it("offers no step on a cancelled or delivered order", async () => {
    api.GET.mockImplementation(() => ok({ ...ORDER, status: "cancelled", order_status: "cancelled" }));
    wrap(<SellerOrderDetailView id="so1" />);
    expect(await screen.findByText(admin.seller.order.hint.cancelled)).toBeInTheDocument();
    for (const label of Object.values(admin.seller.order.action)) expect(screen.queryByRole("button", { name: label })).toBeNull();
  });

  it("treats another store's order as not found", async () => {
    api.GET.mockImplementation(() => refused(404, "seller_order_not_found"));
    wrap(<SellerOrderDetailView id="other" />);
    expect(await screen.findByText(admin.seller.order.notFound)).toBeInTheDocument();
  });
});

const seller = en.store.account.seller;

describe("Sell with us (Account)", () => {
  const fill = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(screen.getByLabelText(seller.name), "Oak Works");
    await user.type(screen.getByLabelText(seller.email), "sales@oak.rw");
    await user.type(screen.getByLabelText(seller.phone), "0788 123 456");
    await user.type(screen.getByLabelText(seller.district), "Gasabo");
  };

  it("applies once, then shows the application under review", async () => {
    api.GET.mockImplementation((path: string) => (path === "/api/v1/seller/application" ? refused(404, "store_not_found") : ok({ email: "a@b.rw" })));
    api.POST.mockImplementation(() => ok({ id: "s1", name: "Oak Works", status: "pending", status_reason: null, submitted_at: "2026-11-22T08:00:00Z", contact_email: "sales@oak.rw", contact_phone: "+250788123456", district: "Gasabo" }, 201));
    const user = userEvent.setup();
    wrap(<SellerApplicationView />);
    await user.click(await screen.findByRole("button", { name: seller.submit }));
    expect(api.POST).not.toHaveBeenCalled(); // checked in the browser first
    await fill(user);
    await user.click(screen.getByRole("button", { name: seller.submit }));
    await waitFor(() => expect(api.POST).toHaveBeenCalled());
    const [path, { body }] = api.POST.mock.calls[0];
    expect(path).toBe("/api/v1/seller/application");
    expect(Object.keys(body).sort()).toEqual(["contact_email", "contact_phone", "description", "district", "name", "sector", "street_address"]);
    expect(await screen.findByText(seller.status.pending)).toBeInTheDocument();
  });

  it("asks for a verified email when the backend requires one", async () => {
    api.GET.mockImplementation((path: string) => (path === "/api/v1/seller/application" ? refused(404, "store_not_found") : ok({ email: "a@b.rw" })));
    api.POST.mockImplementation(() => refused(403, "email_verification_required"));
    const user = userEvent.setup();
    wrap(<SellerApplicationView />);
    await screen.findByRole("button", { name: seller.submit });
    await fill(user);
    await user.click(screen.getByRole("button", { name: seller.submit }));
    expect(await screen.findByText(seller.verifyFirst)).toBeInTheDocument();
  });

  it("opens the seller dashboard once approved, with no form", async () => {
    api.GET.mockImplementation(() => ok({ id: "s1", name: "Oak Works", status: "approved", status_reason: null, submitted_at: "2026-11-22T08:00:00Z", contact_email: "sales@oak.rw", contact_phone: "+250788123456", district: "Gasabo" }));
    wrap(<SellerApplicationView />);
    expect(await screen.findByRole("link", { name: seller.openDashboard })).toHaveAttribute("href", "/seller");
    expect(screen.queryByRole("button", { name: seller.submit })).toBeNull();
    expect(screen.queryByLabelText(seller.name)).toBeNull();
  });

  it("shows why a store was rejected and resubmits it", async () => {
    const rejected = { id: "s1", name: "Oak Works", status: "rejected", status_reason: "Please add your street address.", submitted_at: "2026-11-22T08:00:00Z", description: null, contact_email: "sales@oak.rw", contact_phone: "+250788123456", district: "Gasabo", sector: null, street_address: null };
    api.GET.mockImplementation((path: string) => (path === "/api/v1/seller/application" ? ok(rejected) : ok({ email: "a@b.rw" })));
    api.PUT.mockImplementation(() => ok({ ...rejected, status: "pending", status_reason: null }));
    const user = userEvent.setup();
    wrap(<SellerApplicationView />);
    expect(await screen.findByText(seller.reason.replace("{reason}", rejected.status_reason))).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Street address/), "KG 11 Ave");
    await user.click(screen.getByRole("button", { name: seller.resubmit }));
    await waitFor(() => expect(api.PUT).toHaveBeenCalled());
    expect(api.PUT.mock.calls[0][1].body).toMatchObject({ street_address: "KG 11 Ave", name: "Oak Works" });
  });
});
