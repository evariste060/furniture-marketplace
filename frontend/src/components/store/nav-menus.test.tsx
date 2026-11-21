import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import type { MenuCategory } from "@/lib/catalogue";
import { CategoryLinks, type CategoryLinkItem } from "./category-links";
import { CategoryMegaMenu } from "./category-mega-menu";

/** The category nav's menus (All Categories and each category's subcategories): hover with a mouse, tap or click otherwise, and the data each
 * shows (the header loads it on the server; here it is passed in). */

const nav = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  usePathname: () => nav.pathname,
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));

const image = (name: string) => ({ url: `https://img.test/${name}.jpg`, width: 400, height: 400, alt: name, position: 0 });

const CATEGORIES: MenuCategory[] = [
  {
    id: "c1",
    name: "Phones",
    slug: "phones",
    brands: [],
    subcategories: [],
    products: {
      total: 9,
      items: [
        { id: "p1", name: "Galaxy A55", slug: "galaxy-a55", image: image("a55"), price: 450000 },
        { id: "p2", name: "iPhone 15", slug: "iphone-15", image: null, price: null },
      ],
    },
  },
  {
    id: "c2",
    name: "Laptops",
    slug: "laptops",
    brands: [{ name: "HP", slug: "hp", count: 1 }],
    subcategories: [],
    products: { total: 1, items: [{ id: "p3", name: "HP ProBook 450", slug: "hp-probook-450", image: null, price: 980000 }] },
  },
  { id: "c3", name: "TVs & Audio", slug: "tvs-audio", brands: [], subcategories: [], products: { total: 0, items: [] } },
  { id: "c4", name: "Accessories", slug: "accessories", brands: [], subcategories: [], products: null },
];

const LINKS: CategoryLinkItem[] = [
  {
    id: "l1",
    name: "Laptops",
    slug: "laptops",
    subcategories: [
      { id: "s1", name: "Gaming Laptops", slug: "gaming-laptops" },
      { id: "s2", name: "Monitors", slug: "monitors" },
    ],
  },
  { id: "p1", name: "Phones", slug: "phones", subcategories: [{ id: "s3", name: "Tablets", slug: "tablets" }] },
  { id: "d1", name: "Deals corner", slug: "deals-corner", subcategories: [] },
];

// jsdom has no ResizeObserver; the bar is not measured there (everything fits).
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

function renderWithIntl(ui: ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>,
  );
}

const trigger = (name: string) => screen.getByRole("button", { name });
const panel = (name: string) => screen.getByRole("region", { name, hidden: true });

/** A mouse moving from element to element. React derives pointerenter/leave from pointerout and
 * pointerover, so those are what this sends (synchronously, which fake timers need). */
function mouse() {
  let at: Element | null = null;
  return {
    moveTo(target: Element) {
      if (at) fireEvent.pointerOut(at, { pointerType: "mouse", relatedTarget: target });
      fireEvent.pointerOver(target, { pointerType: "mouse", relatedTarget: at });
      at = target;
    },
  };
}

afterEach(() => {
  vi.useRealTimers();
  nav.pathname = "/";
});

describe("All Categories mega menu", () => {
  it("opens on click, lists the categories and the first one's best sellers", async () => {
    const user = userEvent.setup();
    renderWithIntl(<CategoryMegaMenu categories={CATEGORIES} />);
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "false");

    await user.keyboard("{Tab}{Enter}");
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "true");
    const menu = panel("All Categories");
    for (const c of CATEGORIES) {
      expect(within(menu).getByRole("link", { name: c.name })).toHaveAttribute("href", `/category/${c.slug}`);
    }
    expect(within(menu).getByRole("link", { name: /Galaxy A55/ })).toHaveAttribute("href", "/product/galaxy-a55");
    expect(within(menu).getByRole("link", { name: /Galaxy A55/ })).toHaveTextContent("RWF");
    // No variant: no price, still a link to the product.
    expect(within(menu).getByRole("link", { name: "iPhone 15" })).toHaveAttribute("href", "/product/iphone-15");
    expect(within(menu).getByRole("link", { name: "View all (9)" })).toHaveAttribute("href", "/category/phones");
    expect(within(menu).getByRole("link", { name: "Browse all products" })).toHaveAttribute("href", "/products");
  });

  it("shows the hovered category's products after a short pause", () => {
    vi.useFakeTimers();
    renderWithIntl(<CategoryMegaMenu categories={CATEGORIES} />);
    const pointer = mouse();
    pointer.moveTo(trigger("All Categories"));
    act(() => vi.advanceTimersByTime(100));
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "true");
    const menu = panel("All Categories");

    pointer.moveTo(within(menu).getByRole("link", { name: "Laptops" }));
    // Not yet: a cursor passing over a category on its way elsewhere switches nothing.
    expect(within(menu).queryByRole("link", { name: /HP ProBook/ })).toBeNull();
    act(() => vi.advanceTimersByTime(150));
    expect(within(menu).getByRole("link", { name: /HP ProBook 450/ })).toHaveAttribute("href", "/product/hp-probook-450");
    expect(within(menu).getByRole("link", { name: "HP1" })).toHaveAttribute("href", "/category/laptops?brand=hp");
    expect(within(menu).queryByRole("link", { name: /Galaxy A55/ })).toBeNull();

    // Crossing a category quickly on the way to the products panel keeps Laptops shown.
    pointer.moveTo(within(menu).getByRole("link", { name: "TVs & Audio" }));
    act(() => vi.advanceTimersByTime(50));
    pointer.moveTo(within(menu).getByRole("link", { name: /HP ProBook 450/ }));
    act(() => vi.advanceTimersByTime(500));
    expect(within(menu).getByRole("link", { name: /HP ProBook 450/ })).toBeInTheDocument();
  });

  it("stays open while the cursor moves from the trigger into the panel, and closes after leaving", () => {
    vi.useFakeTimers();
    renderWithIntl(
      <>
        <CategoryMegaMenu categories={CATEGORIES} />
        <p>Page content</p>
      </>,
    );
    const pointer = mouse();
    pointer.moveTo(trigger("All Categories"));
    act(() => vi.advanceTimersByTime(100));
    pointer.moveTo(within(panel("All Categories")).getByRole("link", { name: "Phones" }));
    act(() => vi.advanceTimersByTime(500));
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "true");

    pointer.moveTo(screen.getByText("Page content"));
    act(() => vi.advanceTimersByTime(100));
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "true");
    act(() => vi.advanceTimersByTime(150));
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "false");
  });

  it("does not open when the cursor only passes over the trigger", () => {
    vi.useFakeTimers();
    renderWithIntl(
      <>
        <CategoryMegaMenu categories={CATEGORIES} />
        <p>Page content</p>
      </>,
    );
    const pointer = mouse();
    pointer.moveTo(trigger("All Categories"));
    act(() => vi.advanceTimersByTime(40));
    pointer.moveTo(screen.getByText("Page content"));
    act(() => vi.advanceTimersByTime(500));
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "false");
  });

  it("on touch, the first tap on a category shows its products instead of leaving the page", async () => {
    const user = userEvent.setup();
    renderWithIntl(<CategoryMegaMenu categories={CATEGORIES} />);
    await user.click(trigger("All Categories"));
    const laptops = within(panel("All Categories")).getByRole("link", { name: "Laptops" });

    fireEvent.pointerDown(laptops, { pointerType: "touch" });
    const firstTap = fireEvent.click(laptops);
    expect(firstTap).toBe(false); // default prevented: no navigation
    expect(within(panel("All Categories")).getByRole("link", { name: /HP ProBook 450/ })).toBeInTheDocument();

    fireEvent.pointerDown(laptops, { pointerType: "touch" });
    expect(fireEvent.click(laptops)).toBe(true); // shown already: the link opens the category
  });

  it("shows empty and error states per category", async () => {
    const user = userEvent.setup();
    renderWithIntl(<CategoryMegaMenu categories={CATEGORIES} />);
    await user.click(trigger("All Categories"));
    const menu = panel("All Categories");

    act(() => within(menu).getByRole("link", { name: "TVs & Audio" }).focus());
    expect(within(menu).getByText("No products in this category yet.")).toBeInTheDocument();
    expect(within(menu).getByRole("link", { name: "View category" })).toHaveAttribute("href", "/category/tvs-audio");

    act(() => within(menu).getByRole("link", { name: "Accessories" }).focus());
    expect(within(menu).getByText(/couldn't load these products/)).toBeInTheDocument();
  });

  it("starts on the category being browsed and marks it", async () => {
    nav.pathname = "/category/laptops";
    const user = userEvent.setup();
    renderWithIntl(<CategoryMegaMenu categories={CATEGORIES} />);
    await user.click(trigger("All Categories"));
    const menu = panel("All Categories");
    expect(within(menu).getByRole("link", { name: "Laptops" })).toHaveAttribute("aria-current", "page");
    expect(within(menu).getByRole("link", { name: /HP ProBook 450/ })).toBeInTheDocument();
  });

  it("closes with Escape and gives focus back to the trigger", async () => {
    const user = userEvent.setup();
    renderWithIntl(<CategoryMegaMenu categories={CATEGORIES} />);
    await user.click(trigger("All Categories"));
    act(() => within(panel("All Categories")).getByRole("link", { name: "Phones" }).focus());
    await user.keyboard("{Escape}");
    expect(trigger("All Categories")).toHaveAttribute("aria-expanded", "false");
    expect(trigger("All Categories")).toHaveFocus();
  });

  it("says so when there are no categories", async () => {
    const user = userEvent.setup();
    renderWithIntl(<CategoryMegaMenu categories={[]} />);
    await user.click(trigger("All Categories"));
    expect(within(panel("All Categories")).getByText("No categories yet.")).toBeInTheDocument();
  });
});

describe("category dropdowns", () => {
  it("shows each category as text linking to its page, with no icons", () => {
    const { container } = renderWithIntl(<CategoryLinks items={LINKS} />);
    expect(screen.getByRole("link", { name: "Laptops" })).toHaveAttribute("href", "/category/laptops");
    expect(screen.getByRole("link", { name: "Deals corner" })).toHaveAttribute("href", "/category/deals-corner");
    expect(container.querySelector("svg.lucide")).toBeNull();
    // A category without subcategories has no dropdown.
    expect(screen.queryByRole("button", { name: "Deals corner subcategories" })).toBeNull();
  });

  it("opens on hover with only that category's subcategories", () => {
    vi.useFakeTimers();
    renderWithIntl(<CategoryLinks items={LINKS} />);
    mouse().moveTo(screen.getByRole("link", { name: "Laptops" }));
    act(() => vi.advanceTimersByTime(200));
    expect(trigger("Laptops subcategories")).toHaveAttribute("aria-expanded", "true");
    const list = panel("Laptops subcategories");
    expect(within(list).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Gaming Laptops", "/category/gaming-laptops"],
      ["Monitors", "/category/monitors"],
    ]);
    expect(trigger("Phones subcategories")).toHaveAttribute("aria-expanded", "false");
  });

  it("opens from its caret with a click or keyboard, and closes once one is chosen", async () => {
    const user = userEvent.setup();
    renderWithIntl(<CategoryLinks items={LINKS} />);
    await user.click(trigger("Phones subcategories"));
    const tablets = within(panel("Phones subcategories")).getByRole("link", { name: "Tablets" });
    await user.click(tablets);
    expect(trigger("Phones subcategories")).toHaveAttribute("aria-expanded", "false");
  });

  it("marks the category while one of its subcategories is open", () => {
    nav.pathname = "/category/monitors";
    renderWithIntl(<CategoryLinks items={LINKS} />);
    expect(screen.getByRole("link", { name: "Laptops" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Phones" })).not.toHaveAttribute("aria-current");
  });
});
