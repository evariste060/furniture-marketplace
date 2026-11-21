import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { SHOWCASE_INTERVAL_MS, SpotlightShowcase, type ShowcaseProduct } from "./spotlight-showcase";

/** The large product on the left of each home page category spotlight. */

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
// The cart buttons need the cart's providers; here they only show what they would add.
vi.mock("./product-actions", () => ({
  BuyNowButton: ({ target }: { target: { productName: string } }) => <button type="button">{`Buy Now: ${target.productName}`}</button>,
  AddToCartButton: ({ target }: { target: { productName: string } }) => <button type="button">{`Add to Cart: ${target.productName}`}</button>,
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));

const image = (n: number) => ({ url: `https://img.test/${n}.jpg`, width: 800, height: 800, alt: `Photo ${n}`, position: n });

const PHONE: ShowcaseProduct = {
  name: "iPhone 15",
  slug: "apple-iphone-15",
  images: [image(1), image(2), image(3)],
  price: 1_200_000,
  compareAtPrice: 1_350_000,
  discount: 11,
  detail: "128GB · Black",
  rating: { average: 4.5, count: 4 },
  cart: { productName: "iPhone 15", variantId: "v1", variantName: "128GB · Black", variantCount: 2, inStock: true },
};

function renderShowcase(product: ShowcaseProduct = PHONE) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SpotlightShowcase product={product} />
    </NextIntlClientProvider>,
  );
}

/** The index of the photo shown (the one at full opacity). */
function shownPhoto(container: HTMLElement): number {
  const photos = [...container.querySelectorAll("img")].map((img) => img.closest("span"));
  return photos.findIndex((span) => span?.className.includes("opacity-100"));
}

function setReducedMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query.includes("reduce"),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

describe("SpotlightShowcase", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setReducedMotion(false);
  });
  afterEach(() => vi.useRealTimers());

  it("shows the name, variant, rating, sale price and the buy buttons", () => {
    renderShowcase();
    expect(screen.getByRole("link", { name: "iPhone 15" })).toHaveAttribute("href", "/product/apple-iphone-15");
    expect(screen.getByText("128GB · Black")).toBeInTheDocument();
    expect(screen.getByText("Rated 4.5 out of 5 from 4 reviews")).toBeInTheDocument();
    expect(screen.getByText("RWF 1,200,000", { exact: false })).toHaveClass("text-err");
    expect(screen.getByText("RWF 1,350,000", { exact: false })).toHaveClass("line-through");
    expect(screen.getByRole("button", { name: "Buy Now: iPhone 15" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to Cart: iPhone 15" })).toBeInTheDocument();
  });

  it("shows the photos one after the other and lets the dots pick one", () => {
    const { container } = renderShowcase();
    expect(shownPhoto(container)).toBe(0);
    act(() => void vi.advanceTimersByTime(SHOWCASE_INTERVAL_MS));
    expect(shownPhoto(container)).toBe(1);
    act(() => void vi.advanceTimersByTime(SHOWCASE_INTERVAL_MS * 2));
    expect(shownPhoto(container)).toBe(0); // back to the first after the last
    fireEvent.click(screen.getByRole("button", { name: "Show photo 3 of 3" }));
    expect(shownPhoto(container)).toBe(2);
    expect(screen.getByRole("button", { name: "Show photo 3 of 3" })).toHaveAttribute("aria-current", "true");
  });

  it("pauses while the pointer is on it", () => {
    const { container } = renderShowcase();
    fireEvent.pointerEnter(container.firstElementChild!);
    act(() => void vi.advanceTimersByTime(SHOWCASE_INTERVAL_MS * 2));
    expect(shownPhoto(container)).toBe(0);
    fireEvent.pointerLeave(container.firstElementChild!);
    act(() => void vi.advanceTimersByTime(SHOWCASE_INTERVAL_MS));
    expect(shownPhoto(container)).toBe(1);
  });

  it("does not rotate with reduced motion", () => {
    setReducedMotion(true);
    const { container } = renderShowcase();
    act(() => void vi.advanceTimersByTime(SHOWCASE_INTERVAL_MS * 3));
    expect(shownPhoto(container)).toBe(0);
  });

  it("has no dots for a single photo and no sale price without a discount", () => {
    renderShowcase({ ...PHONE, images: [image(1)], discount: null, compareAtPrice: null, rating: { average: null, count: 0 }, detail: null });
    expect(screen.queryByRole("button", { name: /Show photo/ })).not.toBeInTheDocument();
    expect(screen.getByText("RWF 1,200,000")).toHaveClass("text-pri-h");
    expect(screen.queryByText(/Rated/)).not.toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument(); // no stray review count
  });
});
