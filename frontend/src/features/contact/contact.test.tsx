import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RichText } from "@/components/store/rich-text";
import { telHref, whatsappHref } from "@/lib/contact";
import { infoPageKey } from "@/lib/info-pages";
import { emptyLine, kigaliDay, serverErrors, validateLine, validateQuote, type QuoteForm } from "./quote";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

const NOW = new Date("2026-10-29T10:00:00Z");
const FORM: QuoteForm = {
  company: "Green Hills Academy",
  contactName: "Aline Uwase",
  phone: "788 123 456",
  email: "",
  lines: [{ product: "HP ProBook 450", quantity: "25" }, emptyLine()],
  deliveryLocation: "",
  neededBy: "",
  message: "",
};

describe("contact links", () => {
  it("builds WhatsApp and phone links from international numbers", () => {
    expect(whatsappHref("+250 788 123 456")).toBe("https://wa.me/250788123456");
    expect(whatsappHref("+250 788 123 456", "Hello & bye")).toBe("https://wa.me/250788123456?text=Hello%20%26%20bye");
    expect(telHref("+250 788 123 456")).toBe("tel:+250788123456");
  });

  it("knows the six policy pages by slug", () => {
    expect(infoPageKey("delivery-information")).toBe("delivery");
    expect(infoPageKey("terms-and-conditions")).toBe("terms");
    expect(infoPageKey("unknown")).toBeNull();
  });
});

describe("quote request", () => {
  it("gives Kigali's date, also just before midnight UTC", () => {
    expect(kigaliDay(NOW)).toBe("2026-10-29");
    expect(kigaliDay(new Date("2026-10-29T22:30:00Z"))).toBe("2026-10-30");
    expect(kigaliDay(NOW, 366)).toBe("2027-10-30");
  });

  it("sends a valid form without its empty rows", () => {
    const { errors, body, rowIndex } = validateQuote(FORM, "rw", NOW);
    expect(errors).toEqual({});
    expect(rowIndex).toEqual([0]);
    expect(body).toEqual({
      company: "Green Hills Academy",
      contact_name: "Aline Uwase",
      phone: "0788123456",
      email: null,
      lines: [{ product: "HP ProBook 450", quantity: 25 }],
      delivery_location: null,
      needed_by: null,
      message: null,
      locale: "rw",
    });
  });

  it("points at each mistake", () => {
    const { errors, body } = validateQuote(
      {
        ...FORM,
        company: "G",
        contactName: "",
        phone: "12345",
        email: "not-an-email",
        lines: [emptyLine(), { product: "", quantity: "3" }, { product: "Router", quantity: "0" }],
        neededBy: "2026-10-28",
      },
      "en",
      NOW,
    );
    expect(body).toBeNull();
    expect(errors).toEqual({
      company: "tooShort",
      contactName: "required",
      phone: "phoneInvalid",
      email: "emailInvalid",
      rows: { 1: { product: "productRequired" }, 2: { quantity: "quantityInvalid" } },
      neededBy: "neededByInvalid",
    });
  });

  it("needs at least one product", () => {
    expect(validateQuote({ ...FORM, lines: [emptyLine()] }, "en", NOW).errors).toEqual({ lines: "linesRequired" });
    expect(validateQuote({ ...FORM, lines: [{ product: "Laptop", quantity: "1.5" }] }, "en", NOW).errors.rows).toEqual({ 0: { quantity: "quantityInvalid" } });
  });

  it("checks one product from the Add a product popup", () => {
    expect(validateLine({ product: "  HP ProBook 450 ", quantity: "25" })).toEqual({ line: { product: "HP ProBook 450", quantity: 25 }, errors: {} });
    expect(validateLine(emptyLine())).toEqual({ line: null, errors: { product: "productRequired", quantity: "quantityRequired" } });
    expect(validateLine({ product: "Router", quantity: "0" }).errors).toEqual({ quantity: "quantityInvalid" });
    expect(validateLine({ product: "Router", quantity: "100001" }).errors).toEqual({ quantity: "quantityInvalid" });
  });

  it("maps the backend's 422 details back onto the form rows", () => {
    const errors = serverErrors(
      [
        { loc: ["body", "phone"], msg: "bad" },
        { loc: ["body", "lines", 0, "quantity"], msg: "bad" },
        { loc: ["body", "unknown"], msg: "bad" },
      ],
      [2],
    );
    expect(errors).toEqual({ phone: "invalid", rows: { 2: { quantity: "quantityInvalid" } } });
    expect(serverErrors("nope", [])).toEqual({});
  });
});

describe("policy page text", () => {
  it("draws Markdown without raw HTML, images or unsafe links", () => {
    const { container } = render(
      <RichText
        markdown={[
          "Lead text.",
          "",
          "## Zones",
          "",
          "- Kigali",
          "",
          "| Zone | Fee |",
          "| --- | --- |",
          "| Kigali | 2,000 |",
          "",
          '<script>alert("x")</script><b>bold</b>',
          "",
          "![photo](https://example.com/a.png)",
          "",
          "[contact](/contact) [site](https://example.com) [bad](javascript:alert(1))",
        ].join("\n")}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Zones" })).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
    expect(container.querySelector("script, b, img")).toBeNull();
    expect(screen.getByRole("link", { name: "contact" }).getAttribute("href")).toBe("/contact");
    expect(screen.getByRole("link", { name: "site" }).getAttribute("target")).toBe("_blank");
    expect(screen.queryByRole("link", { name: "bad" })?.getAttribute("href") ?? "").not.toContain("javascript");
  });
});
