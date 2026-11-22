import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import admin from "../../../messages/admin.json";
import { ToastProvider } from "@/components/ui/toast";
import { StaffAccessProvider } from "./access";
import { activeNav, canOpen, NAV } from "./nav";
import { percentToBps, reasonProblem, SellerDetailView, SellersView, storeDecisions } from "./sellers";

/** ADR-014 phase 5: the admin Sellers page. The backend decides every transition and checks
 * sellers:read and sellers:manage again; these tests check what the admin offers and sends. */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/admin/sellers",
  useSearchParams: () => new URLSearchParams("status=pending"),
}));
const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

// jsdom has no modal dialogs.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.open = false;
};

const ok = (data: unknown) => Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });
const refused = (status: number, code: string) => Promise.resolve({ data: undefined, error: { error: { code, message: code } }, response: { ok: false, status } });
const s = admin.sellers;

const OWNER = { id: "u1", full_name: "Aline Uwase", email: "aline@example.rw", phone: "+250788123456" };
const STORE = {
  id: "s1",
  name: "Oak Works",
  slug: "oak-works",
  status: "pending",
  district: "Gasabo",
  submitted_at: "2026-11-20T08:00:00Z",
  reviewed_at: null,
  owner: OWNER,
  description: "Solid oak furniture.",
  contact_email: "sales@oak.rw",
  contact_phone: "+250788000111",
  sector: "Kimironko",
  street_address: "KG 11 Ave",
  logo: null,
  cover: null,
  status_reason: null,
  approved_at: null,
  reviewed_by: null,
  commission_rate_bps: null,
  effective_commission_rate_bps: 1000,
  history: [{ status: "pending", reason: null, store_name: "Oak Works", actor: null, created_at: "2026-11-20T08:00:00Z" }],
};
const BUCKET = { orders: 0, merchandise_total: 0, commission_amount: 0, seller_net_amount: 0 };
const EARNINGS = { store_id: "s1", currency_code: "RWF", pending: BUCKET, earned: BUCKET };

function wrap(children: ReactNode, permissions = ["sellers:read", "sellers:manage"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ admin }} timeZone="Africa/Kigali">
        <ToastProvider closeLabel="Close">
          <StaffAccessProvider access={{ id: "a1", fullName: "Admin", role: "administrator", permissions }}>{children}</StaffAccessProvider>
        </ToastProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

function serve(store: Record<string, unknown>) {
  api.GET.mockImplementation((path: string) => ok(path.endsWith("/earnings") ? EARNINGS : store));
}

afterEach(() => vi.clearAllMocks());

describe("seller decisions", () => {
  it("offers exactly the backend's transitions", () => {
    expect(storeDecisions("pending")).toEqual(["approved", "rejected"]);
    expect(storeDecisions("approved")).toEqual(["suspended"]);
    expect(storeDecisions("suspended")).toEqual(["approved"]);
    expect(storeDecisions("rejected")).toEqual([]);
  });

  it("needs a reason of 10 characters to reject or suspend, and none to approve", () => {
    expect(reasonProblem("rejected", "  ")).toBe("required");
    expect(reasonProblem("suspended", "too short")).toBe("short");
    expect(reasonProblem("rejected", "Please add your street address.")).toBeNull();
    expect(reasonProblem("approved", "")).toBeNull();
    expect(reasonProblem("approved", "short")).toBe("short");
  });

  it("turns a percentage into whole basis points", () => {
    expect(percentToBps("10")).toBe(1000);
    expect(percentToBps("12.5")).toBe(1250);
    expect(percentToBps("7,25")).toBe(725);
    expect(percentToBps("0")).toBe(0);
    expect(percentToBps("100")).toBe(10000);
    expect(percentToBps("100.01")).toBeNull();
    expect(percentToBps("12.345")).toBeNull();
    expect(percentToBps("-1")).toBeNull();
    expect(percentToBps("ten")).toBeNull();
  });

  it("is in the admin's menu for sellers:read only", () => {
    const item = NAV.flatMap((g) => g.items).find((i) => i.key === "sellers")!;
    expect(item.href).toBe("/admin/sellers");
    expect(canOpen(["sellers:read"], item.anyOf)).toBe(true);
    expect(canOpen(["orders:read", "catalog:manage"], item.anyOf)).toBe(false);
    expect(activeNav("/admin/sellers/s1")).toBe("sellers");
  });
});

describe("the Sellers list", () => {
  it("lists stores filtered by the status in the URL", async () => {
    api.GET.mockImplementation(() => ok({ items: [STORE], total: 1, page: 1, size: 20 }));
    wrap(<SellersView />);
    expect(await screen.findByRole("link", { name: "Oak Works" })).toHaveAttribute("href", "/admin/sellers/s1");
    expect(screen.getByText("aline@example.rw")).toBeInTheDocument();
    expect(api.GET).toHaveBeenCalledWith("/api/v1/staff/sellers", { params: { query: { status: "pending", q: undefined, page: 1, size: 20 } } });
  });
});

describe("a seller's page", () => {
  it("approves a pending application with an optional note", async () => {
    serve(STORE);
    api.PATCH.mockImplementation(() => ok({ ...STORE, status: "approved", approved_at: "2026-11-22T08:00:00Z" }));
    const user = userEvent.setup();
    wrap(<SellerDetailView id="s1" />);
    await user.click(await screen.findByRole("button", { name: s.decide.approved }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: s.decide.approved }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalled());
    expect(api.PATCH.mock.calls[0]).toEqual(["/api/v1/staff/sellers/{store_id}/status", { params: { path: { store_id: "s1" } }, body: { status: "approved", reason: null } }]);
  });

  it("refuses to reject without a reason, then sends it", async () => {
    serve(STORE);
    api.PATCH.mockImplementation(() => ok({ ...STORE, status: "rejected", status_reason: "Please add your street address." }));
    const user = userEvent.setup();
    wrap(<SellerDetailView id="s1" />);
    await user.click(await screen.findByRole("button", { name: s.decide.rejected }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: s.decide.rejected }));
    expect(await within(dialog).findByText(s.errors.required)).toBeInTheDocument();
    expect(api.PATCH).not.toHaveBeenCalled();
    await user.type(within(dialog).getByLabelText(s.reasonLabel), "Please add your street address.");
    await user.click(within(dialog).getByRole("button", { name: s.decide.rejected }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalled());
    expect(api.PATCH.mock.calls[0][1].body).toEqual({ status: "rejected", reason: "Please add your street address." });
  });

  it("explains a decision another administrator already made", async () => {
    serve({ ...STORE, status: "approved", approved_at: "2026-11-21T08:00:00Z" });
    api.PATCH.mockImplementation(() => refused(409, "invalid_store_transition"));
    const user = userEvent.setup();
    wrap(<SellerDetailView id="s1" />);
    await user.click(await screen.findByRole("button", { name: s.decide.suspended }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText(s.reasonLabel), "Repeated late deliveries.");
    await user.click(within(dialog).getByRole("button", { name: s.decide.suspended }));
    expect(await screen.findByRole("alert")).toHaveTextContent(s.errors.stale);
  });

  it("offers Reinstate for a suspended store and links to its public page only while approved", async () => {
    serve({ ...STORE, status: "suspended", status_reason: "Repeated late deliveries.", approved_at: "2026-11-21T08:00:00Z" });
    wrap(<SellerDetailView id="s1" />);
    expect(await screen.findByRole("button", { name: s.decide.reinstate })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: s.viewStore })).toBeNull();
    expect(screen.getByText(/Repeated late deliveries\./, { selector: "p" })).toBeInTheDocument();
  });

  it("sets and clears the commission override in basis points", async () => {
    serve(STORE);
    api.PATCH.mockImplementation((_path: string, { body }: { body: { commission_rate_bps: number | null } }) =>
      ok({ ...STORE, commission_rate_bps: body.commission_rate_bps, effective_commission_rate_bps: body.commission_rate_bps ?? 1000 }),
    );
    const user = userEvent.setup();
    wrap(<SellerDetailView id="s1" />);
    const field = await screen.findByLabelText(s.commission.label);
    await user.type(field, "12.5");
    await user.click(screen.getByRole("button", { name: s.commission.save }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    expect(api.PATCH.mock.calls[0]).toEqual(["/api/v1/staff/sellers/{store_id}/commission", { params: { path: { store_id: "s1" } }, body: { commission_rate_bps: 1250 } }]);
    await user.clear(field);
    await user.click(screen.getByRole("button", { name: s.commission.save }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
    expect(api.PATCH.mock.calls[1][1].body).toEqual({ commission_rate_bps: null });
  });

  it("is read-only without sellers:manage", async () => {
    serve(STORE);
    wrap(<SellerDetailView id="s1" />, ["sellers:read"]);
    expect(await screen.findByText("Aline Uwase")).toBeInTheDocument();
    for (const label of Object.values(s.decide)) expect(screen.queryByRole("button", { name: label })).toBeNull();
    expect(screen.queryByLabelText(s.commission.label)).toBeNull();
  });

  it("treats an unknown store as not found", async () => {
    api.GET.mockImplementation(() => refused(404, "store_not_found"));
    wrap(<SellerDetailView id="missing" />);
    expect(await screen.findByText(s.notFound)).toBeInTheDocument();
  });
});
