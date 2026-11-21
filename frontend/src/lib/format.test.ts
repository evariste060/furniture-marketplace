import { describe, expect, it } from "vitest";
import { formatDate, formatMoney, formatPhone } from "./format";
import { hasLocalImageHost, imageRemotePatterns } from "./image-hosts";
import { primaryImage } from "./images";
import { pageWindow } from "@/components/ui/pagination";

describe("formatMoney", () => {
  it("shows whole RWF with thousands separators and no decimals", () => {
    expect(formatMoney(580000)).toBe("RWF 580,000");
    expect(formatMoney(0)).toBe("RWF 0");
    expect(formatMoney(1450000)).toBe("RWF 1,450,000");
  });
});

describe("formatPhone", () => {
  it.each(["+250788123456", "250788123456", "0788123456", "0788 123 456"])("formats %s", (value) => {
    expect(formatPhone(value)).toBe("+250 788 123 456");
  });
  it("leaves anything that is not a Rwandan mobile unchanged", () => {
    expect(formatPhone("12345")).toBe("12345");
  });
});

describe("formatDate", () => {
  it("shows Kigali time whatever the input zone", () => {
    // 22:30 UTC on 23 Oct is 00:30 on 24 Oct in Kigali (UTC+2).
    expect(formatDate("2026-10-23T22:30:00Z")).toBe("24 Oct 2026");
    expect(formatDate("2026-10-23T22:30:00Z", "dateTime")).toBe("24 Oct 2026, 00:30");
  });
});

describe("image hosts", () => {
  it("parses comma-separated URL patterns", () => {
    const patterns = imageRemotePatterns("http://localhost:8000/media/**, https://cdn.example.rw/**");
    expect(patterns).toEqual([
      { protocol: "http", hostname: "localhost", port: "8000", pathname: "/media/**", search: "" },
      { protocol: "https", hostname: "cdn.example.rw", port: "", pathname: "/**", search: "" },
    ]);
    expect(hasLocalImageHost(patterns)).toBe(true);
    expect(hasLocalImageHost(patterns.slice(1))).toBe(false);
    expect(imageRemotePatterns(undefined)).toEqual([]);
  });
  it("refuses other protocols", () => {
    expect(() => imageRemotePatterns("ftp://x.rw/**")).toThrow(/protocol/);
  });
});

describe("primaryImage", () => {
  it("picks the lowest position, or null", () => {
    const a = { url: "a", width: 1, height: 1, alt: "", position: 2 };
    const b = { ...a, url: "b", position: 1 };
    expect(primaryImage([a, b])?.url).toBe("b");
    expect(primaryImage([])).toBeNull();
    expect(primaryImage(undefined)).toBeNull();
  });
});

describe("pageWindow", () => {
  it("shows the first, last and neighbouring pages with gaps", () => {
    expect(pageWindow(1, 1)).toEqual([1]);
    expect(pageWindow(2, 3)).toEqual([1, 2, 3]);
    expect(pageWindow(5, 10)).toEqual([1, null, 4, 5, 6, null, 10]);
  });
});
