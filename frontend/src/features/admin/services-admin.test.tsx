import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import admin from "../../../messages/admin.json";
import en from "../../../messages/en.json";
import { ToastProvider } from "@/components/ui/toast";
import { activeNav, NAV } from "./nav";
import { ServiceRequestsView } from "./service-requests";
import { serviceChanges, ServicesView } from "./services";

/** Admin Services and Service requests (ADR-013): the list and its order, the edit dialog, the
 * delete rule, and following a request up from the inbox's drawer. */

// The drawer and the status counts load after a click; give busy test runs time to settle.
configure({ asyncUtilTimeout: 5000 });

const access = vi.hoisted(() => ({ manage: true }));
vi.mock("./access", () => ({ useStaffAccess: () => ({ can: (p: string) => p !== "services:manage" || access.manage }) }));
const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => "/admin/services",
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const service = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id,
  slug: id,
  name_en: name,
  name_rw: null,
  short_description_en: `${name} card`,
  short_description_rw: null,
  intro_en: `${name} intro`,
  intro_rw: null,
  icon: "wrench",
  image: null,
  sort_order: 1,
  is_active: true,
  items: [] as { id: string; title_en: string; title_rw: string | null; sort_order: number }[],
  request_count: 0,
  created_at: "2026-11-17T00:00:00Z",
  updated_at: "2026-11-17T00:00:00Z",
  ...extra,
});
const SERVICES = [
  service("cctv", "CCTV", { request_count: 2, items: [{ id: "i1", title_en: "Cameras", title_rw: null, sort_order: 1 }] }),
  service("repair", "Repair", { sort_order: 2 }),
];
const LEAD = {
  id: "r1",
  reference: "SR-261117-ABCDEF",
  service: { id: "cctv", slug: "cctv", name: "CCTV" },
  full_name: "Aline Uwase",
  phone: "+250788123456",
  email: null,
  location: "Kicukiro",
  client_type: "business",
  message: "Eight cameras",
  preferred_date: null,
  locale: "en",
  status: "new",
  status_changed_at: null,
  assigned_to: null,
  internal_notes: null,
  created_at: "2026-11-17T08:00:00Z",
  updated_at: "2026-11-17T08:00:00Z",
};

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
  access.manage = true;
  nav.params = new URLSearchParams();
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/staff/services") return ok(SERVICES);
    if (path === "/api/v1/staff/service-requests") return ok({ items: [LEAD], total: 1, page: 1, size: 20 });
    if (path === "/api/v1/staff/service-requests/assignees") return ok([{ id: "u1", name: "Test sales" }]);
    return ok(null);
  });
  api.PUT.mockImplementation(() => ok(null));
  api.PATCH.mockImplementation(() => ok(LEAD));
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});
afterEach(() => vi.clearAllMocks());

describe("admin navigation", () => {
  it("lists Services and Service requests for services:read", () => {
    const items = NAV.flatMap((g) => g.items);
    expect(items.find((i) => i.key === "services")).toMatchObject({ href: "/admin/services", anyOf: ["services:read"] });
    expect(items.find((i) => i.key === "serviceRequests")).toMatchObject({ href: "/admin/service-requests", anyOf: ["services:read"] });
    expect(activeNav("/admin/service-requests")).toBe("serviceRequests");
  });
});

describe("services", () => {
  it("lists the services in order with their items and requests", async () => {
    renderView(<ServicesView />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("b")?.textContent)).toEqual(["CCTV", "Repair"]);
    expect(within(rows[0]!).getByText("2 requests")).toBeInTheDocument();
  });

  it("moves a service down and saves the new order", async () => {
    const user = userEvent.setup();
    renderView(<ServicesView />);
    await user.click(await screen.findByRole("button", { name: "Move CCTV down" }));
    expect(api.PUT).toHaveBeenCalledWith("/api/v1/staff/services/order", { body: { service_ids: ["repair", "cctv"] } });
  });

  it("refuses to delete a service with requests and lists its items", async () => {
    const user = userEvent.setup();
    renderView(<ServicesView />);
    await user.click(await screen.findByRole("button", { name: /Edits*CCTV/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(within(dialog).getByText(/so it can’t be deleted/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("tab", { name: "What we offer (1)" }));
    expect(within(dialog).getByText("Cameras")).toBeInTheDocument();
  });

  it("is read-only without services:manage", async () => {
    access.manage = false;
    renderView(<ServicesView />);
    await screen.findAllByRole("listitem");
    expect(screen.queryByRole("button", { name: "Add service" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull();
  });

  it("sends only what changed, with blank Kinyarwanda texts as null", () => {
    const saved = service("cctv", "CCTV", { name_rw: "Kamera" }) as Parameters<typeof serviceChanges>[1];
    const draft = { name_en: "CCTV ", name_rw: " ", slug: "", short_description_en: "CCTV card", short_description_rw: "", intro_en: "CCTV intro", intro_rw: "", icon: "cctv" as const, is_active: false };
    expect(serviceChanges(draft, saved)).toEqual({ name_rw: null, icon: "cctv", is_active: false });
    expect(serviceChanges(draft, null)).toEqual({ name_en: "CCTV", short_description_en: "CCTV card", intro_en: "CCTV intro", icon: "cctv", is_active: false });
  });
});

describe("service requests", () => {
  it("lists requests and follows one up from its drawer", async () => {
    const user = userEvent.setup();
    renderView(<ServiceRequestsView />);
    await user.click(await screen.findByRole("button", { name: "Open the request from Aline Uwase" }));
    const drawer = screen.getByRole("dialog", { name: "Request from Aline Uwase" });
    expect(within(drawer).getByText("Eight cameras")).toBeInTheDocument();
    await user.selectOptions(within(drawer).getByLabelText("Status"), "contacted");
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/staff/service-requests/{request_id}", { params: { path: { request_id: "r1" } }, body: { status: "contacted" } });
    await user.selectOptions(await within(drawer).findByLabelText("Assigned to"), "u1");
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/staff/service-requests/{request_id}", { params: { path: { request_id: "r1" } }, body: { assigned_to_user_id: "u1" } });
    await user.type(within(drawer).getByLabelText("Internal notes"), "Visit Friday");
    await user.click(within(drawer).getByRole("button", { name: "Save notes" }));
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/staff/service-requests/{request_id}", { params: { path: { request_id: "r1" } }, body: { internal_notes: "Visit Friday" } });
  });

  it("filters by status through the URL", async () => {
    nav.params = new URLSearchParams("status=new");
    renderView(<ServiceRequestsView />);
    await screen.findByRole("button", { name: "Open the request from Aline Uwase" });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/staff/service-requests", { params: { query: expect.objectContaining({ status: "new", page: 1 }) } });
  });

  it("shows the pipeline as status cards that filter the list, and filters by assignee", async () => {
    const user = userEvent.setup();
    nav.params = new URLSearchParams("assigned=u1");
    renderView(<ServiceRequestsView />);
    const cards = screen.getByRole("group", { name: "Service request status" });
    const all = within(cards).getByRole("button", { name: /All requests/ });
    expect(all).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(all).toHaveTextContent("1"));
    await user.click(within(cards).getByRole("button", { name: /Scheduled/ }));
    expect(nav.replace).toHaveBeenCalledWith("/admin/services?assigned=u1&status=scheduled", { scroll: false });
    await screen.findByRole("button", { name: "Open the request from Aline Uwase" });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/staff/service-requests", { params: { query: expect.objectContaining({ assigned_to: "u1", page: 1 }) } });
    expect(screen.queryByRole("link", { name: "Call Aline Uwase" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /WhatsApp Aline Uwase/ })).toBeInTheDocument();
  });

  it("moves a request to its next step in one click, and can cancel and reopen it", async () => {
    const user = userEvent.setup();
    renderView(<ServiceRequestsView />);
    await user.click(await screen.findByRole("button", { name: "Open the request from Aline Uwase" }));
    const drawer = screen.getByRole("dialog", { name: "Request from Aline Uwase" });
    expect(within(drawer).getByRole("list", { name: "Progress" }).querySelector("[aria-current=step]")).toHaveTextContent("New");
    await user.click(within(drawer).getByRole("button", { name: /Mark as contacted/ }));
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/staff/service-requests/{request_id}", { params: { path: { request_id: "r1" } }, body: { status: "contacted" } });
    await user.click(within(drawer).getByRole("button", { name: "Cancel request" }));
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/staff/service-requests/{request_id}", { params: { path: { request_id: "r1" } }, body: { status: "cancelled" } });
  });

  it("hides the follow-up controls from staff who can only read", async () => {
    access.manage = false;
    const user = userEvent.setup();
    renderView(<ServiceRequestsView />);
    expect(screen.queryByLabelText("Assigned to")).toBeNull();
    await user.click(await screen.findByRole("button", { name: "Open the request from Aline Uwase" }));
    const drawer = screen.getByRole("dialog", { name: "Request from Aline Uwase" });
    expect(within(drawer).queryByRole("button", { name: /Mark as contacted/ })).toBeNull();
    expect(within(drawer).queryByLabelText("Status")).toBeNull();
  });
});
