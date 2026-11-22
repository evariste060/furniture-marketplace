import { describe, expect, it } from "vitest";
import en from "../../messages/en.json";
import rw from "../../messages/rw.json";
import { ATTRIBUTE_KEYS, attributeCodes, CHOICES, specificationRow } from "./furniture";
import { listingSearch, parseListingState, filterQuery, activeFilterCount } from "./catalogue";

type Tree = { [key: string]: string | Tree };
const lookup = (tree: Tree) => (key: string, values?: Record<string, string | number>) => {
  const found = key.split(".").reduce<string | Tree | undefined>((node, part) => (typeof node === "object" ? node[part] : undefined), tree);
  if (typeof found !== "string") throw new Error(`missing ${key}`);
  return found.replace("{value}", String(values?.value ?? ""));
};

describe("furniture attributes (ADR-014 phase 6)", () => {
  it("has an English and a Kinyarwanda label for every attribute and every code", () => {
    for (const messages of [en.furniture, rw.furniture] as unknown as Tree[]) {
      const t = lookup(messages);
      for (const key of ATTRIBUTE_KEYS) expect(t(`names.${key}`)).not.toBe("");
      for (const [key, codes] of Object.entries(CHOICES)) for (const code of codes) expect(t(`${key}.${code}`)).not.toBe("");
    }
  });

  it("shows known attributes translated, with units, and free ones as written", () => {
    const t = lookup(en.furniture as unknown as Tree);
    expect(specificationRow("width_cm", 210, t)).toEqual({ label: "Width", value: "210 cm" });
    expect(specificationRow("weight_kg", 58, t)).toEqual({ label: "Weight", value: "58 kg" });
    expect(specificationRow("material", "solid_wood", t)).toEqual({ label: "Material", value: "Solid wood" });
    expect(specificationRow("assembly_required", false, t)).toEqual({ label: "Assembly required", value: "No" });
    expect(specificationRow("Cushions", "Removable covers", t)).toEqual({ label: "Cushions", value: "Removable covers" });
    expect(specificationRow("color", "purple", t)).toEqual({ label: "Colour", value: "purple" });
  });

  it("keeps known codes only, once each, in the attribute's order", () => {
    expect(attributeCodes("material", ["fabric", "oak wood", "solid_wood", "fabric"])).toEqual(["solid_wood", "fabric"]);
  });

  it("reads and writes the attribute filters in the listing URL and API query", () => {
    const state = parseListingState({ material: ["fabric", "unobtainium"], color: "oak", style: "Modern" });
    expect(state.attributes).toEqual({ material: ["fabric"], color: ["oak"], style: [] });
    expect(listingSearch(state)).toBe("?material=fabric&color=oak");
    expect(filterQuery(state)).toEqual({ material: ["fabric"], color: ["oak"] });
    expect(activeFilterCount(state)).toBe(2);
  });
});
