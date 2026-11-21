import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import admin from "../../../messages/admin.json";
import en from "../../../messages/en.json";
import { ToastProvider } from "@/components/ui/toast";
import { MessagesView } from "./messages";
import { OrdersView } from "./orders";
import { QuotesView } from "./quotes";
import { ReviewsView } from "./reviews";

/** Orders and Quote requests as a table of records with a drawer (layout owner 2026-11-18): the
 * drawer shows the record and keeps the same actions and permission checks as before. */

// Drawers load their record after opening; give slow, busy test runs time to settle.
configure({ asyncUtilTimeout: 5000 });

const access = vi.hoisted(() => ({ fulfil: true }));
vi.mock("./access", () => ({ useStaffAccess: () => ({ can: (p: string) => p !== "orders:fulfil" || access.fulfil }) }));
const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/admin/orders",
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const SUMMARY = {
  id: "o1",
  order_number: "3S-1001",
  status: "received",
  total: 250000,
  item_count: 2,
  payment_method: "cash_on_delivery",
  payment_status: "pending",
  created_at: "2026-11-17T08:00:00Z",
  customer_name: "Jean Mugabo",
  customer_phone: "+250788111222",
};
const DETAIL = {
  ...SUMMARY,
  updated_at: "2026-11-17T08:00:00Z",
  currency_code: "RWF",
  subtotal: 245000,
  discount_total: 0,
  delivery_fee: 5000,
  tax_total: 0,
  tax_treatment: null,
  discount_code: null,
  delivery_zone: "Kigali",
  recipient_name: "Jean Mugabo",
  recipient_phone: "+250788111222",
  delivery_address: { street_address: "KN 5 Rd", district: "Gasabo", delivery_instructions: "Blue gate" },
  lines: [{ id: "l1", product_name: "Galaxy A15", variant_name: null, sku: "SM-A15", quantity: 2, unit_price: 122500, line_total: 245000, image: null }],
  payment: null,
  payments: [],
  status_history: [{ status: "received", created_at: "2026-11-17T08:00:00Z", reason: null }],
  user_id: null,
  customer_email: "jean@example.com",
  customer_note: null,
  fulfilment_assignee_user_id: null,
  fulfilment_assignee_name: null,
};
const QUOTE = {
  id: "q1",
  reference: "QR-261117-ABCDEF",
  company: "Kigali Tech Ltd",
  contact_name: "Aline Uwase",
  phone: "+250788123456",
  email: null,
  lines: [
    { product: "Laptops", quantity: 20 },
    { product: "Monitors", quantity: 5 },
  ],
  delivery_location: "Remera",
  needed_by: null,
  message: "For our new office",
  locale: "en",
  status: "new",
  handled_by_user_id: null,
  handled_at: null,
  created_at: "2026-11-17T08:00:00Z",
};

const REVIEW = {
  id: "rv1",
  status: "pending",
  rating: 4,
  title: "Great phone",
  body: "Battery lasts two days.",
  author_name: "Eric Habimana",
  product_id: "p1",
  product_name: "Galaxy A15",
  product_slug: "galaxy-a15",
  order_number: "3S-1001",
  moderation_reason: null,
  moderated_at: null,
  created_at: "2026-11-17T08:00:00Z",
};

const THREAD = {
  id: "t1",
  reference: "SUP-261117-ABCDEF",
  topic: "order",
  subject: "Where is my order?",
  order_number: "3S-1001",
  status: "open",
  message_count: 1,
  last_author: "customer",
  last_preview: "It has been three days.",
  last_message_at: "2026-11-17T08:00:00Z",
  created_at: "2026-11-17T08:00:00Z",
  name: "Claude Niyonzima",
  phone: "+250788333444",
  email: null,
  has_account: false,
  locale: "en",
};
const THREAD_DETAIL = { ...THREAD, messages: [{ id: "m1", author: "customer", body: "It has been three days.", staff_name: null, created_at: "2026-11-17T08:00:00Z" }] };

const ok = (data: unknown) => Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });

function renderView(view: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ ...en, admin }} timeZone="Africa/Kigali">
        <ToastProvider closeLabel="Close">{view}</ToastProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  access.fulfil = true;
  nav.params = new URLSearchParams();
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/staff/orders") return ok({ items: [SUMMARY], total: 1, page: 1, size: 20 });
    if (path === "/api/v1/staff/orders/{order_id}") return ok(DETAIL);
    if (path === "/api/v1/staff/orders/assignees") return ok({ items: [] });
    if (path === "/api/v1/staff/quote-requests") return ok({ items: [QUOTE], total: 1, page: 1, size: 20 });
    if (path === "/api/v1/staff/reviews") return ok({ items: [REVIEW], total: 1, page: 1, size: 20 });
    if (path === "/api/v1/staff/support-threads") return ok({ items: [THREAD], total: 1, page: 1, size: 20 });
    if (path === "/api/v1/staff/support-threads/{thread_id}") return ok(THREAD_DETAIL);
    return ok(null);
  });
  api.POST.mockImplementation(() => ok({ ...REVIEW, status: "approved" }));
  api.PATCH.mockImplementation(() => ok({ ...QUOTE, status: "contacted" }));
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});
afterEach(() => vi.clearAllMocks());

describe("orders", () => {
  it("filters by a status card", async () => {
    const user = userEvent.setup();
    renderView(<OrdersView />);
    await user.click(await screen.findByRole("button", { name: /Received/, pressed: false }));
    expect(nav.replace).toHaveBeenCalledWith("/admin/orders?status=received", { scroll: false });
  });

  it("opens an order in the drawer with its items and next step", async () => {
    const user = userEvent.setup();
    renderView(<OrdersView />);
    const row = (await screen.findByText("Jean Mugabo")).closest("tr")!;
    expect(within(row).queryByRole("link", { name: /^Call/ })).not.toBeInTheDocument();
    expect(within(row).getByRole("link", { name: /WhatsApp Jean Mugabo/ })).toHaveAttribute("href", "https://wa.me/250788111222");
    await user.click(within(row).getByRole("button", { name: "Open order 3S-1001" }));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("Galaxy A15", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(within(drawer).getByText(/KN 5 Rd, Gasabo/)).toBeInTheDocument();
    expect(within(drawer).getByRole("link", { name: /Open full page/ })).toHaveAttribute("href", "/admin/orders/o1");
    expect(row.className).toContain("bg-light");
    await user.click(within(drawer).getByRole("button", { name: /Mark as Confirmed/ }));
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/staff/orders/{order_id}/status", { params: { path: { order_id: "o1" } }, body: { status: "confirmed", reason: null } });
  });

  it("shows no status actions without orders:fulfil", async () => {
    access.fulfil = false;
    const user = userEvent.setup();
    renderView(<OrdersView />);
    await user.click(await screen.findByRole("button", { name: "Open order 3S-1001" }));
    const drawer = await screen.findByRole("dialog");
    await within(drawer).findByText("Galaxy A15", undefined, { timeout: 5000 });
    expect(within(drawer).queryByRole("button", { name: /Mark as/ })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Cancel order" })).not.toBeInTheDocument();
  });
});

describe("quote requests", () => {
  it("lists requests in a table and moves one along from the drawer", async () => {
    const user = userEvent.setup();
    renderView(<QuotesView />);
    const row = (await screen.findByText("Kigali Tech Ltd")).closest("tr")!;
    expect(within(row).getByText("2 products · 25 units")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Open the quote request from Kigali Tech Ltd" }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Laptops")).toBeInTheDocument();
    expect(within(drawer).getByText("For our new office")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: /Mark as contacted/ }));
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/staff/quote-requests/{quote_id}", { params: { path: { quote_id: "q1" } }, body: { status: "contacted" } });
  });
});

describe("reviews", () => {
  it("opens a review in the drawer, needs a reason to reject, and approves", async () => {
    const user = userEvent.setup();
    renderView(<ReviewsView />);
    const row = (await screen.findByText("Great phone")).closest("tr")!;
    expect(within(row).getByText("Galaxy A15")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Open the review by Eric Habimana" }));
    expect(row.className).toContain("bg-light");
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Battery lasts two days.")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: /Reject/ }));
    expect(within(drawer).getByRole("alert")).toHaveTextContent("Choose a reason first.");
    expect(api.POST).not.toHaveBeenCalled();
    await user.click(within(drawer).getByRole("button", { name: /Spam/ }));
    await user.click(within(drawer).getByRole("button", { name: /Reject/ }));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/staff/reviews/{review_id}/reject", { params: { path: { review_id: "rv1" } }, body: { reason: "Spam" } });
    await user.click(within(drawer).getByRole("button", { name: /Approve/ }));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/staff/reviews/{review_id}/approve", { params: { path: { review_id: "rv1" } } });
  });
});

describe("support", () => {
  it("opens a conversation in the drawer, replies from the pinned box, and closes it", async () => {
    const user = userEvent.setup();
    renderView(<MessagesView />);
    const row = (await screen.findByText("Where is my order?")).closest("tr")!;
    expect(within(row).getByRole("link", { name: /WhatsApp Claude Niyonzima/ })).toHaveAttribute("href", expect.stringContaining("https://wa.me/250788333444"));
    await user.click(within(row).getByRole("button", { name: "Open the conversation with Claude Niyonzima" }));
    expect(row.className).toContain("bg-light");
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByRole("list", { name: "Conversation" }, { timeout: 5000 })).toHaveTextContent("It has been three days.");
    api.POST.mockImplementation(() => ok(THREAD_DETAIL));
    await user.type(within(drawer).getByRole("textbox", { name: /Reply/ }), "It leaves today.");
    await user.click(within(drawer).getByRole("button", { name: "Send" }));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/staff/support-threads/{thread_id}/messages", { params: { path: { thread_id: "t1" } }, body: { body: "It leaves today." } });
    api.PATCH.mockImplementation(() => ok({ ...THREAD_DETAIL, status: "closed" }));
    await user.click(within(drawer).getByRole("button", { name: "Close conversation" }));
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/staff/support-threads/{thread_id}", { params: { path: { thread_id: "t1" } }, body: { status: "closed" } });
  });
});
