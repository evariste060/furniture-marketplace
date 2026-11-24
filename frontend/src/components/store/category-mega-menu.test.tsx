import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../../../messages/en.json";
import type { MenuCategory } from "@/lib/catalogue";
import { categoryHref, MegaMenuPanel } from "./category-mega-menu";

/** The three-step "All Categories" menu (2026-11-16): main category → its subcategories → that
 * subcategory's products. Brands are not offered on the storefront (SC-09). */

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/",
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/ui/product-image", () => ({ ProductImage: () => <span /> }));

const product = (id: string, name: string, price = 100_000) => ({ id, name, slug: id, image: null, price });
const CATEGORIES: MenuCategory[] = [
  {
    id: "phones",
    name: "Phones & Tablets",
    slug: "phones",
    subcategories: [
      { id: "smartphones", name: "Smartphones", slug: "smartphones" },
      { id: "tablets", name: "Tablets", slug: "tablets" },
    ],
    products: { items: [product("a55", "Galaxy A55")], total: 14 },
  },
  { id: "cameras", name: "Cameras & Photography", slug: "cameras-photography", subcategories: [], products: { items: [], total: 0 } },
  {
    id: "appliances",
    name: "Home Appliances",
    slug: "home-appliances",
    subcategories: [
      { id: "fridges", name: "Refrigerators", slug: "refrigerators" },
      { id: "fans", name: "Fans", slug: "fans" },
    ],
    products: { items: [product("fryer", "Air Fryer")], total: 6 },
  },
];

function renderMenu(close = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={en}>
        <MegaMenuPanel categories={CATEGORIES} close={close} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return close;
}

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("category mega menu", () => {
  it("shows the main category's subcategories and best sellers, and no brands", () => {
    renderMenu();
    expect(screen.getByRole("link", { name: "Phones & Tablets" })).toHaveAttribute("href", "/category/phones");
    const subs = screen.getByRole("navigation", { name: "Subcategories of Phones & Tablets" });
    expect(within(subs).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["All Phones & Tablets", "/category/phones"],
      ["Smartphones", "/category/smartphones"],
      ["Tablets", "/category/tablets"],
    ]);
    expect(screen.queryByRole("navigation", { name: /Brands in/ })).toBeNull();
    expect(document.querySelector('a[href*="brand="]')).toBeNull();
    expect(screen.getByRole("link", { name: /Galaxy A55/ })).toHaveAttribute("href", "/product/a55");
    expect(screen.getByRole("link", { name: "View all (14)" })).toHaveAttribute("href", "/category/phones");
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("shows a category without subcategories with no middle column", () => {
    renderMenu();
    fireEvent.focus(screen.getByRole("link", { name: "Cameras & Photography" }));
    expect(screen.queryByRole("navigation", { name: /Subcategories of/ })).toBeNull();
    expect(screen.getByText(en.store.megaMenu.empty)).toBeInTheDocument();
  });

  it("loads a hovered subcategory's products once", async () => {
    api.GET.mockResolvedValue({
      data: { items: [{ id: "lg420", name: "LG 420 L Refrigerator", slug: "lg420", images: [], variants: [{ price: 900_000, is_active: true, stock_status: "in_stock" }] }], total: 2, page: 1, size: 9 },
      response: { status: 200 },
    });
    renderMenu();
    fireEvent.focus(screen.getByRole("link", { name: "Home Appliances" }));
    const subs = screen.getByRole("navigation", { name: "Subcategories of Home Appliances" });
    expect(within(subs).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["All Home Appliances", "/category/home-appliances"],
      ["Refrigerators", "/category/refrigerators"],
      ["Fans", "/category/fans"],
    ]);
    expect(screen.getByRole("link", { name: /Air Fryer/ })).toBeInTheDocument();
    fireEvent.focus(within(subs).getByRole("link", { name: "Refrigerators" }));
    expect(await screen.findByRole("link", { name: /LG 420 L Refrigerator/ })).toHaveAttribute("href", "/product/lg420");
    expect(screen.getByRole("link", { name: "View all (2)" })).toHaveAttribute("href", "/category/refrigerators");
    const [, { params }] = api.GET.mock.calls[0];
    expect(params.query.category).toBe("refrigerators");
    expect(params.query.brand).toBeUndefined();
  });

  it("previews on the first tap and opens on the second", () => {
    const close = renderMenu();
    const samsung = screen.getByRole("link", { name: "Tablets" });
    api.GET.mockReturnValue(new Promise(() => {}));
    fireEvent.pointerDown(samsung, { pointerType: "touch" });
    expect(fireEvent.click(samsung)).toBe(false); // default prevented: previewed, not opened
    expect(close).not.toHaveBeenCalled();
    fireEvent.pointerDown(samsung, { pointerType: "touch" });
    fireEvent.click(samsung);
    expect(close).toHaveBeenCalled();
  });

  it("reports a subcategory whose products fail to load", async () => {
    api.GET.mockResolvedValue({ data: undefined, error: { code: "server_error" }, response: { status: 500 } });
    renderMenu();
    fireEvent.focus(screen.getByRole("link", { name: "Tablets" }));
    // The menu retries once before giving up.
    await waitFor(() => expect(screen.getByText(en.store.megaMenu.productsError)).toBeInTheDocument(), { timeout: 5000 });
  });

  it("builds the category links", () => {
    expect(categoryHref("tvs-audio")).toBe("/category/tvs-audio");
  });
});
