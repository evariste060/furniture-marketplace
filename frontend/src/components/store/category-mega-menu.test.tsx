import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../../../messages/en.json";
import type { MenuCategory } from "@/lib/catalogue";
import { categoryHref, MegaMenuPanel, type MenuService } from "./category-mega-menu";

/** The three-step "All Categories" menu (2026-11-16): main category → its brands → that brand's
 * products in the category, every link opening the search page filtered to the choice. */

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
    brands: [
      { name: "Apple", slug: "apple", count: 2 },
      { name: "Samsung", slug: "samsung", count: 4 },
      { name: "Google", slug: "google", count: 0 },
    ],
    subcategories: [],
    products: { items: [product("a55", "Galaxy A55")], total: 14 },
  },
  { id: "cameras", name: "Cameras & Photography", slug: "cameras-photography", brands: [], subcategories: [], products: { items: [], total: 0 } },
  {
    id: "appliances",
    name: "Home Appliances",
    slug: "home-appliances",
    brands: [],
    subcategories: [
      { id: "fridges", name: "Refrigerators", slug: "refrigerators" },
      { id: "fans", name: "Fans", slug: "fans" },
    ],
    products: { items: [product("fryer", "Air Fryer")], total: 6 },
  },
];

function renderMenu(close = vi.fn(), services: MenuService[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={en}>
        <MegaMenuPanel categories={CATEGORIES} services={services} close={close} />
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
  it("shows the main category's brands and best sellers, linking to filtered search", () => {
    renderMenu();
    expect(screen.getByRole("link", { name: "Phones & Tablets" })).toHaveAttribute("href", "/category/phones");
    const brands = screen.getByRole("navigation", { name: "Brands in Phones & Tablets" });
    expect(within(brands).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["All Phones & Tablets", "/category/phones"],
      ["Apple2", "/category/phones?brand=apple"],
      ["Samsung4", "/category/phones?brand=samsung"],
      ["Google", "/category/phones?brand=google"],
    ]);
    expect(screen.getByRole("link", { name: /Galaxy A55/ })).toHaveAttribute("href", "/product/a55");
    expect(screen.getByRole("link", { name: "View all (14)" })).toHaveAttribute("href", "/category/phones");
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("loads a hovered brand's products in the category once and keeps them", async () => {
    api.GET.mockResolvedValue({
      data: { items: [{ id: "ip15", name: "iPhone 15", slug: "ip15", images: [], variants: [{ price: 1_450_000, is_active: true, stock_status: "in_stock" }] }], total: 2, page: 1, size: 9 },
      response: { status: 200 },
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderMenu();
    const apple = screen.getByRole("link", { name: /^Apple/ });
    fireEvent.pointerEnter(apple, { pointerType: "mouse" });
    await act(() => vi.advanceTimersByTimeAsync(200));
    expect(await screen.findByRole("link", { name: /iPhone 15/ })).toHaveAttribute("href", "/product/ip15");
    expect(screen.getByText("Apple · Phones & Tablets")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all (2)" })).toHaveAttribute("href", "/category/phones?brand=apple");
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/catalog/products",
      expect.objectContaining({ params: { query: expect.objectContaining({ category: "phones", brand: ["apple"] }) } }),
    );

    fireEvent.focus(screen.getByRole("link", { name: "All Phones & Tablets" }));
    expect(screen.getByRole("link", { name: /Galaxy A55/ })).toBeInTheDocument();
    fireEvent.focus(apple);
    expect(await screen.findByRole("link", { name: /iPhone 15/ })).toBeInTheDocument();
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("shows a chosen brand without products in the category without loading anything", () => {
    renderMenu();
    fireEvent.focus(screen.getByRole("link", { name: "Google" }));
    expect(screen.getByText("No Google products in Phones & Tablets yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View category" })).toHaveAttribute("href", "/category/phones?brand=google");
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("shows a category without brands with no brand column", () => {
    renderMenu();
    fireEvent.focus(screen.getByRole("link", { name: "Cameras & Photography" }));
    expect(screen.queryByRole("navigation", { name: /Brands in/ })).toBeNull();
    expect(screen.getByText(en.store.megaMenu.empty)).toBeInTheDocument();
  });

  it("lists the subcategories of a category without brands, and loads a hovered one's products", async () => {
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
    const samsung = screen.getByRole("link", { name: /^Samsung/ });
    api.GET.mockReturnValue(new Promise(() => {}));
    fireEvent.pointerDown(samsung, { pointerType: "touch" });
    expect(fireEvent.click(samsung)).toBe(false); // default prevented: previewed, not opened
    expect(close).not.toHaveBeenCalled();
    fireEvent.pointerDown(samsung, { pointerType: "touch" });
    fireEvent.click(samsung);
    expect(close).toHaveBeenCalled();
  });

  it("reports a brand whose products fail to load", async () => {
    api.GET.mockResolvedValue({ data: undefined, error: { code: "server_error" }, response: { status: 500 } });
    renderMenu();
    fireEvent.focus(screen.getByRole("link", { name: /^Samsung/ }));
    // The menu retries once before giving up.
    await waitFor(() => expect(screen.getByText(en.store.megaMenu.productsError)).toBeInTheDocument(), { timeout: 5000 });
  });

  it("builds the search links", () => {
    expect(categoryHref("tvs-audio")).toBe("/category/tvs-audio");
    expect(categoryHref("phones", "apple")).toBe("/category/phones?brand=apple");
  });

  it("lists Services last, with the services as its subcategories and what each includes", () => {
    const close = renderMenu(vi.fn(), [
      { slug: "cctv-security", name: "CCTV & Security", short_description: "Cameras for homes.", icon: "cctv", items: ["Camera installation", "Remote viewing"] },
      { slug: "electronics-repair", name: "Repair", short_description: "Phones and laptops fixed.", icon: "wrench", items: [] },
    ]);
    const main = screen.getByRole("link", { name: "Services" });
    expect(main).toHaveAttribute("href", "/services");
    fireEvent.focus(main);
    const list = screen.getByRole("navigation", { name: "Services" });
    expect(within(list).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(["/services", "/services/cctv-security", "/services/electronics-repair"]);
    expect(screen.getByText("Phones and laptops fixed.")).toBeInTheDocument();
    fireEvent.focus(within(list).getByRole("link", { name: "CCTV & Security" }));
    expect(screen.getByText("Remote viewing")).toBeInTheDocument();
    const request = screen.getByRole("link", { name: "Request this service" });
    expect(request).toHaveAttribute("href", "/services/cctv-security/request");
    fireEvent.click(request);
    expect(close).toHaveBeenCalled();
  });

  it("has no Services entry without services", () => {
    renderMenu();
    expect(screen.queryByRole("link", { name: "Services" })).toBeNull();
  });
});
