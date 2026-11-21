import { describe, expect, it } from "vitest";
import { actionLabel, changeLine } from "./audit";
import { batches, splitItemError } from "./bulk-images";
import { categoryTree } from "./categories";
import { compactNumber, niceScale, percentChange, periodWindows, reportWindows, timeAgo } from "./dashboard";
import { numberSetting } from "./delivery";
import { reportCsv } from "./import";
import { availableTone, REASONS } from "./inventory";
import { activeNav, canOpen } from "./nav";
import { groupDigits, parseAmount } from "./numbers";
import { nextStatus, whatsappLink } from "./order-detail";
import { moveItem, rowsToObject, skuOk } from "./product-editor";
import { dayFromEnd, endFromDay, promotionPhase } from "./promotions";
import { roleHas, rolesFor } from "./roles";
import { bannerPhase, ctaPathOk, textSetting } from "./settings";
import { adminSearchTarget } from "./shell";
import { initials } from "./staff";
import { hasBothLanguages, lastUpdated } from "./pages";
import { dueIn, quoteUnits } from "./quotes";
import { socialChanges, socialNetworkOf, storeChanges, storeFieldOf, type SocialLinks, type StoreTexts } from "./store-settings";
import { socialLinkOk } from "@/components/ui/social-icons";

describe("access", () => {
  it("finds the nav item of a path, longest match first", () => {
    expect(activeNav("/admin")).toBe("dashboard");
    expect(activeNav("/admin/products/images")).toBe("bulkImages");
    expect(activeNav("/admin/products/123")).toBe("products");
    expect(activeNav("/admin/productsx")).toBeNull();
  });

  it("checks permissions and lists the roles for a page", () => {
    expect(canOpen(["orders:read"], ["orders:read"])).toBe(true);
    expect(canOpen(new Set(["catalog:read"]), ["orders:read"])).toBe(false);
    expect(roleHas("administrator", "audit:read")).toBe(true);
    expect(roleHas("sales", "audit:read")).toBe(false);
    expect(rolesFor(["audit:read"])).toEqual(["administrator", "finance"]);
    expect(rolesFor(["staff:read"])).toEqual(["administrator"]);
  });

});

describe("shell search", () => {
  it("sends order numbers and phones to orders, the rest to products", () => {
    expect(adminSearchTarget("  ")).toBeNull();
    expect(adminSearchTarget("ORD-261028-WTEYFV")).toBe("/admin/orders?q=ORD-261028-WTEYFV");
    expect(adminSearchTarget("0788 123 456")).toContain("/admin/orders?");
    expect(adminSearchTarget("galaxy a55")).toBe("/admin/products?q=galaxy+a55");
  });
});

describe("dashboard", () => {
  it("compares a period with the one before", () => {
    const now = Date.UTC(2026, 9, 28);
    const w = periodWindows(7, now);
    expect(w.current.to).toBe("2026-10-28T00:00:00.000Z");
    expect(w.current.from).toBe("2026-10-21T00:00:00.000Z");
    expect(w.previous).toEqual({ from: "2026-10-14T00:00:00.000Z", to: "2026-10-21T00:00:00.000Z" });
    expect(percentChange(12, 10)).toBe(20);
    expect(percentChange(5, 0)).toBeNull();
  });

  it("asks the reports for whole Kigali days", () => {
    // 23:30 UTC is already the next day in Kigali (UTC+2).
    const now = Date.UTC(2026, 9, 28, 23, 30);
    expect(reportWindows(7, now)).toEqual({
      current: { from: "2026-10-23", to: "2026-10-29" },
      previous: { from: "2026-10-16", to: "2026-10-22" },
    });
  });

  it("rounds the chart axis and labels", () => {
    expect(niceScale(0)).toEqual({ top: 4, step: 1 });
    expect(niceScale(6_450_000)).toEqual({ top: 8_000_000, step: 2_000_000 });
    expect(niceScale(9)).toEqual({ top: 10, step: 2.5 });
    expect(compactNumber(6_450_000)).toBe("6.5M");
    expect(compactNumber(0)).toBe("0");
  });

  it("says how long ago an order came in", () => {
    const now = Date.UTC(2026, 9, 28, 12);
    expect(timeAgo(new Date(now - 20_000).toISOString(), now)).toBe("this minute");
    expect(timeAgo(new Date(now - 2 * 60_000).toISOString(), now)).toBe("2 min. ago");
    expect(timeAgo(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe("3 hr. ago");
    expect(timeAgo(new Date(now - 86_400_000).toISOString(), now)).toBe("yesterday");
  });
});

describe("orders", () => {
  it("knows the forward step and the WhatsApp link", () => {
    expect(nextStatus("received")).toBe("confirmed");
    expect(nextStatus("dispatched")).toBe("delivered");
    expect(nextStatus("delivered")).toBeNull();
    expect(nextStatus("cancelled")).toBeNull();
    expect(whatsappLink("+250 788 123 456")).toBe("https://wa.me/250788123456");
  });
});

describe("amounts", () => {
  it("reads and writes whole RWF", () => {
    expect(parseAmount("520,000")).toBe(520000);
    expect(parseAmount(" 520 000 ")).toBe(520000);
    expect(parseAmount("12.5")).toBeNull();
    expect(parseAmount("-5")).toBeNull();
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("1000000000000")).toBeNull();
    expect(groupDigits(520000)).toBe("520,000");
    expect(parseAmount(groupDigits(999_999_999_999))).toBe(999_999_999_999);
  });
});

describe("product editor", () => {
  it("checks SKUs like the backend", () => {
    expect(skuOk("SAM-A55-256")).toBe(true);
    expect(skuOk("")).toBe(false);
    expect(skuOk("A B")).toBe(false);
    expect(skuOk("A/B")).toBe(false);
    expect(skuOk("A__B")).toBe(false);
    expect(skuOk("x".repeat(81))).toBe(false);
  });

  it("turns rows into an object and moves items", () => {
    expect(
      rowsToObject([
        { key: " RAM ", value: " 8 GB " },
        { key: "", value: "x" },
        { key: "Colour", value: " " },
      ]),
    ).toEqual({ RAM: "8 GB" });
    expect(moveItem(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
    expect(moveItem(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(moveItem(["a", "b", "c"], 1, 9)).toEqual(["a", "c", "b"]);
  });
});

describe("bulk photos", () => {
  it("batches files by 20 and reads item errors", () => {
    const files = Array.from({ length: 45 }, (_, i) => i);
    expect(batches(files).map((b) => b.length)).toEqual([20, 20, 5]);
    expect(batches([])).toEqual([]);
    expect(splitItemError("unknown_slug: No product has the slug x.\nTry again")).toEqual({ code: "unknown_slug", message: "No product has the slug x.\nTry again" });
    expect(splitItemError("Something broke")).toEqual({ code: null, message: "Something broke" });
    expect(splitItemError(null)).toEqual({ code: null, message: null });
  });
});

describe("inventory", () => {
  it("colours the left badge and maps reasons to the backend's", () => {
    expect(availableTone({ available_quantity: 0, is_low_stock: true })).toBe("soft-err");
    expect(availableTone({ available_quantity: 2, is_low_stock: true })).toBe("soft-warn");
    expect(availableTone({ available_quantity: 20, is_low_stock: false })).toBe("soft-ok");
    expect(REASONS.add.map((r) => r.reason)).toEqual(["receipt", "inspected_return", "adjustment"]);
    expect(REASONS.remove.every((r) => r.reason === "adjustment")).toBe(true);
  });
});

describe("categories", () => {
  it("orders the tree by sort order and name, children under parents", () => {
    const tree = categoryTree([
      { id: "c", parent_id: "a", sort_order: 0, name: "Cases" },
      { id: "b", parent_id: null, sort_order: 1, name: "Laptops" },
      { id: "a", parent_id: null, sort_order: 0, name: "Phones" },
      { id: "o", parent_id: "missing", sort_order: 5, name: "Orphan" },
    ]);
    expect(tree.map((n) => [n.item.id, n.level, n.hasChildren])).toEqual([
      ["a", 0, true],
      ["c", 1, false],
      ["b", 0, false],
      ["o", 0, false],
    ]);
  });
});

describe("import report", () => {
  it("quotes cells and defuses spreadsheet formulas", () => {
    const csv = reportCsv([{ kind: "Error", row: 3, field: "price", message: '=HYPERLINK("x") "bad"' }], ["Kind", "Row", "Field", "Problem"]);
    expect(csv.split("\r\n")).toEqual(['"Kind","Row","Field","Problem"', '"Error","3","price","\'=HYPERLINK(""x"") ""bad"""']);
  });
});

describe("settings", () => {
  it("reads settings by type", () => {
    const items = [
      { key: "delivery.free_delivery_threshold", value: 50000 },
      { key: "seller.tin", value: null },
      { key: "seller.legal_name", value: "3 Sixty Ltd" },
    ];
    expect(numberSetting(items, "delivery.free_delivery_threshold")).toBe(50000);
    expect(numberSetting(items, "seller.tin")).toBeNull();
    expect(textSetting(items as never, "seller.legal_name")).toBe("3 Sixty Ltd");
    expect(textSetting(items as never, "seller.tin")).toBe("");
  });

  it("only allows banner links on this site", () => {
    expect(ctaPathOk("/category/phones")).toBe(true);
    expect(ctaPathOk("/search?q=tv&page=2")).toBe(true);
    expect(ctaPathOk("//evil.example")).toBe(false);
    expect(ctaPathOk("https://evil.example")).toBe(false);
    expect(ctaPathOk("/a//b")).toBe(false);
    expect(ctaPathOk("/a b")).toBe(false);
    expect(ctaPathOk("/\\evil")).toBe(false);
    expect(ctaPathOk(`/${"a".repeat(200)}`)).toBe(false);
  });

  it("says where a banner stands", () => {
    const now = Date.parse("2026-10-28T12:00:00Z");
    const base = { is_active: true, shown_now: false, starts_at: null, ends_at: null };
    expect(bannerPhase({ ...base, shown_now: true }, now)).toBe("live");
    expect(bannerPhase({ ...base, is_active: false }, now)).toBe("hidden");
    expect(bannerPhase({ ...base, ends_at: "2026-10-01T00:00:00+02:00" }, now)).toBe("ended");
    expect(bannerPhase({ ...base, starts_at: "2026-11-01T00:00:00+02:00" }, now)).toBe("scheduled");
  });
});

describe("promotions", () => {
  it("classifies promotions by status and dates", () => {
    const now = Date.parse("2026-10-28T12:00:00Z");
    expect(promotionPhase({ status: "draft", starts_at: null, ends_at: null }, now)).toBe("off");
    expect(promotionPhase({ status: "disabled", starts_at: null, ends_at: null }, now)).toBe("off");
    expect(promotionPhase({ status: "active", starts_at: null, ends_at: null }, now)).toBe("active");
    expect(promotionPhase({ status: "active", starts_at: "2026-11-01T00:00:00+02:00", ends_at: null }, now)).toBe("scheduled");
    expect(promotionPhase({ status: "active", starts_at: null, ends_at: "2026-10-28T00:00:00+02:00" }, now)).toBe("expired");
  });

  it("turns the last valid day into the API's exclusive end and back", () => {
    expect(endFromDay("2026-11-30")).toBe("2026-12-01T00:00:00");
    expect(endFromDay("2026-12-31")).toBe("2027-01-01T00:00:00");
    expect(dayFromEnd("2026-12-01T00:00:00+02:00")).toBe("2026-11-30");
  });
});

describe("staff and audit", () => {
  it("makes avatar initials", () => {
    expect(initials("Jean Paul Habimana")).toBe("JP");
    expect(initials("admin@gmail.com")).toBe("A");
    expect(initials(null)).toBe("");
  });

  it("reads audit changes in one line", () => {
    expect(changeLine({ status: "success", changes: { status: { from: "draft", to: "active" } } })).toBe("status: draft → active");
    expect(changeLine({ from_status: "received", to_status: "cancelled", reason: "payment_timeout" })).toBe("received → cancelled");
    expect(changeLine({ from: "mtn_momo", to: "cash_on_delivery", ip_address: "::1" })).toBe("mtn_momo → cash_on_delivery");
    expect(changeLine({ on_hand_before: 1, on_hand_after: 0, reason: "adjustment" })).toBe("1 → 0 (adjustment)");
    expect(changeLine({ status: "success", ip_address: "::1", user_agent: "node", role: "finance" })).toBe("role: finance");
    expect(changeLine({ note: "x".repeat(300) }, 20)).toHaveLength(20);
    expect(actionLabel("catalog.product_update")).toBe("Product update");
    expect(actionLabel("user.profile.update")).toBe("Profile update");
    expect(actionLabel("login")).toBe("Login");
  });
});

describe("module 19 content", () => {
  const empty: StoreTexts = { name: "", phone: "", whatsapp: "", email: "", address: "", hours: "", announceEn: "", announceRw: "" };

  it("opens quote requests for administrators and sales only", () => {
    expect(activeNav("/admin/quotes")).toBe("quotes");
    expect(rolesFor(["quotes:manage"])).toEqual(["administrator", "sales"]);
  });

  it("sends only the changed store settings, in the backend's form", () => {
    const { errors, body } = storeChanges({ ...empty, phone: " +250 788 123 456 ", email: "Info@3SixtyTech.rw" }, empty, false, false);
    expect(errors).toEqual({});
    expect(body).toEqual({ "contact.phone": "+250 788 123 456", "contact.email": "info@3sixtytech.rw" });
  });

  it("checks store settings like the backend", () => {
    const before = { ...empty, name: "3 Sixty Technologies" };
    const { errors } = storeChanges({ ...before, name: "", phone: "0788123456", whatsapp: "+250 788 123 456", hours: "x" }, before, false, false);
    expect(errors).toEqual({ name: "required", phone: "phone", hours: "tooShort" });
  });

  it("switches the announcement on only with both texts", () => {
    expect(storeChanges({ ...empty, announceEn: "Free delivery" }, empty, true, false).errors).toEqual({ announceRw: "announcement" });
    const both = { ...empty, announceEn: "Free delivery", announceRw: "Kugeza ku buntu" };
    expect(storeChanges(both, both, true, false).body).toEqual({ "announcement.enabled": true });
    expect(storeChanges(both, both, false, true).body).toEqual({ "announcement.enabled": false });
    expect(storeFieldOf("announcement.text_rw")).toBe("announceRw");
  });

  it("summarises pages and quote requests", () => {
    const v = (updated_at: string, is_published = true) => ({ title: "T", body: "B", is_published, updated_at, updated_by_user_id: null });
    expect(lastUpdated({ en: v("2026-09-01T00:00:00Z"), rw: v("2026-10-02T00:00:00Z") })).toBe("2026-10-02T00:00:00Z");
    expect(lastUpdated({ en: null, rw: null })).toBeNull();
    expect(hasBothLanguages({ en: v("2026-09-01T00:00:00Z"), rw: v("2026-09-01T00:00:00Z", false) })).toBe(false);
    expect(quoteUnits([{ quantity: 25 }, { quantity: 5 }])).toBe(30);
  });

  it("tells how soon a quote request is needed, in Kigali days", () => {
    const now = new Date("2026-11-11T22:30:00Z"); // 12 Nov, 00:30 in Kigali
    expect(dueIn("2026-11-11", now)).toEqual({ kind: "passed", days: -1 });
    expect(dueIn("2026-11-12", now)).toEqual({ kind: "today", days: 0 });
    expect(dueIn("2026-11-13", now).kind).toBe("tomorrow");
    expect(dueIn("2026-11-19", now)).toEqual({ kind: "soon", days: 7 });
    expect(dueIn("2026-11-20", now).kind).toBe("later");
  });
});

describe("social media links (owner, 2026-11-18)", () => {
  const none: SocialLinks = { facebook: "", instagram: "", x: "", youtube: "", tiktok: "", linkedin: "" };

  it("accepts full https links on each network's own site only", () => {
    expect(socialLinkOk("facebook", "https://www.facebook.com/3sixtytech")).toBe(true);
    expect(socialLinkOk("x", "https://twitter.com/3sixtytech")).toBe(true);
    expect(socialLinkOk("youtube", "https://youtu.be/abc")).toBe(true);
    expect(socialLinkOk("facebook", "http://facebook.com/3sixtytech")).toBe(false);
    expect(socialLinkOk("facebook", "facebook.com/3sixtytech")).toBe(false);
    expect(socialLinkOk("facebook", "https://facebook.com.evil.example/x")).toBe(false);
    expect(socialLinkOk("instagram", "https://facebook.com/3sixtytech")).toBe(false);
    expect(socialLinkOk("x", "https://user:pass@x.com/a")).toBe(false);
    expect(socialLinkOk("tiktok", "https://www.tiktok.com/@3sixty tech")).toBe(false);
  });

  it("sends only the changed links, an emptied one as \"\" so its icon leaves the footer", () => {
    const before = { ...none, facebook: "https://facebook.com/old", x: "https://x.com/3sixtytech" };
    const { errors, body } = socialChanges({ ...before, facebook: " https://www.facebook.com/3sixtytech ", x: "  ", youtube: "youtube.com/@3sixty" }, before);
    expect(errors).toEqual(["youtube"]);
    expect(body).toEqual({ "social.facebook": "https://www.facebook.com/3sixtytech", "social.x": "" });
    expect(socialChanges(before, before).body).toEqual({});
    expect(socialNetworkOf("social.linkedin")).toBe("linkedin");
    expect(socialNetworkOf("contact.phone")).toBeUndefined();
  });
});
