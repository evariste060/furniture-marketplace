import { describe, expect, it } from "vitest";
import { emailOk, initials, maskIdentifier, passwordOk, passwordStrength, safeReturnTo } from "./auth";

describe("safeReturnTo", () => {
  it("keeps paths on this site", () => {
    expect(safeReturnTo("/cart")).toBe("/cart");
    expect(safeReturnTo("/product/x?y=1#z")).toBe("/product/x?y=1#z");
    expect(safeReturnTo(["/checkout", "/x"])).toBe("/checkout");
  });

  it("refuses other origins and odd values", () => {
    for (const bad of ["//evil.example", "https://evil.example", "/\\evil.example", "evil", "", "/\tx", "/\u0000"]) {
      expect(safeReturnTo(bad)).toBe("/account");
    }
    expect(safeReturnTo(null, "/")).toBe("/");
    expect(safeReturnTo(`/${"a".repeat(600)}`)).toBe("/account");
  });
});

describe("passwords", () => {
  it("follows the backend rule", () => {
    expect(passwordOk("Kigali2026")).toBe(true);
    expect(passwordOk("Kigali-pass")).toBe(true);
    expect(passwordOk("kigali2026")).toBe(false);
    expect(passwordOk("KIGALI2026")).toBe(false);
    expect(passwordOk("Kigalipass")).toBe(false);
    expect(passwordOk("Kig2")).toBe(false);
  });

  it("scores the meter", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("abc")).toBe(1);
    expect(passwordStrength("abcdefgh")).toBe(1);
    expect(passwordStrength("Abcdefgh")).toBe(2);
    expect(passwordStrength("Kigali2026")).toBe(3);
    expect(passwordStrength("Kigali-2026-ok")).toBe(4);
  });
});

describe("identifiers", () => {
  it("checks emails", () => {
    expect(emailOk("aline@example.com")).toBe(true);
    expect(emailOk("aline@example")).toBe(false);
  });

  it("masks phones and emails", () => {
    expect(maskIdentifier("0788000111")).toBe("+250 788 ••• 111");
    expect(maskIdentifier("+250 788 000 111")).toBe("+250 788 ••• 111");
    expect(maskIdentifier("aline@example.com")).toBe("al•••@example.com");
  });

  it("makes initials", () => {
    expect(initials("Aline Mukamana")).toBe("AM");
    expect(initials("Aline Uwase Mukamana")).toBe("AM");
    expect(initials("Aline")).toBe("A");
    expect(initials(null)).toBe("?");
  });
});
