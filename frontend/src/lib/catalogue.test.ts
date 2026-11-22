import { describe, expect, it } from "vitest";
import {
  activeFilterCount,
  discountPercent,
  displayVariant,
  filterQuery,
  listingSearch,
  parseListingState,
  productQuery,
  productStock,
  searchText,
  defaultSort,
  starFill,
  type CatalogVariant,
} from "./catalogue";

function variant(over: Partial<CatalogVariant>): CatalogVariant {
  return {
    id: "v",
    sku: "SKU",
    name: "Std",
    attributes: {},
    price: 1000,
    compare_at_price: null,
    currency_code: "RWF",
    stock_status: "in_stock",
    in_stock: true,
    images: [],
    ...over,
  };
}

describe("cards", () => {
  it("shows the cheapest variant in stock, else the cheapest", () => {
    const cheapOut = variant({ id: "a", price: 100, in_stock: false, stock_status: "out_of_stock" });
    const mid = variant({ id: "b", price: 200 });
    const dear = variant({ id: "c", price: 300 });
    expect(displayVariant({ variants: [dear, cheapOut, mid] })?.id).toBe("b");
    expect(displayVariant({ variants: [variant({ id: "d", price: 5, in_stock: false }), cheapOut] })?.id).toBe("d");
    expect(displayVariant({ variants: [] })).toBeNull();
  });

  it("computes the discount from compare_at_price, rounded down", () => {
    expect(discountPercent({ price: 180_000, compare_at_price: 200_000 })).toBe(10);
    expect(discountPercent({ price: 185_000, compare_at_price: 199_000 })).toBe(7);
    expect(discountPercent({ price: 1000, compare_at_price: 1000 })).toBeNull();
    expect(discountPercent({ price: 1000, compare_at_price: null })).toBeNull();
    expect(discountPercent({ price: 999, compare_at_price: 1000 })).toBeNull(); // under 1%
  });

  it("derives the stock badge from the variants", () => {
    expect(productStock({ variants: [variant({}), variant({ stock_status: "low_stock" })] })).toBe("in_stock");
    expect(productStock({ variants: [variant({ stock_status: "low_stock" })] })).toBe("low_stock");
    expect(productStock({ variants: [variant({ in_stock: false, stock_status: "out_of_stock" })] })).toBe("out_of_stock");
    expect(productStock({ variants: [] })).toBe("out_of_stock");
  });

  it("rounds the stars to half stars", () => {
    expect(starFill(null)).toBe(0);
    expect(starFill(4.2)).toBe(4);
    expect(starFill(4.3)).toBe(4.5);
    expect(starFill(4.8)).toBe(5);
  });
});

describe("listing state", () => {
  it("defaults to popular, grid, page 1 and no filters", () => {
    const state = parseListingState({});
    expect(state).toEqual({
      q: null,
      category: null,
      brands: [],
      minPrice: null,
      maxPrice: null,
      stock: [],
      minRating: null,
      attributes: { material: [], color: [], style: [] },
      sort: "popular",
      view: "grid",
      page: 1,
    });
    expect(listingSearch(state)).toBe("");
    expect(productQuery(state)).toEqual({ sort_by: "bestselling", sort_direction: "desc", page: 1, size: 12 });
  });

  it("round-trips through the URL", () => {
    const search = "?brand=samsung&brand=apple&min_price=200000&max_price=399999&stock=in&rating=4&sort=price_desc&view=list&page=2";
    const state = parseListingState(Object.fromEntries([...new URLSearchParams(search).keys()].map((k) => {
      const v = new URLSearchParams(search).getAll(k);
      return [k, v.length > 1 ? v : v[0]];
    })));
    expect(listingSearch(state)).toBe(search);
    expect(productQuery(state)).toEqual({
      brand: ["samsung", "apple"],
      min_price: 200_000,
      max_price: 399_999,
      in_stock: true,
      min_rating: 4,
      sort_by: "price",
      sort_direction: "desc",
      page: 2,
      size: 12,
    });
    expect(activeFilterCount(state)).toBe(5);
  });

  it("ignores invalid or contradictory values instead of sending them to the API", () => {
    const state = parseListingState({
      brand: ["Samsung!", "ok-brand", "ok-brand"],
      min_price: "500",
      max_price: "100",
      stock: ["in", "out"],
      rating: "9",
      sort: "cheapest",
      view: "table",
      page: "-3",
    });
    expect(state.brands).toEqual(["ok-brand"]);
    expect([state.minPrice, state.maxPrice]).toEqual([null, null]);
    expect(state.stock).toEqual([]); // both ticked = no filter
    expect(state.minRating).toBeNull();
    expect([state.sort, state.view, state.page]).toEqual(["popular", "grid", 1]);
    expect(filterQuery(state)).toEqual({ brand: ["ok-brand"] });
  });

  it("asks for out-of-stock products only when just that box is ticked", () => {
    expect(filterQuery(parseListingState({ stock: "out" }))).toEqual({ in_stock: false });
  });

  it("keeps at most 20 brands, the API's limit", () => {
    const many = Array.from({ length: 25 }, (_, i) => `b${i}`);
    expect(parseListingState({ brand: many }).brands).toHaveLength(20);
  });
  it("keeps one category and sends it to the API", () => {
    const state = parseListingState({ category: ["phones", "laptops"] });
    expect(state.category).toBe("phones");
    expect(filterQuery(state)).toEqual({ category: "phones" });
    expect(listingSearch(state)).toBe("?category=phones");
    expect(activeFilterCount(state)).toBe(1);
    expect(parseListingState({ category: "Not a slug!" }).category).toBeNull();
  });
});

describe("search state", () => {
  it("reads q only on the search page, tidied and capped at 160 characters", () => {
    expect(parseListingState({ q: "galaxy" }).q).toBeNull();
    expect(parseListingState({ q: "  galaxy   a55 " }, { search: true }).q).toBe("galaxy a55");
    expect(parseListingState({ q: "   " }, { search: true }).q).toBeNull();
    expect(parseListingState({ q: "x".repeat(300) }, { search: true }).q).toHaveLength(160);
    expect(searchText(["first", "second"])).toBe("first");
  });

  it("defaults to best match with a search and keeps it out of the URL", () => {
    const state = parseListingState({ q: "galaxy" }, { search: true });
    expect(state.sort).toBe("relevance");
    expect(defaultSort(state)).toBe("relevance");
    expect(listingSearch(state)).toBe("?q=galaxy");
    expect(productQuery(state)).toEqual({ q: "galaxy", page: 1, size: 12 });
    const popular = { ...state, sort: "popular" as const };
    expect(listingSearch(popular)).toBe("?q=galaxy&sort=popular");
    expect(parseListingState({ q: "galaxy", sort: "popular" }, { search: true }).sort).toBe("popular");
  });

  it("has no best match without a search", () => {
    expect(parseListingState({ sort: "relevance" }).sort).toBe("popular");
    expect(parseListingState({ sort: "relevance" }, { search: true }).sort).toBe("popular");
  });
});
