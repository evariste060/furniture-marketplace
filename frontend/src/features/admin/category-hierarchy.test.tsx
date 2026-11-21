import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import admin from "../../../messages/admin.json";
import en from "../../../messages/en.json";
import { ToastProvider } from "@/components/ui/toast";
import { addableBrands, moveItem, nextSortOrder, siblingOrder, subtreeCount, visibleRows } from "./categories";
import { brandOptions, isHidden, mainOptions, rootOf, splitCategory, subOptions } from "./category-options";
import { ProductEditorView } from "./product-editor";

/** Category hierarchy (2026-11-16): the product editor's Main category → Subcategory pickers and
 * the admin tree's search, filter, counts and reorder helpers. */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));
vi.mock("./access", () => ({ useStaffAccess: () => ({ can: () => true }) }));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const cat = (id: string, name: string, parent_id: string | null, sort_order: number, is_active = true, product_count = 0) => ({
  id,
  name,
  slug: id,
  parent_id,
  sort_order,
  is_active,
  product_count,
  description: null,
  image: null,
  spotlight_product_id: null,
  created_at: "2026-11-16T00:00:00Z",
  updated_at: "2026-11-16T00:00:00Z",
});

const CATEGORIES = [
  cat("phones", "Phones & Tablets", null, 1, true, 1),
  cat("laptops", "Laptops & Computers", null, 2),
  cat("retired", "Retired", null, 3, false),
  cat("smartphones", "Smartphones", "phones", 1, true, 12),
  cat("tablets", "Tablets", "phones", 2, true, 3),
  cat("feature", "Feature Phones", "phones", 3, false),
  cat("gaming", "Gaming Laptops", "laptops", 2),
  cat("notebooks", "Laptops", "laptops", 1),
  cat("old", "Old stock", "retired", 1),
];
const BRANDS = [
  { id: "samsung", name: "Samsung", slug: "samsung", is_active: true, logo: null, product_count: 0, created_at: "", updated_at: "" },
  { id: "nokia", name: "Nokia", slug: "nokia", is_active: false, logo: null, product_count: 0, created_at: "", updated_at: "" },
  { id: "apple", name: "Apple", slug: "apple", is_active: true, logo: null, product_count: 0, created_at: "", updated_at: "" },
];
const ok = (data: unknown, status = 200) => Promise.resolve({ data, error: undefined, response: { ok: true, status } });

function respond(product?: Record<string, unknown>) {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/staff/categories") return ok({ items: CATEGORIES });
    if (path === "/api/v1/staff/brands") return ok({ items: BRANDS });
    if (path === "/api/v1/staff/products/{product_id}") return ok(product);
    return ok({ items: [], total: 0, page: 1, size: 20 });
  });
}

function renderEditor(productId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ ...en, admin }} timeZone="Africa/Kigali">
        <ToastProvider closeLabel="Close">{(<ProductEditorView productId={productId} />) as ReactNode}</ToastProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const options = (select: HTMLElement) => within(select).getAllByRole("option").map((o) => o.textContent);

afterEach(() => vi.clearAllMocks());

describe("category options", () => {
  it("finds a category's main category and whether it is hidden", () => {
    expect(rootOf(CATEGORIES, "tablets")?.id).toBe("phones");
    expect(rootOf(CATEGORIES, "phones")?.id).toBe("phones");
    expect(isHidden(CATEGORIES, "old")).toBe(true); // under a hidden main category
    expect(isHidden(CATEGORIES, "feature")).toBe(true);
    expect(isHidden(CATEGORIES, "tablets")).toBe(false);
  });

  it("offers visible categories in order, plus the product's current hidden one", () => {
    expect(mainOptions(CATEGORIES, "").map((o) => o.id)).toEqual(["phones", "laptops"]);
    expect(subOptions(CATEGORIES, "laptops", "").map((o) => o.id)).toEqual(["notebooks", "gaming"]);
    expect(subOptions(CATEGORIES, "phones", "").map((o) => o.id)).toEqual(["smartphones", "tablets"]);
    expect(subOptions(CATEGORIES, "phones", "feature")).toContainEqual({ id: "feature", name: "Feature Phones", hidden: true });
    expect(mainOptions(CATEGORIES, "old")).toContainEqual({ id: "retired", name: "Retired", hidden: true });
    expect(subOptions(CATEGORIES, "", "")).toEqual([]);
  });

  it("splits a stored category into the two pickers", () => {
    expect(splitCategory(CATEGORIES, "tablets")).toEqual({ mainId: "phones", subId: "tablets" });
    expect(splitCategory(CATEGORIES, "phones")).toEqual({ mainId: "phones", subId: "" });
    expect(splitCategory(CATEGORIES, "")).toEqual({ mainId: "", subId: "" });
    expect(splitCategory(CATEGORIES, "unknown")).toEqual({ mainId: "", subId: "" });
  });

  it("offers active brands by name, plus the current hidden one", () => {
    expect(brandOptions(BRANDS, "").map((b) => b.id)).toEqual(["apple", "samsung"]);
    expect(brandOptions(BRANDS, "nokia").map((b) => b.id)).toEqual(["apple", "nokia", "samsung"]);
  });
});

describe("category tree helpers", () => {
  it("counts the products of a main category and its subcategories", () => {
    expect(subtreeCount(CATEGORIES, "phones")).toBe(16);
    expect(subtreeCount(CATEGORIES, "tablets")).toBe(3);
  });

  it("keeps the matches of a search and status filter with their main categories", () => {
    expect([...visibleRows(CATEGORIES, "tab", "all")].sort()).toEqual(["phones", "tablets"]);
    expect([...visibleRows(CATEGORIES, "", "hidden")].sort()).toEqual(["feature", "phones", "retired"]);
    expect(visibleRows(CATEGORIES, "", "all").size).toBe(CATEGORIES.length);
    expect(visibleRows(CATEGORIES, "zzz", "all").size).toBe(0);
  });

  it("moves a category among its siblings and puts new ones last", () => {
    expect(siblingOrder(CATEGORIES, "tablets", -1)).toEqual(["tablets", "smartphones", "feature"]);
    expect(siblingOrder(CATEGORIES, "smartphones", -1)).toBeNull();
    expect(siblingOrder(CATEGORIES, "retired", 1)).toBeNull();
    expect(nextSortOrder(CATEGORIES, "phones")).toBe(4);
    expect(nextSortOrder(CATEGORIES, "gaming")).toBe(1);
    expect(nextSortOrder(CATEGORIES, "laptops", "gaming")).toBe(2);
  });
});

describe("product editor: main category, then subcategory", () => {
  it("shows only the chosen main category's subcategories and resets them on change", async () => {
    respond();
    renderEditor();
    const main = await screen.findByLabelText("Main category");
    await waitFor(() => expect(main).toBeEnabled());
    const sub = screen.getByLabelText("Subcategory");
    expect(options(main)).toEqual(["Choose a main category…", "Phones & Tablets", "Laptops & Computers"]);
    expect(sub).toBeDisabled();

    await userEvent.selectOptions(main, "phones");
    expect(options(sub)).toEqual(["None (directly in the main category)", "Smartphones", "Tablets"]);
    await userEvent.selectOptions(sub, "tablets");
    expect(sub).toHaveValue("tablets");

    await userEvent.selectOptions(main, "laptops");
    expect(sub).toHaveValue("");
    expect(options(sub)).toEqual(["None (directly in the main category)", "Laptops", "Gaming Laptops"]);
    expect(options(screen.getByLabelText("Brand"))).toEqual(["No brand", "Apple", "Samsung"]);
  });

  it("saves the subcategory, or the main category when none is picked", async () => {
    respond();
    api.POST.mockImplementation(() => ok({ id: "new-product" }, 201));
    renderEditor();
    const main = await screen.findByLabelText("Main category");
    await waitFor(() => expect(main).toBeEnabled());
    await userEvent.type(screen.getByLabelText("Product name"), "Galaxy S24");
    await userEvent.selectOptions(main, "phones");
    await userEvent.selectOptions(screen.getByLabelText("Subcategory"), "smartphones");
    await userEvent.click(screen.getByRole("button", { name: "Create product" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    expect(api.POST.mock.calls[0][1].body.category_id).toBe("smartphones");

    await userEvent.selectOptions(screen.getByLabelText("Subcategory"), "");
    await userEvent.click(screen.getByRole("button", { name: "Create product" }));
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
    expect(api.POST.mock.calls[1][1].body.category_id).toBe("phones");
  });

  it("asks for a main category before saving", async () => {
    respond();
    renderEditor();
    await waitFor(() => expect(screen.getByLabelText("Main category")).toBeEnabled());
    await userEvent.type(screen.getByLabelText("Product name"), "Galaxy S24");
    await userEvent.click(screen.getByRole("button", { name: "Create product" }));
    expect(await screen.findByText("Choose a main category.")).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("loads a product's main category and subcategory, keeping hidden ones it already has", async () => {
    respond({
      id: "p1",
      name: "Nokia 105",
      slug: "nokia-105",
      description: null,
      brand_id: "nokia",
      category_id: "feature",
      model: null,
      warranty_text: null,
      status: "draft",
      is_featured: false,
      specifications: {},
      variants: [],
      images: [],
      photo_file_names: [],
      updated_at: "2026-11-16T00:00:00Z",
    });
    renderEditor("p1");
    const main = await screen.findByLabelText("Main category");
    await waitFor(() => expect(main).toHaveValue("phones"));
    const sub = screen.getByLabelText("Subcategory");
    expect(sub).toHaveValue("feature");
    expect(options(sub)).toContain("Feature Phones (hidden)");
    expect(screen.getByLabelText("Brand")).toHaveValue("nokia");
    expect(options(screen.getByLabelText("Brand"))).toContain("Nokia (hidden)");
  });
});

describe("menu brands picker helpers (2026-11-16)", () => {
  it("moves a brand one place and stops at either end", () => {
    expect(moveItem(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    expect(moveItem(["a", "b", "c"], 1, 1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b", "c"], 0, -1)).toEqual(["a", "b", "c"]);
    expect(moveItem(["a", "b", "c"], 2, 1)).toEqual(["a", "b", "c"]);
  });

  it("offers active brands that are not listed yet, by name", () => {
    const brands = [
      { id: "s", name: "Samsung", is_active: true },
      { id: "a", name: "Apple", is_active: true },
      { id: "n", name: "Nokia", is_active: false },
      { id: "h", name: "HP", is_active: true },
    ];
    expect(addableBrands(brands, ["h"]).map((b) => b.name)).toEqual(["Apple", "Samsung"]);
  });
});
