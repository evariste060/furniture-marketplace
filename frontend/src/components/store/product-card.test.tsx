import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import type { CatalogProduct } from "@/lib/catalogue";
import { ProductCard } from "./product-card";

/** The product card's stock badge, shown on the home page's Featured, Bestselling and New
 * Arrivals rows (owner, 2026-11-17). */

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("./product-actions", () => ({
  AddToCartButton: () => <button type="button">Add to Cart</button>,
  WishlistButton: () => null,
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));

function product(variants: { in_stock: boolean; stock_status: string; compare_at_price?: number | null }[]): CatalogProduct {
  return {
    id: "p1",
    name: "Tecno Spark 20",
    slug: "tecno-spark-20",
    images: [],
    rating: { average: null, count: 0 },
    variants: variants.map((v, i) => ({ id: `v${i}`, name: null, price: 295000, compare_at_price: null, images: [], ...v })),
  } as unknown as CatalogProduct;
}

function renderCard(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

describe("ProductCard stock badge", () => {
  it.each([
    [[{ in_stock: true, stock_status: "in_stock" }], "In Stock"],
    [[{ in_stock: true, stock_status: "low_stock" }], "Low Stock"],
    [[{ in_stock: false, stock_status: "out_of_stock" }], "Out of Stock"],
  ])("shows the stock level when asked (%#)", (variants, label) => {
    renderCard(<ProductCard product={product(variants)} showStock />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("puts it after the New badge, and is left out by default", () => {
    const { unmount } = renderCard(<ProductCard product={product([{ in_stock: true, stock_status: "in_stock" }])} showStock isNew />);
    const badges = screen.getAllByText(/^(New|In Stock)$/).map((b) => b.textContent);
    expect(badges).toEqual(["New", "In Stock"]);
    unmount();
    renderCard(<ProductCard product={product([{ in_stock: true, stock_status: "in_stock" }])} />);
    expect(screen.queryByText("In Stock")).toBeNull();
  });
});
