import { describe, expect, it } from "vitest";
import en from "../../messages/en.json";
import rw from "../../messages/rw.json";
import { MARKETPLACE_NAME, withMarketplace } from "./marketplace";

describe("the marketplace name (ADR-014 decision 16)", () => {
  it("defaults to FurniHub and is filled into every message", () => {
    expect(MARKETPLACE_NAME).toBe("FurniHub");
    const filled = withMarketplace({ a: "{marketplace} — home", b: { c: ["New to {marketplace}?"] }, n: 3 });
    expect(filled).toEqual({ a: "FurniHub — home", b: { c: ["New to FurniHub?"] }, n: 3 });
  });

  it("escapes an apostrophe for ICU", () => {
    expect(withMarketplace("© {marketplace}", "Kim's Home")).toBe("© Kim''s Home");
  });

  it("leaves no old store name in the English or Kinyarwanda messages", () => {
    for (const messages of [en, rw]) {
      const text = JSON.stringify(messages);
      expect(text).not.toMatch(/3 ?Sixty/i);
      expect(withMarketplace(messages).store.logoAlt).toBe("FurniHub");
    }
  });
});
