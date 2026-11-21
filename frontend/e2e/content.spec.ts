import { expect, test } from "@playwright/test";
import { expectAccessible, screenshot } from "./helpers";

/** Module 19: the Contact page with its business quote form, and the policy pages
 * (Contact.dc.html, Policy.dc.html). Needs the store contact and the draft pages from the
 * development seed. Sending a quote request adds one row to the dev database. */

test("the policy pages show the seeded text in both languages", async ({ page }, testInfo) => {
  await page.goto("/pages/delivery-information");
  await expect(page.getByRole("heading", { level: 1, name: "Delivery information" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Help topics" });
  await expect(nav.getByRole("link", { name: "Delivery information" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("main").getByRole("table")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "policy");

  await page.getByRole("link", { name: "Soma mu Kinyarwanda" }).click();
  await expect(page).toHaveURL(/\/rw\/pages\/delivery-information$/);
  await expect(page.getByRole("link", { name: "Read in English" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "policy-rw");

  // Like a missing product, the page streams before the lookup fails: not found, marked noindex.
  await page.goto("/pages/no-such-page");
  await expect(page.getByRole("heading", { level: 1, name: "We can’t find that page" })).toBeVisible();
});

test("the bulk orders page checks the quote form and sends it", async ({ page }, testInfo) => {
  await page.goto("/contact");
  await expect(page.getByRole("heading", { level: 1, name: "Talk to us" })).toBeVisible();
  await expect(page.getByRole("form", { name: "Get help from our team" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "contact");

  await page.getByRole("link", { name: /Buying in bulk\?/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Business & bulk orders" })).toBeVisible();
  await expect(page.getByRole("link", { name: /^WhatsApp/ }).first()).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "bulk-orders");

  const form = page.getByRole("form", { name: "Request a business quote" });
  await form.getByRole("button", { name: "Send quote request" }).click();
  await expect(form.getByLabel("Company / institution")).toHaveAttribute("aria-invalid", "true");
  await expect(form.getByLabel("Company / institution")).toBeFocused();
  await expect(form.getByText("Add at least one product and its quantity.")).toBeVisible();
  await expect(form.getByText("No products added yet.")).toBeVisible();
  await expectAccessible(page);

  // Products are added in a popup, checked there, listed with their quantities and removable.
  const addProduct = async (product: string, quantity: string) => {
    await form.getByRole("button", { name: "Add a product" }).click();
    const popup = page.getByRole("dialog", { name: "Add a product" });
    await expect(popup).toBeVisible();
    await popup.getByLabel("Product name or model").fill(product);
    await popup.getByLabel("Quantity").fill(quantity);
    await popup.getByRole("button", { name: "Add product" }).click();
    await expect(popup).toBeHidden();
  };
  await form.getByRole("button", { name: "Add a product" }).click();
  const popup = page.getByRole("dialog", { name: "Add a product" });
  await popup.getByRole("button", { name: "Add product" }).click();
  await expect(popup.getByText("Write the product name or model.")).toBeVisible();
  await expect(popup.getByText("Enter a quantity.")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "contact-add-product");
  await popup.getByRole("button", { name: "Cancel" }).click();
  await expect(popup).toBeHidden();
  await addProduct("HP ProBook 450 G10", "12");
  await addProduct("TP-Link Archer router", "3");
  await expect(form.getByRole("listitem")).toHaveCount(2);
  await expect(form.getByRole("listitem").first()).toContainText("HP ProBook 450 G10");
  await expect(form.getByRole("listitem").first()).toContainText("Qty: 12");
  await form.getByRole("button", { name: "Remove TP-Link Archer router" }).click();
  await expect(form.getByRole("listitem")).toHaveCount(1);
  await expect(form.getByText("Add at least one product and its quantity.")).toHaveCount(0);

  // A different number each run keeps the per-number limit (3 an hour) out of the way.
  const phone = `78${String(Date.now()).slice(-7)}`;
  await form.getByLabel("Company / institution").fill("E2E Test School");
  await form.getByLabel("Contact person").fill("E2E Tester");
  await form.getByLabel("Phone").fill(phone);
  await form.getByRole("button", { name: "Send quote request" }).click();
  await expect(form.getByRole("status")).toContainText("we’ve received your request");
  await expect(form.getByRole("status")).toContainText(/Your reference: Q-\d{6}-[A-Z0-9]{6}/);
  await expect(form.getByLabel("Company / institution")).toHaveValue("");
  await expect(form.getByText("No products added yet.")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "contact-sent");
});
