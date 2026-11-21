import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { CatalogBrand } from "@/lib/catalogue";
import { BrandMarquee, brandCountLabel, MARQUEE_MIN_CARDS, marqueeBrands, marqueeHalf } from "./brand-marquee";

/** Trusted Brands on the home page: real logos only, an endless loop without a seam, and the
 * number of brands under it. */

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));

const logo = (name: string) => ({ url: `https://img.test/${name}.png`, width: 800, height: 400, alt: name, position: 0 });
const brand = (name: string, withLogo = true): CatalogBrand => ({
  id: name,
  name,
  slug: name.toLowerCase(),
  product_count: 1,
  logo: withLogo ? logo(name) : null,
});

describe("Trusted Brands", () => {
  it("shows only brands with a logo", () => {
    expect(marqueeBrands([brand("Apple"), brand("Acer", false), brand("Sony")]).map((b) => b.name)).toEqual(["Apple", "Sony"]);
  });

  it("repeats a short list so each half is wider than the screen", () => {
    const half = marqueeHalf(["a", "b", "c", "d", "e"]);
    expect(half.length).toBeGreaterThanOrEqual(MARQUEE_MIN_CARDS);
    expect(half.length % 5).toBe(0);
    expect(marqueeHalf([])).toEqual([]);
  });

  it("moves two identical halves, reading out and linking each brand once", () => {
    const brands = marqueeBrands([brand("Apple"), brand("Samsung")]);
    const { container } = render(<BrandMarquee brands={brands} label="Trusted Brands" />);
    const track = container.querySelector(".animate-marquee") as HTMLElement;
    const [first, copy] = track.querySelectorAll("ul");
    expect(first!.children.length).toBe(copy!.children.length);
    expect(copy).toHaveAttribute("aria-hidden", "true");
    expect(track.style.animationDuration).toBe(`${first!.children.length * 3}s`);
    const list = screen.getByRole("list", { name: "Trusted Brands" });
    const links = within(list).getAllByRole("link");
    expect(links.map((a) => [a.getAttribute("href"), within(a).getByRole("img").getAttribute("alt")])).toEqual([
      ["/brand/apple", "Apple"],
      ["/brand/samsung", "Samsung"],
    ]);
  });

  it("gives the exact number of brands below 20, then rounds down to tens with a plus", () => {
    expect(brandCountLabel(7)).toEqual({ count: 7, over: false });
    expect(brandCountLabel(46)).toEqual({ count: 40, over: true });
    expect(brandCountLabel(120)).toEqual({ count: 120, over: true });
  });
});
