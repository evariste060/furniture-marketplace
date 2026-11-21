import { describe, expect, it } from "vitest";
import type { CatalogVariant } from "./catalogue";
import { initialVariant, optionGroups, pickVariant, VARIANT_GROUP } from "./variant-options";

function v(id: string, attributes: Record<string, unknown>, over: Partial<CatalogVariant> = {}): CatalogVariant {
  return {
    id,
    sku: id,
    name: `Name ${id}`,
    attributes,
    price: 1000,
    compare_at_price: null,
    currency_code: "RWF",
    stock_status: "in_stock",
    in_stock: true,
    images: [],
    ...over,
  };
}

const navy128 = v("a", { colour: "Navy", storage: "128 GB", ram: "8 GB" }, { price: 495_000 });
const ice256 = v("b", { colour: "Iceblue", storage: "256 GB", ram: "8 GB" }, { price: 560_000 });
const navy256 = v("c", { colour: "Navy", storage: "256 GB", ram: "8 GB" }, { price: 560_000, in_stock: false });

describe("option groups", () => {
  it("groups attributes that differ, colour first, and ignores shared ones", () => {
    expect(optionGroups([navy128, ice256, navy256])).toEqual([
      { key: "colour", values: ["Navy", "Iceblue"] },
      { key: "storage", values: ["128 GB", "256 GB"] },
    ]);
  });

  it("has no groups for a single variant", () => {
    expect(optionGroups([navy128])).toEqual([]);
  });

  it("lists variants by name when attributes do not tell them apart", () => {
    const groups = optionGroups([v("x", {}), v("y", { colour: "Red" })]);
    expect(groups).toEqual([{ key: VARIANT_GROUP, values: ["Name x", "Name y"] }]);
    expect(optionGroups([v("x", { colour: "Red" }), v("y", { colour: "Red" })])[0].key).toBe(VARIANT_GROUP);
  });
});

describe("picking", () => {
  const all = [navy128, ice256, navy256];
  const groups = optionGroups(all);

  it("keeps the other choices when that combination exists", () => {
    expect(pickVariant(all, groups, navy128, "storage", "256 GB")?.id).toBe("c");
  });

  it("falls back to a variant in stock with the picked value", () => {
    expect(pickVariant(all, groups, navy128, "colour", "Iceblue")?.id).toBe("b");
  });

  it("starts on the cheapest variant in stock", () => {
    expect(initialVariant([ice256, navy256, navy128])?.id).toBe("a");
    expect(initialVariant([])).toBeNull();
  });
});
