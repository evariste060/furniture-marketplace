import { describe, expect, it } from "vitest";
import { inboxTime, messageDay } from "@/features/admin/messages";
import { bodyError, serverErrors, stepOf, supportKey, supportReference, validateStep, validateSupport, type SupportForm } from "./support";

const FORM: SupportForm = { topic: "order", name: " Aline Uwase ", phone: "788 123 456", email: "", subject: "Delivery to Musanze", orderNumber: " ORD-1 ", body: " When will it arrive? " };
const EMPTY: SupportForm = { topic: "", name: "", phone: "", email: "", subject: "", orderNumber: "", body: "" };

describe("support messages", () => {
  it("builds the request body, trimmed, with a local phone", () => {
    const { errors, body } = validateSupport(FORM, "rw");
    expect(errors).toEqual({});
    expect(body).toEqual({ topic: "order", name: "Aline Uwase", phone: "0788123456", email: null, subject: "Delivery to Musanze", order_number: "ORD-1", body: "When will it arrive?", locale: "rw" });
  });

  it("sends an order number only for topics about an order", () => {
    expect(validateSupport({ ...FORM, topic: "product" }, "en").body?.order_number).toBeNull();
    expect(validateSupport({ ...FORM, topic: "returns" }, "en").body?.order_number).toBe("ORD-1");
  });

  it("checks one step at a time", () => {
    expect(validateStep("topic", EMPTY)).toEqual({ topic: "topicRequired" });
    expect(validateStep("details", EMPTY)).toEqual({ subject: "required", body: "required" });
    expect(validateStep("contact", EMPTY)).toEqual({ name: "required", contact: "contactRequired" });
    expect(validateStep("review", EMPTY)).toEqual({});
    expect(validateStep("details", FORM)).toEqual({});
  });

  it("sends the visitor back to the first step with a mistake", () => {
    expect(stepOf({ name: "required", subject: "required" })).toBe("details");
    expect(stepOf({ contact: "contactRequired" })).toBe("contact");
    expect(stepOf({})).toBeNull();
  });

  it("needs a phone or an email", () => {
    expect(validateSupport({ ...FORM, phone: "" }, "en").errors).toEqual({ contact: "contactRequired" });
    expect(validateSupport({ ...FORM, phone: "", email: "aline@example.rw" }, "en").body?.email).toBe("aline@example.rw");
  });

  it("checks each field like the backend", () => {
    const { errors, body } = validateSupport({ topic: "", name: "A", phone: "0123", email: "nope", subject: "Hi", orderNumber: "x".repeat(33), body: "" }, "en");
    expect(body).toBeNull();
    expect(errors).toEqual({ topic: "topicRequired", name: "tooShort", phone: "phoneInvalid", email: "emailInvalid", subject: "tooShort", orderNumber: "tooLong", body: "required" });
    expect(bodyError("x".repeat(2001))).toBe("tooLong");
    expect(bodyError(" ok ")).toBeUndefined();
  });

  it("maps the backend's 422 details onto the fields", () => {
    expect(serverErrors([{ loc: ["body", "order_number"] }, { loc: ["body"] }, { loc: ["body", "topic"] }])).toEqual({ orderNumber: "invalid", contact: "contactRequired", topic: "invalid" });
    expect(serverErrors(null)).toEqual({});
  });

  it("reads a conversation's reference and private key from the URL", () => {
    expect(supportReference("m-261111-abcdef")).toBe("M-261111-ABCDEF");
    expect(supportReference("ORD-261111-ABCDEF")).toBeNull();
    expect(supportReference("%E0%A4%A")).toBeNull();
    expect(supportKey("aZ09_-".repeat(5) + "ab")).toHaveLength(32);
    expect(supportKey("short")).toBeNull();
    expect(supportKey("a".repeat(31) + "/")).toBeNull();
  });

  it("dates inbox rows as a time today, yesterday or a day", () => {
    const now = new Date("2026-11-11T10:00:00Z"); // 12:00 in Kigali
    expect(inboxTime("2026-11-11T07:05:00Z", now)).toEqual({ label: "09:05", kind: "time" });
    expect(inboxTime("2026-11-10T20:00:00Z", now).kind).toBe("yesterday");
    expect(inboxTime("2026-11-02T08:00:00Z", now)).toEqual({ label: "2 Nov", kind: "date" });
  });

  it("heads each day of a conversation as today, yesterday or its date", () => {
    const now = new Date("2026-11-11T10:00:00Z");
    expect(messageDay("2026-11-10T22:30:00Z", now).kind).toBe("today"); // 00:30 in Kigali
    expect(messageDay("2026-11-10T08:00:00Z", now).kind).toBe("yesterday");
    expect(messageDay("2026-11-02T08:00:00Z", now).kind).toBe("date");
  });
});
