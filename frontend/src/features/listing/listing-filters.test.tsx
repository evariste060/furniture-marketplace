import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { parseListingState, type CatalogFacets } from "@/lib/catalogue";
import { FilterPanel, FilterSheet, type SubcategoryFilter } from "./listing-filters";

/** The category page's Subcategory filter group (owner, 2026-11-17): the main category's
 * subcategories, each opening its page with the other filters kept. */

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/api/client", () => ({ browserApi: { GET: vi.fn() } }));

// jsdom has no modal dialogs.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.open = false;
};

const FACETS: CatalogFacets = {
  total: 3,
  brands: [{ slug: "hp", name: "HP", count: 3 }],
  categories: [],
  price_bands: [],
  availability: { in_stock: 3, out_of_stock: 0 },
  ratings: [],
} as unknown as CatalogFacets;

const SUBS = (current: string): SubcategoryFilter => ({
  main: { name: "Laptops", slug: "laptops" },
  items: [
    { name: "Gaming Laptops", slug: "gaming-laptops" },
    { name: "Monitors", slug: "monitors" },
  ],
  current,
});

function renderPanel(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <NextIntlClientProvider locale="en" messages={messages}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("Subcategory filter", () => {
  it("lists the main category and its subcategories, keeping the other filters", () => {
    const state = parseListingState({ brand: "hp", sort: "price_asc", page: "3" });
    renderPanel(<FilterPanel state={state} facets={FACETS} basePath="/category/laptops" base={{ category: "laptops" }} subcategories={SUBS("laptops")} />);
    const group = screen.getByRole("navigation", { name: "Subcategory" });
    const links = within(group).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["All Laptops", "/category/laptops?brand=hp&sort=price_asc"],
      ["Gaming Laptops", "/category/gaming-laptops?brand=hp&sort=price_asc"],
      ["Monitors", "/category/monitors?brand=hp&sort=price_asc"],
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
  });

  it("marks the subcategory being browsed", () => {
    renderPanel(<FilterPanel state={parseListingState({})} facets={FACETS} basePath="/category/monitors" base={{ category: "monitors" }} subcategories={SUBS("monitors")} />);
    const group = screen.getByRole("navigation", { name: "Subcategory" });
    expect(within(group).getByRole("link", { name: "Monitors" })).toHaveAttribute("aria-current", "page");
    expect(within(group).getByRole("link", { name: "All Laptops" })).not.toHaveAttribute("aria-current");
  });

  it("is left out where there are no subcategories", () => {
    renderPanel(<FilterPanel state={parseListingState({})} facets={FACETS} basePath="/deals" base={{ on_sale: true }} />);
    expect(screen.queryByRole("navigation", { name: "Subcategory" })).toBeNull();
  });

  it("is in the phone filter sheet too", async () => {
    const user = userEvent.setup();
    renderPanel(<FilterSheet state={parseListingState({})} facets={FACETS} basePath="/category/laptops" base={{ category: "laptops" }} subcategories={SUBS("laptops")} />);
    await user.click(screen.getByRole("button", { name: "Filters" }));
    const group = screen.getByRole("group", { name: "Subcategory" });
    expect(within(group).getByRole("link", { name: "Gaming Laptops" })).toHaveAttribute("href", "/category/gaming-laptops");
  });
});
