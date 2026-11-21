import { afterEach, describe, expect, it } from "vitest";
import {
  checkAddress,
  checkContact,
  checkoutStep,
  countdown,
  localPhone,
  orderAccess,
  orderAddress,
  orderNumber,
  rememberOrder,
  secondsLeft,
  splitName,
} from "./checkout";

const CONTACT = { firstName: " Aline ", lastName: "Mukamana", phone: "788 000 111", email: "" };
const ADDRESS = { district: "Gasabo", sector: " Kimironko ", street: "KG 11 Ave, House 24", landmark: "", save: false };

describe("localPhone", () => {
  it("accepts the ways people type a Rwandan mobile number", () => {
    for (const typed of ["788000111", "788 000 111", "0788000111", "+250 788 000 111", "250788000111"])
      expect(localPhone(typed)).toBe("788000111");
    expect(localPhone("0722 123 456")).toBe("722123456");
  });
  it("refuses other numbers", () => {
    for (const typed of ["", "12345", "0788", "0758000111", "+254788000111", "07880001112"]) expect(localPhone(typed)).toBeNull();
  });
});

describe("form checks", () => {
  it("requires a name, a valid phone and, if given, a valid email", () => {
    expect(checkContact(CONTACT)).toEqual({});
    expect(checkContact({ firstName: "", lastName: " ", phone: "", email: "" })).toEqual({
      firstName: "required",
      lastName: "required",
      phone: "required",
    });
    expect(checkContact({ ...CONTACT, phone: "12", email: "not-an-email" })).toEqual({ phone: "invalid", email: "invalid" });
  });
  it("requires a district we deliver to and a street", () => {
    const districts = ["Gasabo", "Kicukiro"];
    expect(checkAddress(ADDRESS, districts)).toEqual({});
    expect(checkAddress({ ...ADDRESS, district: "", street: "" }, districts)).toEqual({ district: "required", street: "required" });
    expect(checkAddress({ ...ADDRESS, district: "Musanze", street: "x" }, districts)).toEqual({ district: "invalid", street: "invalid" });
  });
});

describe("orderAddress", () => {
  it("sends the contact person as the recipient and trims the fields, with no amounts", () => {
    expect(orderAddress(CONTACT, ADDRESS)).toEqual({
      recipient_name: "Aline Mukamana",
      phone: "0788000111",
      district: "Gasabo",
      sector: "Kimironko",
      street_address: "KG 11 Ave, House 24",
      delivery_instructions: null,
    });
  });
});

describe("small helpers", () => {
  it("reads the step from the URL, defaulting to the first", () => {
    expect(checkoutStep("review")).toBe("review");
    expect(checkoutStep(["payment"])).toBe("payment");
    expect(checkoutStep("pay")).toBe("contact");
    expect(checkoutStep(null)).toBe("contact");
  });
  it("splits a full name for the form", () => {
    expect(splitName("Aline Uwase Mukamana")).toEqual({ firstName: "Aline", lastName: "Uwase Mukamana" });
    expect(splitName(null)).toEqual({ firstName: "", lastName: "" });
  });
  it("accepts only order-number shaped URL segments", () => {
    expect(orderNumber("ord-261027-abc123")).toBe("ORD-261027-ABC123");
    expect(orderNumber("..%2Fadmin")).toBeNull();
    expect(orderNumber("x")).toBeNull();
  });
  it("counts down to the hold's end", () => {
    const now = Date.parse("2026-10-27T10:00:00Z");
    expect(secondsLeft("2026-10-27T10:04:32Z", now)).toBe(272);
    expect(secondsLeft("2026-10-27T09:00:00Z", now)).toBe(0);
    expect(secondsLeft(null, now)).toBe(0);
    expect(countdown(272)).toBe("04:32");
    expect(countdown(3600 * 23 + 61)).toBe("23:01:01");
  });
});

describe("order access for this tab", () => {
  afterEach(() => sessionStorage.clear());
  it("remembers the phone of a placed order, newest first, at most five", () => {
    for (let i = 1; i <= 6; i++) rememberOrder({ number: `ORD-261027-00000${i}`, phone: "0788000111" });
    expect(orderAccess("ord-261027-000006")).toEqual({ number: "ORD-261027-000006", phone: "0788000111" });
    expect(orderAccess("ORD-261027-000001")).toBeNull();
  });
  it("ignores storage it cannot read", () => {
    sessionStorage.setItem("sixty_orders", "{broken");
    expect(orderAccess("ORD-1")).toBeNull();
  });
});
