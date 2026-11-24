import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { HoverProductCard, type HoverProduct } from "./hover-product-card";

/** The hover card shared by the home hero (sm) and the category spotlights (md). */

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
// The cart button needs the cart's providers; here it only shows which variant it would add.
vi.mock("./product-actions", () => ({
  AddToCartButton: ({ target }: { target: { productName: string; variantId: string | null } }) => (
    <button type="button" data-variant={target.variantId ?? ""}>{`Add to Cart: ${target.productName}`}</button>
  ),
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));

const PHONE: HoverProduct = {
  id: "p1",
  name: "Tecno Spark 20",
  slug: "tecno-spark-20",
  image: null,
  price: 265500,
  cart: { productName: "Tecno Spark 20", variantId: "v1", variantName: "128GB · Black", variantCount: 2, inStock: true },
  detail: "128GB · Black",
  rating: { average: 4.5, count: 2 },
  discount: 10,
};

function renderCard(product: HoverProduct, size?: "sm" | "md") {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <HoverProductCard product={product} size={size} />
    </NextIntlClientProvider>,
  );
}

describe("HoverProductCard", () => {
  it("links to the product page and adds the shown variant to the cart", () => {
    renderCard(PHONE, "md");
    expect(screen.getByRole("link", { name: /^Tecno Spark 20/ })).toHaveAttribute("href", "/product/tecno-spark-20");
    expect(screen.getByRole("button", { name: "Add to Cart: Tecno Spark 20" })).toHaveAttribute("data-variant", "v1");
  });

  it("shows the variant, rating and discount on the spotlight card", () => {
    renderCard(PHONE, "md");
    expect(screen.getByText("128GB · Black")).toBeInTheDocument();
    expect(screen.getByText("Rated 4.5 out of 5 from 2 reviews")).toBeInTheDocument();
    expect(screen.getByText("RWF 265,500", { exact: false })).toHaveClass("text-err-fg");
    expect(screen.getAllByText("−10%", { exact: false }).length).toBeGreaterThan(0);
  });

  it("offers View Details beside the cart icon on the spotlight card", () => {
    renderCard(PHONE, "md");
    expect(screen.getByRole("link", { name: "View Details: Tecno Spark 20" })).toHaveAttribute("href", "/product/tecno-spark-20");
    expect(screen.getByRole("button", { name: "Add to Cart: Tecno Spark 20" })).toBeInTheDocument();
  });

  it("keeps the hero's small card to photo, name, price and button", () => {
    renderCard(PHONE);
    expect(screen.queryByRole("link", { name: /View Details/ })).not.toBeInTheDocument();
    expect(screen.queryByText("128GB · Black")).not.toBeInTheDocument();
    expect(screen.queryByText(/Rated/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to Cart: Tecno Spark 20" })).toBeInTheDocument();
  });

  it("leaves the rating out when the product has no reviews", () => {
    renderCard({ ...PHONE, rating: { average: null, count: 0 }, discount: null }, "md");
    expect(screen.queryByText(/Rated/)).not.toBeInTheDocument();
    expect(screen.getByText("RWF 265,500")).toHaveClass("text-tx");
  });
});
