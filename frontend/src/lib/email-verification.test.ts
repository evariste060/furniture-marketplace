import { describe, expect, it } from "vitest";
import { readLinkToken, retryAfterSeconds, withoutToken } from "./email-verification";

const TOKEN = "A".repeat(20) + "b_c-" + "9".repeat(19); // 43 URL-safe characters, like the backend's

describe("readLinkToken", () => {
  it("reads the token from the fragment the email links to", () => {
    expect(readLinkToken(`#token=${TOKEN}`, "")).toEqual({ kind: "ok", token: TOKEN });
  });

  it("accepts ?token= too, the fragment winning when both are there", () => {
    expect(readLinkToken("", `?token=${TOKEN}`)).toEqual({ kind: "ok", token: TOKEN });
    expect(readLinkToken(`#token=${TOKEN}`, "?token=other")).toEqual({ kind: "ok", token: TOKEN });
  });

  it("reports a missing token", () => {
    for (const [hash, search] of [["", ""], ["#", "?"], ["#token=", ""], ["#other=1", "?x=2"]]) {
      expect(readLinkToken(hash!, search!)).toEqual({ kind: "missing" });
    }
  });

  it("refuses anything the backend cannot have sent", () => {
    for (const bad of ["short", "x".repeat(129), `${TOKEN.slice(0, 40)}%20ab`, `${TOKEN.slice(0, 40)}<s>`, "a b".repeat(15)]) {
      expect(readLinkToken(`#token=${encodeURIComponent(bad)}`, "")).toEqual({ kind: "malformed" });
    }
  });

  it("survives malformed URLs", () => {
    expect(readLinkToken("#token=%E0%A4%A", "")).toEqual({ kind: "malformed" });
  });
});

describe("withoutToken", () => {
  it("removes only the token from the address", () => {
    expect(withoutToken("/verify-email", `?token=${TOKEN}`)).toBe("/verify-email");
    expect(withoutToken("/rw/verify-email", `?utm=mail&token=${TOKEN}`)).toBe("/rw/verify-email?utm=mail");
    expect(withoutToken("/verify-email", "")).toBe("/verify-email");
  });
});

describe("retryAfterSeconds", () => {
  it("reads usable Retry-After values only", () => {
    expect(retryAfterSeconds("120")).toBe(120);
    expect(retryAfterSeconds("1.2")).toBe(2);
    for (const bad of [null, "", "0", "-5", "soon"]) expect(retryAfterSeconds(bad)).toBeNull();
  });
});
