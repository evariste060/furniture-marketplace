import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { HeroShowcase, TURN_MS, type ShowcaseCategory, type ShowcaseServices } from "./hero-showcase";

/** The home hero's product showcase: the spotlight, its category's related products, and the
 * change from one category to the next. */

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

const product = (id: string, name: string, price: number | null = 100000) => ({ id, name, slug: id, image: null, price });
const related = (id: string, name: string) => ({
  ...product(id, name),
  cart: { productName: name, variantId: `${id}-v1`, variantName: null, variantCount: 1, inStock: true },
});

const CATEGORIES: ShowcaseCategory[] = [
  {
    id: "c1",
    name: "Phones",
    slug: "phones",
    total: 12,
    featured: product("tecno-spark-20", "Tecno Spark 20", 295000),
    related: [related("iphone-15", "iPhone 15"), related("galaxy-s24", "Galaxy S24")],
  },
  { id: "c2", name: "Laptops", slug: "laptops", total: 8, featured: product("macbook-air", "MacBook Air"), related: [related("hp-15", "HP 15")] },
  { id: "c3", name: "TVs & Audio", slug: "tvs-audio", total: 1, featured: product("lg-55", "LG 55\" TV", null), related: [] },
];

function renderShowcase(categories = CATEGORIES, services: ShowcaseServices | null = null) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <HeroShowcase categories={categories} services={services} title="Furniture for Every Room, From Stores You Trust" />
    </NextIntlClientProvider>,
  );
}

/** Every category's time in the spotlight, with the copy's exit: three seconds (owner, 2026-11-18). */
const phones = TURN_MS;
const laptops = TURN_MS;
const tvs = TURN_MS;

const hero = () => screen.getByRole("region", { name: "Products and services showcase" });
/** The orbit's places: each product's angle on the circle (180° is the spotlight on the left). */
function angles() {
  return [...hero().querySelectorAll<HTMLElement>("[data-orbit-item]")].map((el) => Number(el.style.transform.match(/^rotate\((-?[\d.]+)deg\)/)![1]));
}

beforeEach(() => {
  vi.useFakeTimers();
  window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
});
afterEach(() => vi.useRealTimers());

describe("HeroShowcase", () => {
  it("shows the first category's best seller in the spotlight with its price, Shop Now and related products", () => {
    renderShowcase();
    const region = hero();
    expect(within(region).getByRole("heading", { level: 1 })).toHaveTextContent("Furniture for Every Room");
    expect(within(region).getByText("Tecno Spark 20")).toBeInTheDocument();
    expect(within(region).getByText(/RWF\s*295,000/)).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: "Shop Now" })).toHaveAttribute("href", "/product/tecno-spark-20");
    expect(within(region).getByText("More in Phones")).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: "View all (12)" })).toHaveAttribute("href", "/category/phones");
    expect(within(region).getByRole("link", { name: /iPhone 15/ })).toHaveAttribute("href", "/product/iphone-15");
    expect(within(region).getByRole("link", { name: /Galaxy S24/ })).toBeInTheDocument();
    // Each related product has its own Add to Cart (shown on hover), outside its link.
    const add = within(region).getByRole("button", { name: "Add to Cart: iPhone 15" });
    expect(add).toHaveAttribute("data-variant", "iphone-15-v1");
    expect(add.closest("a")).toBeNull();
    expect(angles()).toEqual([180, 60, -60]);
  });

  it("turns to the next category every three seconds, however many related products it has", () => {
    expect(TURN_MS).toBe(3_000);
  });

  it("turns one place clockwise every three seconds, and shows the next category and its four products", () => {
    renderShowcase();
    act(() => vi.advanceTimersByTime(phones - 100));
    expect(within(hero()).getByText("Tecno Spark 20")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(100));
    expect(within(hero()).getByText("MacBook Air")).toBeInTheDocument();
    expect(within(hero()).getByText("More in Laptops")).toBeInTheDocument();
    expect(within(hero()).getByRole("link", { name: /HP 15/ })).toBeInTheDocument();
    expect(within(hero()).queryByText("Tecno Spark 20")).toBeNull();
    // Every angle grew by one place (120°): Laptops is now on the left, Phones moved on up.
    expect(angles()).toEqual([300, 180, 60]);

    // No price: no price line, still Shop Now. After the last category the first comes back,
    // still turning forward.
    act(() => vi.advanceTimersByTime(laptops));
    expect(within(hero()).getByRole("link", { name: "Shop Now" })).toHaveAttribute("href", "/product/lg-55");
    expect(within(hero()).queryByText(/RWF/)).toBeNull();
    act(() => vi.advanceTimersByTime(tvs));
    expect(within(hero()).getByText("Tecno Spark 20")).toBeInTheDocument();
    expect(angles()).toEqual([540, 420, 300]);
  });

  it("pauses while the pointer is on it", () => {
    renderShowcase();
    fireEvent.pointerEnter(hero());
    act(() => vi.advanceTimersByTime(20_000));
    expect(within(hero()).getByText("Tecno Spark 20")).toBeInTheDocument();
    fireEvent.pointerLeave(hero());
    act(() => vi.advanceTimersByTime(phones));
    expect(within(hero()).getByText("MacBook Air")).toBeInTheDocument();
  });

  it("resumes where it paused: a hover does not start the category's time again", () => {
    renderShowcase();
    act(() => vi.advanceTimersByTime(2_000));
    fireEvent.pointerEnter(hero());
    act(() => vi.advanceTimersByTime(10_000));
    fireEvent.pointerLeave(hero());
    // What was left comes after the pointer leaves, then the copy's exit.
    act(() => vi.advanceTimersByTime(phones - 2_000 - 100));
    expect(within(hero()).getByText("Tecno Spark 20")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(100));
    expect(within(hero()).getByText("MacBook Air")).toBeInTheDocument();
    // The new category gets its full time.
    act(() => vi.advanceTimersByTime(laptops - 100));
    expect(within(hero()).getByText("MacBook Air")).toBeInTheDocument();
  });

  it("shows four related products together", () => {
    const many = [{ ...CATEGORIES[0], related: Array.from({ length: 6 }, (_, i) => related(`p${i}`, `Phone ${i}`)) }, CATEGORIES[1]];
    renderShowcase(many);
    const tiles = within(hero()).getAllByRole("link", { name: /^Phone \d/ });
    expect(tiles.map((a) => a.getAttribute("href"))).toEqual(["/product/p0", "/product/p1", "/product/p2", "/product/p3"]);
    act(() => vi.advanceTimersByTime(TURN_MS));
    expect(within(hero()).getByText("MacBook Air")).toBeInTheDocument();
  });

  it("names the spotlight's category as its best seller", () => {
    renderShowcase();
    expect(within(hero()).getByRole("link", { name: "Best seller in Phones" })).toHaveAttribute("href", "/category/phones");
  });

  it("jumps to a category from its button, turning forward", () => {
    renderShowcase();
    fireEvent.click(within(hero()).getByRole("button", { name: "Show TVs & Audio" }));
    expect(within(hero()).getByRole("button", { name: "Show TVs & Audio" })).toHaveAttribute("aria-current", "true");
    expect(within(hero()).getByText("More in TVs & Audio")).toBeInTheDocument();
    expect(angles()).toEqual([420, 300, 180]);
  });

  it("does not rotate or show buttons with one category", () => {
    renderShowcase(CATEGORIES.slice(0, 1));
    act(() => vi.advanceTimersByTime(20_000));
    expect(within(hero()).getByText("Tecno Spark 20")).toBeInTheDocument();
    expect(within(hero()).queryByRole("button", { name: /^Show / })).toBeNull();
  });

  it("turns to Services as one place after the categories, bringing in four services", () => {
    const service = (slug: string, name: string) => ({ slug, name, icon: "wrench" as const, image: null });
    const services: ShowcaseServices = {
      kind: "services",
      id: "services",
      name: "Services",
      services: [service("cctv", "CCTV"), service("gates", "Gates"), service("access", "Access"), service("it", "IT"), service("repair", "Repair"), service("training", "Training")],
    };
    renderShowcase(CATEGORIES.slice(0, 1), services);
    // One place on the orbit for all the services, as for a category.
    expect(angles()).toHaveLength(2);
    fireEvent.click(within(hero()).getByRole("button", { name: "Show Services" }));
    expect(within(hero()).getByText("Furniture Services")).toBeInTheDocument();
    expect(within(hero()).getByRole("link", { name: "Our furniture services" })).toHaveAttribute("href", "/services");
    expect(within(hero()).getByRole("link", { name: "Explore services" })).toHaveAttribute("href", "/services");
    expect(within(hero()).getByRole("link", { name: "View all (6)" })).toHaveAttribute("href", "/services");
    const tiles = within(hero()).getAllByRole("link", { name: /^(CCTV|Gates|Access|IT|Repair|Training)$/ });
    // Four services beside the spotlight, as four products; "View all (6)" leads to the rest.
    expect(tiles.map((a) => a.getAttribute("href"))).toEqual(["/services/cctv", "/services/gates", "/services/access", "/services/it"]);
    expect(within(hero()).queryByRole("link", { name: "Shop Now" })).toBeNull();
  });
});
