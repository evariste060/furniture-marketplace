import { Archive, Baby, BedDouble, Briefcase, Sofa, Tag, TreePalm, Tv, UtensilsCrossed } from "lucide-react";
import { describe, expect, it } from "vitest";
import { categoryIcon } from "./category-icon";
import { menuProduct, menuProductQuery, type CatalogProduct } from "./catalogue";

/** The main categories of the furniture taxonomy (backend/app/core/furniture.py). */
const TAXONOMY_ICONS = [
  { slug: "living-room", name: "Living Room" },
  { slug: "bedroom", name: "Bedroom" },
  { slug: "dining", name: "Dining" },
  { slug: "office", name: "Office" },
  { slug: "outdoor", name: "Outdoor" },
  { slug: "kids", name: "Kids" },
];

describe("categoryIcon", () => {
  it("picks an icon from the category's slug and name", () => {
    expect(categoryIcon({ slug: "living-room", name: "Living Room" })).toBe(Sofa);
    expect(categoryIcon({ slug: "bedroom", name: "Bedroom" })).toBe(BedDouble);
    expect(categoryIcon({ slug: "dining", name: "Dining" })).toBe(UtensilsCrossed);
    expect(categoryIcon({ slug: "office", name: "Office" })).toBe(Briefcase);
    expect(categoryIcon({ slug: "outdoor", name: "Outdoor" })).toBe(TreePalm);
    expect(categoryIcon({ slug: "kids", name: "Kids" })).toBe(Baby);
  });

  it("lets the earlier rule win for subcategories", () => {
    expect(categoryIcon({ slug: "kids-beds", name: "Kids' Beds" })).toBe(Baby);
    expect(categoryIcon({ slug: "office-storage", name: "Office Storage" })).toBe(Briefcase);
    expect(categoryIcon({ slug: "tv-stands", name: "TV Stands" })).toBe(Tv);
    expect(categoryIcon({ slug: "wardrobes", name: "Wardrobes" })).toBe(Archive);
  });

  it("gives every main category of the taxonomy its own icon", () => {
    for (const main of TAXONOMY_ICONS) expect(categoryIcon(main)).not.toBe(Tag);
  });

  it("matches whole words only, and falls back to the tag", () => {
    expect(categoryIcon({ slug: "bedazzled", name: "Bedazzled" })).toBe(Tag);
    expect(categoryIcon({ slug: "phones", name: "Phones" })).toBe(Tag);
  });
});

describe("menuProduct", () => {
  const product = {
    id: "p",
    name: "Galaxy A55",
    slug: "galaxy-a55",
    images: [
      { url: "https://img.test/2.jpg", width: 1, height: 1, alt: "back", position: 2 },
      { url: "https://img.test/1.jpg", width: 1, height: 1, alt: "front", position: 1 },
    ],
    variants: [
      { price: 500000, in_stock: false },
      { price: 450000, in_stock: true },
    ],
  } as unknown as CatalogProduct;

  it("keeps the name, slug, first image and the display variant's price", () => {
    expect(menuProduct(product)).toEqual({
      id: "p",
      name: "Galaxy A55",
      slug: "galaxy-a55",
      image: product.images[1],
      price: 450000,
    });
  });

  it("has no image or price when the product has none", () => {
    expect(menuProduct({ ...product, images: [], variants: [] })).toMatchObject({ image: null, price: null });
  });

  it("asks for a category's best sellers", () => {
    expect(menuProductQuery("phones")).toEqual({
      category: "phones",
      page: 1,
      size: 9, // the mega menu's 6, the hero's spotlight and its 6 related products, or a spotlight's showcase and 8 cards
      sort_by: "bestselling",
      sort_direction: "desc",
    });
  });
});
