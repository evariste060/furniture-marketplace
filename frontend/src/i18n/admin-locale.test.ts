import { describe, expect, it } from "vitest";
import { adminLocale, adminLocaleCookie } from "./admin-locale";

describe("admin language", () => {
  it("is Kinyarwanda only when the cookie asks for it", () => {
    expect(adminLocale("rw")).toBe("rw");
    expect(adminLocale("en")).toBe("en");
    expect(adminLocale(undefined)).toBe("en");
    expect(adminLocale("fr")).toBe("en");
  });

  it("is kept for a year, for the admin only", () => {
    expect(adminLocaleCookie("rw")).toBe("admin_locale=rw; Path=/admin; Max-Age=31536000; SameSite=Lax");
  });
});
