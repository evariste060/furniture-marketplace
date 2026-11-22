import { describe, expect, it } from "vitest";
import { attributeSetFor, attributesToObject, attributeValues, parseMeasure } from "./product-editor";

describe("the product editor's furniture details (ADR-014 phase 6)", () => {
  it("sends numbers, booleans and codes, and leaves unset attributes out", () => {
    expect(attributesToObject({ width_cm: "92,5", height_cm: " ", material: "fabric", assembly_required: "false" })).toEqual({
      width_cm: 92.5,
      material: "fabric",
      assembly_required: false,
    });
  });

  it("reads the stored attributes back as text, never the free specifications", () => {
    expect(attributeValues({ width_cm: 210, assembly_required: true, Cushions: "Removable" })).toEqual({ width_cm: "210", assembly_required: "true" });
  });

  it("accepts positive measurements up to the backend's limit only", () => {
    expect(parseMeasure("45")).toBe(45);
    expect(parseMeasure("0")).toBeNull();
    expect(parseMeasure("-3")).toBeNull();
    expect(parseMeasure("12cm")).toBeNull();
    expect(parseMeasure("100001")).toBeNull();
  });

  it("uses the category's set, else its main category's, else the default", () => {
    const definitions = { default_set: ["width_cm"], sets: { sofas: ["seat_height_cm"], "living-room": ["material"] } };
    const categories = [
      { id: "m", name: "Living Room", slug: "living-room", parent_id: null, is_active: true, sort_order: 1 },
      { id: "s", name: "Sofas", slug: "sofas", parent_id: "m", is_active: true, sort_order: 1 },
      { id: "c", name: "Coffee Tables", slug: "coffee-tables", parent_id: "m", is_active: true, sort_order: 2 },
      { id: "x", name: "Other", slug: "other", parent_id: null, is_active: true, sort_order: 2 },
    ];
    expect(attributeSetFor(definitions, categories, "s")).toEqual(["seat_height_cm"]);
    expect(attributeSetFor(definitions, categories, "c")).toEqual(["material"]);
    expect(attributeSetFor(definitions, categories, "x")).toEqual(["width_cm"]);
  });
});
