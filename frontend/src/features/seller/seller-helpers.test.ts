import { afterEach, describe, expect, it, vi } from "vitest";
import { flattenCategories, withoutMerchandising } from "@/features/admin/catalog-scope";
import { adminLocaleCookie } from "@/i18n/admin-locale";
import { ApiError } from "@/lib/api/errors";
import { isSellerPath } from "@/lib/auth";
import { moveErrorKey, nextSellerStep } from "./orders-api";
import { activeSellerNav } from "./shell";
import { applicationBody, canEditApplication, checkStoreForm, storeForm } from "./store-form";
import { percent } from "./store-context";

/** ADR-014 phase 4: the seller dashboard's rules that do not need a page. */

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));
vi.mock("@/lib/api/server", () => ({ hasSession: vi.fn(), sessionApi: vi.fn() }));

afterEach(() => vi.clearAllMocks());

const reply = (status: number, data?: unknown, error?: unknown) => ({ data, error, response: { status, ok: status < 300 } });

describe("seller order steps", () => {
  it("offers exactly the backend's one next step, and none at the end", () => {
    expect(nextSellerStep("pending")).toBe("confirmed");
    expect(nextSellerStep("confirmed")).toBe("processing");
    expect(nextSellerStep("processing")).toBe("dispatched");
    expect(nextSellerStep("dispatched")).toBe("delivered");
    expect(nextSellerStep("delivered")).toBeNull();
    // Cancelling is the platform's (whole order), never a seller step.
    expect(nextSellerStep("cancelled")).toBeNull();
  });

  it("explains each refused step by the backend's code", () => {
    const refused = (code: string) => new ApiError(409, code, "refused");
    expect(moveErrorKey(refused("seller_order_awaiting_payment"))).toBe("awaitingPayment");
    expect(moveErrorKey(refused("seller_order_awaiting_other_stores"))).toBe("awaitingOtherStores");
    expect(moveErrorKey(refused("invalid_transition"))).toBe("invalid");
    expect(moveErrorKey(refused("inventory_conflict"))).toBe("inventory");
    expect(moveErrorKey(new ApiError(500, "server_error", "boom"))).toBe("failed");
    expect(moveErrorKey(new Error("offline"))).toBe("failed");
  });
});

describe("seller navigation", () => {
  it("marks the longest matching link", () => {
    expect(activeSellerNav("/seller")).toBe("dashboard");
    expect(activeSellerNav("/seller/orders/abc")).toBe("orders");
    expect(activeSellerNav("/seller/products/new")).toBe("products");
    expect(activeSellerNav("/seller/inventory")).toBe("inventory");
    expect(activeSellerNav("/seller/store")).toBe("store");
    expect(activeSellerNav("/seller/storefront")).toBeNull();
  });

  it("opens /seller with a full page load after signing in, outside the locale routing", () => {
    expect(isSellerPath("/seller")).toBe(true);
    expect(isSellerPath("/seller/orders?status=pending")).toBe(true);
    expect(isSellerPath("/seller?x=1")).toBe(true);
    expect(isSellerPath("/sellers")).toBe(false);
    expect(isSellerPath("/account/seller")).toBe(false);
  });

  it("keeps the seller dashboard's language apart from the admin's", () => {
    expect(adminLocaleCookie("rw")).toContain("Path=/admin");
    expect(adminLocaleCookie("rw", "/seller")).toBe("admin_locale=rw; Path=/seller; Max-Age=31536000; SameSite=Lax");
  });

  it("shows commission basis points as a percentage", () => {
    expect(percent(1000)).toBe("10");
    expect(percent(1250)).toBe("12.5");
    expect(percent(0)).toBe("0");
  });
});

describe("store form", () => {
  const good = { name: "Kigali Oak Works", description: "", email: "sales@oak.rw", phone: "0788 123 456", district: "Gasabo", sector: "", street: "" };

  it("accepts the backend's rules and names each problem", () => {
    expect(checkStoreForm(good)).toEqual({});
    expect(checkStoreForm({ ...good, name: " K ", email: "nope", phone: "12345", district: " " })).toEqual({ name: "name", email: "email", phone: "phone", district: "district" });
    expect(checkStoreForm({ ...good, name: "x".repeat(121) })).toEqual({ name: "name" });
  });

  it("sends every field, blanks as null, and never a status, slug, owner or commission", () => {
    const body = applicationBody({ ...good, description: "  ", sector: " Kimironko " });
    expect(body).toEqual({ name: "Kigali Oak Works", description: null, contact_email: "sales@oak.rw", contact_phone: "0788 123 456", district: "Gasabo", sector: "Kimironko", street_address: null });
  });

  it("fills the form from a store", () => {
    expect(storeForm(null).name).toBe("");
    const form = storeForm({ name: "Oak", description: null, contact_email: "a@b.rw", contact_phone: "+250788123456", district: "Gasabo", sector: null, street_address: "KG 11 Ave" });
    expect(form).toMatchObject({ name: "Oak", description: "", email: "a@b.rw", district: "Gasabo", sector: "", street: "KG 11 Ave" });
    expect(form.phone.replace(/\D/g, "")).toContain("788123456");
  });

  it("opens the application form only before approval", () => {
    expect(canEditApplication(null)).toBe(true);
    expect(canEditApplication("pending")).toBe(true);
    expect(canEditApplication("rejected")).toBe(true);
    expect(canEditApplication("approved")).toBe(false);
    expect(canEditApplication("suspended")).toBe(false);
  });
});

describe("catalogue scope", () => {
  it("never sends the platform's merchandising fields from a seller", () => {
    expect(withoutMerchandising({ name: "Sofa", is_featured: true })).toEqual({ name: "Sofa" });
    expect(withoutMerchandising({ status: "active", is_featured: undefined })).toEqual({ status: "active" });
  });

  it("flattens the public category tree for the editor's pickers", () => {
    const tree = [
      { id: "living", name: "Living room", slug: "living", sort_order: 1, parent_id: null, children: [{ id: "sofas", name: "Sofas", slug: "sofas", sort_order: 1, parent_id: "living", children: [] }] },
    ];
    expect(flattenCategories(tree as never)).toEqual([
      { id: "living", name: "Living room", parent_id: null, is_active: true, sort_order: 1, slug: "living" },
      { id: "sofas", name: "Sofas", parent_id: "living", is_active: true, sort_order: 1, slug: "sofas" },
    ]);
  });
});

describe("the seller dashboard's server check", () => {
  async function visitor(responses: Record<string, ReturnType<typeof reply>>, session = true) {
    vi.resetModules();
    const server = await import("@/lib/api/server");
    vi.mocked(server.hasSession).mockResolvedValue(session);
    vi.mocked(server.sessionApi).mockResolvedValue({ GET: vi.fn(async (path: string) => responses[path] ?? reply(500)) } as never);
    const { getSellerVisitor } = await import("@/lib/seller");
    return getSellerVisitor();
  }
  const store = (status: string) => ({ id: "s1", name: "Oak", slug: "oak", status, status_reason: null, effective_commission_rate_bps: 1000 });
  const ME = "/api/v1/auth/me";
  const STORE = "/api/v1/seller/store";
  const APPLICATION = "/api/v1/seller/application";

  it("sends a visitor without a session to sign in", async () => {
    expect(await visitor({}, false)).toEqual({ kind: "signed-out" });
    expect(await visitor({ [ME]: reply(401) })).toEqual({ kind: "signed-out" });
  });

  it("never opens the dashboard for staff", async () => {
    expect(await visitor({ [ME]: reply(200, { is_staff: true, full_name: "Admin" }), [STORE]: reply(200, store("approved")) })).toEqual({ kind: "staff" });
  });

  it("opens it only for the owner of an approved store", async () => {
    const me = reply(200, { is_staff: false, full_name: "Aline Uwase" });
    expect(await visitor({ [ME]: me, [STORE]: reply(200, store("approved")) })).toMatchObject({ kind: "seller", fullName: "Aline Uwase", store: { id: "s1" } });
    const refused = reply(403, undefined, { error: { code: "seller_not_approved" } });
    expect(await visitor({ [ME]: me, [STORE]: refused, [APPLICATION]: reply(200, store("suspended")) })).toMatchObject({ kind: "not-approved", store: { status: "suspended" } });
    expect(await visitor({ [ME]: me, [STORE]: refused, [APPLICATION]: reply(404) })).toEqual({ kind: "no-store" });
  });
});
