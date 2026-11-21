import { describe, expect, it } from "vitest";
import { bandLabel, shortAmount } from "./price-bands";

const t = (key: string, v: Record<string, string>) => `${key}:${Object.values(v).join("|")}`;

describe("price bands", () => {
  it("labels the API's bands as the design does", () => {
    expect(bandLabel({ min_price: null, max_price: 199_999 }, t, "long")).toBe("under:200,000");
    expect(bandLabel({ min_price: 200_000, max_price: 399_999 }, t, "long")).toBe("between:200,000|400,000");
    expect(bandLabel({ min_price: 1_000_000, max_price: null }, t, "long")).toBe("above:1,000,000");
    expect(bandLabel({ min_price: 600_000, max_price: 999_999 }, t, "short")).toBe("between:600k|1M");
  });
  it("shortens round amounts only", () => {
    expect(shortAmount(1_500_000)).toBe("1.5M");
    expect(shortAmount(250_000)).toBe("250k");
    expect(shortAmount(1234)).toBe("1,234");
  });
});
