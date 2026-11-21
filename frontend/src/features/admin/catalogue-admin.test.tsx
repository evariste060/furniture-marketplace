import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import admin from "../../../messages/admin.json";
import en from "../../../messages/en.json";
import { ToastProvider } from "@/components/ui/toast";
import { brandsOfCategory, BrandsView, CategoriesView, filterBrands, menusByBrand, newSubcategoryNames, NO_CATEGORY } from "./categories";
import { groupBrandOptions } from "./category-options";
import { activeNav } from "./nav";

/** Categories & brands, redesigned 2026-11-16: main categories beside the chosen one's detail
 * (Subcategories, Store menu, Details), and a Brands tab with every brand in one table. */

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), pathname: "/admin/categories", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
}));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const cat = (id: string, name: string, parent_id: string | null, sort_order: number, extra: Record<string, unknown> = {}) => ({
  id,
  name,
  slug: id,
  parent_id,
  sort_order,
  is_active: true,
  product_count: 0,
  description: null,
  image: null,
  spotlight_product_id: null,
  menu_brand_ids: [] as string[],
  created_at: "2026-11-16T00:00:00Z",
  updated_at: "2026-11-16T00:00:00Z",
  ...extra,
});
const brand = (id: string, name: string, extra: Record<string, unknown> = {}) => ({ id, name, slug: id, is_active: true, logo: null, product_count: 0, created_at: "", updated_at: "", ...extra });

const CATEGORIES = [
  cat("phones", "Phones & Tablets", null, 1, { menu_brand_ids: ["samsung", "apple"] }),
  cat("appliances", "Home Appliances", null, 2),
  cat("smartphones", "Smartphones", "phones", 1, { product_count: 12 }),
  cat("tablets", "Tablets", "phones", 2, { is_active: false }),
  cat("fridges", "Refrigerators", "appliances", 1, { product_count: 2 }),
  cat("fans", "Fans", "appliances", 2),
];
const BRANDS = [
  brand("samsung", "Samsung", { product_count: 7, category_ids: ["phones", "appliances"] }),
  brand("apple", "Apple", { product_count: 4, category_ids: ["phones"] }),
  brand("nokia", "Nokia", { is_active: false, category_ids: [] }),
  brand("lg", "LG", { category_ids: ["appliances"] }),
];

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
  nav.params = new URLSearchParams();
  nav.pathname = "/admin/categories";
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/staff/categories") return ok({ items: CATEGORIES });
    if (path === "/api/v1/staff/brands") return ok({ items: BRANDS });
    return ok({ items: [], total: 0, page: 1, size: 100 });
  });
  // jsdom has no <dialog> methods.
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(() => vi.clearAllMocks());

describe("categories page", () => {
  it("lists the main categories and opens the first with its subcategories in order", async () => {
    renderView(<CategoriesView />);
    const list = await screen.findByRole("region", { name: /Main categories/ });
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Phones & Tablets2 subcategories12 products",
      "Home Appliances2 subcategories2 products",
    ]);
    expect(within(list).getByRole("button", { name: /Phones & Tablets/ })).toHaveAttribute("aria-current", "true");
    const detail = screen.getByRole("region", { name: "Phones & Tablets" });
    const rows = within(detail).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").slice(0, 2).map((c) => c.textContent))).toEqual([
      ["1", "Smartphones/smartphones"],
      ["2", "Tablets/tablets"],
    ]);
    expect(within(rows[1]).getByText("Hidden")).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "View Phones & Tablets on the store (opens in a new tab)" })).toHaveAttribute("href", "/category/phones");
    expect(within(rows[0]).getByRole("link", { name: "View the 12 products of Smartphones" })).toHaveAttribute("href", "/admin/products?category=smartphones");
  });

  it("keeps the chosen category and tab in the URL", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    await user.click(await screen.findByRole("button", { name: /Home Appliances/ }));
    expect(nav.replace).toHaveBeenLastCalledWith("/admin/categories?category=appliances", { scroll: false });
    await user.click(screen.getByRole("tab", { name: "Store menu" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/admin/categories?category=phones&tab=menu", { scroll: false });
  });

  it("shows what the store menu lists: the brand list, or else the subcategories", async () => {
    nav.params = new URLSearchParams("category=phones&tab=menu");
    const { unmount } = renderView(<CategoriesView />);
    expect(await screen.findByText("Lists brands")).toBeInTheDocument();
    const listed = await screen.findByRole("list", { name: "Brands in the store menu" });
    expect(within(listed).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["1SASamsung", "2APApple"]);
    unmount();

    nav.params = new URLSearchParams("category=appliances&tab=menu");
    renderView(<CategoriesView />);
    expect(await screen.findByText("Lists subcategories")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Subcategories" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Refrigerators", "Fans"]);
  });

  it("finds subcategories by name under their main category", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    await user.type(await screen.findByRole("searchbox", { name: "Search categories" }), "fri");
    const list = screen.getByRole("region", { name: /Main categories/ });
    expect(within(list).queryByRole("button", { name: /Phones & Tablets/ })).toBeNull();
    const found = within(list).getByRole("list", { name: "Matching subcategories in Home Appliances" });
    await user.click(within(found).getByRole("button", { name: "Refrigerators" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/admin/categories?category=appliances", { scroll: false });
  });

  it("edits a main category in a tabbed dialog, opening the store menu tab from there", async () => {
    const user = userEvent.setup();
    nav.params = new URLSearchParams("category=phones&tab=menu");
    renderView(<CategoriesView />);
    await user.click(await screen.findByRole("button", { name: "Edit brand list" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Phones & Tablets" });
    expect(within(dialog).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Basics", "Image & spotlight", "Store menu"]);
    expect(within(dialog).getByRole("tab", { name: "Store menu" })).toHaveAttribute("aria-selected", "true");
  });

  it("gives a subcategory's dialog no store menu tab", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    await user.click(await screen.findByRole("button", { name: "Edit Smartphones" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Smartphones" });
    expect(within(dialog).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Basics", "Image & spotlight"]);
  });
});

describe("adding subcategories", () => {
  beforeEach(() => {
    let n = 0;
    api.POST.mockImplementation((_path: string, { body }: { body: { name: string; parent_id: string | null } }) =>
      body.name === "Cameras"
        ? Promise.resolve({ data: undefined, error: { error: { code: "slug_taken", message: "taken" } }, response: { ok: false, status: 409 } })
        : ok({ id: `new${++n}`, name: body.name, parent_id: body.parent_id }),
    );
  });

  it("adds one on Enter, after the existing ones, and keeps the box ready for the next", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    const box = await screen.findByRole("textbox", { name: "Add subcategories" });
    await user.type(box, "  Smart   Watches {Enter}");
    expect(api.POST).toHaveBeenCalledWith("/api/v1/staff/categories", {
      body: { name: "Smart Watches", parent_id: "phones", slug: null, is_active: true, description: null, sort_order: 3 },
    });
    expect(await screen.findByText("Added 1: Smart Watches.")).toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("adds a pasted list in order, skipping names already there and reporting refused ones", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    const box = await screen.findByRole("textbox", { name: "Add subcategories" });
    await user.click(box);
    await user.paste("Chargers\ntablets\nCameras\nCables\n\nChargers");
    expect(api.POST.mock.calls.map(([, { body }]) => [body.name, body.sort_order])).toEqual([
      ["Chargers", 3],
      ["Cameras", 4],
      ["Cables", 5],
    ]);
    expect(await screen.findByText("Added 2: Chargers, Cables.")).toBeInTheDocument();
    expect(screen.getByText("Already there, so not added again: tablets, Chargers.")).toBeInTheDocument();
    expect(screen.getByText(/“Cameras” wasn’t added: its web address is already used/)).toBeInTheDocument();
    expect(box).toHaveValue("Cameras");
  });

  it("invites the first subcategories of a category without any", async () => {
    const user = userEvent.setup();
    nav.params = new URLSearchParams("category=appliances");
    api.GET.mockImplementation((path: string) => {
      if (path === "/api/v1/staff/categories") return ok({ items: CATEGORIES.filter((c) => c.parent_id !== "appliances") });
      if (path === "/api/v1/staff/brands") return ok({ items: BRANDS });
      return ok({ items: [] });
    });
    renderView(<CategoriesView />);
    await user.type(await screen.findByRole("textbox", { name: "Add the first subcategories of Home Appliances" }), "Fans{Enter}");
    expect(api.POST.mock.calls[0][1].body).toMatchObject({ name: "Fans", parent_id: "appliances", sort_order: 1 });
  });

  it("opens the full dialog with the typed name from More options", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    await user.type(await screen.findByRole("textbox", { name: "Add subcategories" }), "Gimbals");
    await user.click(screen.getByRole("button", { name: "More options" }));
    const dialog = screen.getByRole("dialog", { name: "Add subcategory" });
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("Gimbals");
    expect(within(dialog).getByRole("combobox", { name: "Parent category" })).toHaveValue("phones");
  });

  it("creates a main category with the subcategories listed in its dialog", async () => {
    const user = userEvent.setup();
    renderView(<CategoriesView />);
    await user.click(await screen.findByRole("button", { name: "Add main category" }));
    const dialog = screen.getByRole("dialog", { name: "Add main category" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Gaming");
    await user.type(within(dialog).getByRole("textbox", { name: "Subcategories (optional)" }), "Consoles{Enter}Controllers");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Gaming saved with 2 subcategories");
    expect(api.POST.mock.calls.map(([, { body }]) => [body.name, body.parent_id])).toEqual([
      ["Gaming", null],
      ["Consoles", "new1"],
      ["Controllers", "new1"],
    ]);
  });
});

describe("brands of a category", () => {
  beforeEach(() => {
    api.PATCH.mockImplementation(() => ok({}));
    api.POST.mockImplementation((_p: string, { body }: { body: { name: string } }) => ok({ id: "new", ...body }));
  });

  it("lists a category's brands, with whether its store menu lists them", async () => {
    nav.params = new URLSearchParams("category=phones&tab=brands");
    renderView(<CategoriesView />);
    const detail = await screen.findByRole("region", { name: "Phones & Tablets" });
    expect(within(detail).getByRole("tab", { name: /^Brands.*2$/ })).toHaveAttribute("aria-selected", "true");
    const rows = (await within(detail).findAllByRole("row")).slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").slice(0, 3).map((c) => c.textContent))).toEqual([
      ["APApple/apple", "4", "In the menu"],
      ["SASamsung/samsung", "7", "In the menu"],
    ]);
    // Both are in the Phones store menu, so neither can be taken out of Phones here.
    expect(within(rows[0]).getByRole("button", { name: "Remove Apple from Phones & Tablets" })).toBeDisabled();
    const samsung = within(rows[1]).getByRole("button", { name: "Remove Samsung from Phones & Tablets" });
    expect(samsung).toBeDisabled();
    expect(samsung).toHaveAttribute("title", "The Phones & Tablets store menu lists Samsung; take it off that menu first.");
  });

  it("adds an existing brand to the category", async () => {
    const user = userEvent.setup();
    nav.params = new URLSearchParams("category=phones&tab=brands");
    renderView(<CategoriesView />);
    const add = await screen.findByRole("combobox", { name: "Add an existing brand" });
    expect(within(add).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a brand to add to Phones & Tablets…", "LG"]);
    await user.selectOptions(add, "lg");
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/staff/brands/{brand_id}", { params: { path: { brand_id: "lg" } }, body: { category_ids: ["appliances", "phones"] } });
  });

  it("removes a brand that is not in the category's store menu, keeping its other categories", async () => {
    const user = userEvent.setup();
    nav.params = new URLSearchParams("category=appliances&tab=brands");
    renderView(<CategoriesView />);
    await user.click(await screen.findByRole("button", { name: "Remove Samsung from Home Appliances" }));
    expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/staff/brands/{brand_id}", { params: { path: { brand_id: "samsung" } }, body: { category_ids: ["phones"] } });
    // LG has only this category.
    expect(screen.getByRole("button", { name: "Remove LG from Home Appliances" })).toBeDisabled();
  });

  it("starts a new brand in the category, and a brand cannot be saved without one", async () => {
    const user = userEvent.setup();
    nav.params = new URLSearchParams("category=appliances&tab=brands");
    renderView(<CategoriesView />);
    await user.click(await screen.findByRole("button", { name: "New brand" }));
    const dialog = screen.getByRole("dialog", { name: "Add brand" });
    const appliances = within(dialog).getByRole("checkbox", { name: "Home Appliances" });
    expect(appliances).toBeChecked();
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Haier");
    await user.click(appliances);
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Choose at least one category.")).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();
    // Chosen out of order, sent in menu order.
    await user.click(within(dialog).getByRole("checkbox", { name: "Home Appliances" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Phones & Tablets" }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(api.POST).toHaveBeenCalledWith("/api/v1/staff/brands", { body: { name: "Haier", slug: null, is_active: true, category_ids: ["phones", "appliances"] } });
  });

  it("keeps a category ticked while its store menu lists the brand", async () => {
    const user = userEvent.setup();
    nav.pathname = "/admin/brands";
    renderView(<BrandsView />);
    await user.click(await screen.findByRole("button", { name: "Edit Samsung" }));
    const dialog = screen.getByRole("dialog", { name: "Edit brand" });
    expect(within(dialog).getByRole("checkbox", { name: /Phones & Tablets/ })).toBeDisabled();
    expect(within(dialog).getByRole("checkbox", { name: "Home Appliances" })).toBeEnabled();
  });

  it("asks for a category when editing a brand that has none", async () => {
    const user = userEvent.setup();
    nav.pathname = "/admin/brands";
    renderView(<BrandsView />);
    await user.click(await screen.findByRole("button", { name: "Edit Nokia" }));
    const dialog = screen.getByRole("dialog", { name: "Edit brand" });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Choose at least one category.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox", { name: "Phones & Tablets" }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/staff/brands/{brand_id}", { params: { path: { brand_id: "nokia" } }, body: { name: "Nokia", is_active: false, category_ids: ["phones"] } });
  });
});

describe("brands page", () => {
  it("lists every brand with its products and the store menus that list it", async () => {
    nav.pathname = "/admin/brands";
    renderView(<BrandsView />);
    expect(screen.getByRole("link", { name: /Brands/ })).toHaveAttribute("aria-current", "page");
    const rows = (await screen.findAllByRole("row")).slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["APApple/apple · No logo", "LGLG/lg · No logo", "NONokia/nokia · No logo", "SASamsung/samsung · No logo"]);
    // Apple is in Phones & Tablets, whose store menu also lists it.
    expect(within(rows[0]).getByRole("link", { name: /Phones & Tablets.*also in its store menu/ })).toHaveAttribute("href", "/admin/categories?category=phones&tab=brands");
    expect(within(rows[3]).getAllByRole("link").filter((a) => a.getAttribute("href")?.includes("tab=brands")).map((a) => a.textContent)).toEqual(["Phones & Tablets(also in its store menu)", "Home Appliances"]);
    expect(within(rows[2]).getByText("No category yet")).toBeInTheDocument();
    expect(screen.getByText("1 brand has no category yet. Edit them to choose where they belong.")).toBeInTheDocument();
  });

  it("filters by search and status", async () => {
    const user = userEvent.setup();
    nav.pathname = "/admin/brands";
    renderView(<BrandsView />);
    await screen.findAllByRole("row");
    await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "hidden");
    expect(screen.getAllByRole("row").slice(1)).toHaveLength(1);
    await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "all");
    await user.selectOptions(screen.getByRole("combobox", { name: "Category" }), "appliances");
    expect(screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["LGLG/lg · No logo", "SASamsung/samsung · No logo"]);
    await user.click(screen.getByRole("button", { name: "Show them" }));
    expect(screen.getAllByRole("row").slice(1)).toHaveLength(1);
    await user.selectOptions(screen.getByRole("combobox", { name: "Category" }), "");
    await user.type(screen.getByRole("searchbox", { name: "Search brands" }), "zzz");
    expect(screen.getByText("No brands match your search.")).toBeInTheDocument();
  });
});

describe("catalogue helpers", () => {
  it("reads subcategory names one per line, skipping blanks and repeats", () => {
    expect(newSubcategoryNames(" Fans \n\nheaters\nFANS\nKettles  ", ["Kettles"])).toEqual({ names: ["Fans", "heaters"], skipped: ["FANS", "Kettles"] });
  });

  it("filters and sorts brands", () => {
    expect(filterBrands(BRANDS, "", "all").map((b) => b.id)).toEqual(["apple", "lg", "nokia", "samsung"]);
    expect(filterBrands(BRANDS, "SAM", "all").map((b) => b.id)).toEqual(["samsung"]);
    expect(filterBrands(BRANDS, "", "hidden").map((b) => b.id)).toEqual(["nokia"]);
  });

  it("filters brands by category, or those without one", () => {
    expect(filterBrands(BRANDS, "", "all", "appliances").map((b) => b.id)).toEqual(["lg", "samsung"]);
    expect(filterBrands(BRANDS, "", "all", NO_CATEGORY).map((b) => b.id)).toEqual(["nokia"]);
    expect(brandsOfCategory(BRANDS, "phones").map((b) => b.id)).toEqual(["apple", "samsung"]);
  });

  it("puts a main category's brands first in the product editor", () => {
    const options = [
      { id: "apple", name: "Apple", hidden: false },
      { id: "lg", name: "LG", hidden: false },
      { id: "samsung", name: "Samsung", hidden: false },
    ];
    expect(groupBrandOptions(options, BRANDS, "appliances")).toEqual({ own: [options[1], options[2]], other: [options[0]] });
    expect(groupBrandOptions(options, BRANDS, "")).toEqual({ own: [], other: options });
  });

  it("finds the menus that list each brand", () => {
    const menus = menusByBrand(CATEGORIES);
    expect(menus.get("apple")?.map((c) => c.id)).toEqual(["phones"]);
    expect(menus.has("nokia")).toBe(false);
  });

  it("keeps Categories & Brands active in the sidebar on the brands tab", () => {
    expect(activeNav("/admin/brands")).toBe("categories");
    expect(activeNav("/admin/categories")).toBe("categories");
  });
});
