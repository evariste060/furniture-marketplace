import { Cable, Laptop, Refrigerator, Smartphone, Tag, Tv } from "lucide-react";
import { describe, expect, it } from "vitest";
import { categoryIcon } from "./category-icon";
import { menuProduct, menuProductQuery, type CatalogProduct } from "./catalogue";

describe("categoryIcon", () => {
  it("picks an icon from the category's slug and name", () => {
    expect(categoryIcon({ slug: "phones", name: "Phones" })).toBe(Smartphone);
    expect(categoryIcon({ slug: "laptops", name: "Laptops" })).toBe(Laptop);
    expect(categoryIcon({ slug: "tvs-audio", name: "TVs & Audio" })).toBe(Tv);
    expect(categoryIcon({ slug: "home-appliances", name: "Home Appliances" })).toBe(Refrigerator);
    expect(categoryIcon({ slug: "accessories", name: "Accessories" })).toBe(Cable);
  });

  it("matches whole words only, and falls back to the tag", () => {
    expect(categoryIcon({ slug: "earphones-x", name: "Xylophones" })).not.toBe(Smartphone);
    expect(categoryIcon({ slug: "furniture", name: "Furniture" })).toBe(Tag);
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
