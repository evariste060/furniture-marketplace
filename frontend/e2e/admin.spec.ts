import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, screenshot } from "./helpers";

/** Frontend phase 6: every admin screen opens for an administrator (axe and screenshots). SC-05: the
 * Marketplace Administrator is the only staff role. Read-only: nothing is saved, so the dev data
 * stays as it is. Needs the seed administrator in the dev database and its password in
 * E2E_STAFF_PASSWORD; the tests are skipped without it. */

const PASSWORD = process.env.E2E_STAFF_PASSWORD;
const ACCOUNTS = {
  administrator: process.env.E2E_ADMIN_EMAIL ?? "admin@seed.3sixty.local",
} as const;

test.skip(!PASSWORD, "Set E2E_STAFF_PASSWORD to the seed staff password to run the admin tests.");

async function signIn(page: Page, role: keyof typeof ACCOUNTS) {
  const origin = new URL(test.info().project.use.baseURL ?? "http://localhost:3100").origin;
  const response = await page.request.post("/api/auth/login", { data: { identifier: ACCOUNTS[role], password: PASSWORD }, headers: { Origin: origin } });
  expect(response.ok(), `sign-in as ${ACCOUNTS[role]} failed with ${response.status()}`).toBeTruthy();
}

/** Waits until lists and tiles have their data: nothing busy and no "…" or "(…)" count. */
async function settled(page: Page) {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 30_000 });
  // The pagination gap "…" is decorative (aria-hidden) and stays.
  await expect(page.getByText(/^…$|\(…\)/).and(page.locator(':not([aria-hidden="true"])'))).toHaveCount(0, { timeout: 30_000 });
}

async function open(page: Page, path: string, heading: string | RegExp) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible({ timeout: 30_000 });
  await settled(page);
}

test("a signed-out visitor is sent to sign in", async ({ page }) => {
  await page.goto("/admin/orders");
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fadmin/);
});

test("an administrator opens every admin screen", async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  await signIn(page, "administrator");

  const screens: [string, string | RegExp, string][] = [
    ["/admin", /^Good (morning|afternoon|evening), /, "admin-dashboard"],
    ["/admin/orders", "Orders", "admin-orders"],
    ["/admin/payments", "Payments", "admin-payments"],
    ["/admin/quotes", "Quote requests", "admin-quotes"],
    ["/admin/products", "Products", "admin-products"],
    ["/admin/products/images", "Product photos", "admin-bulk-images"],
    ["/admin/categories", "Categories & brands", "admin-categories"],
    ["/admin/import", "Catalogue import", "admin-import"],
    ["/admin/inventory", "Inventory", "admin-inventory"],
    ["/admin/reviews", "Reviews", "admin-reviews"],
    ["/admin/delivery", "Delivery zones", "admin-delivery"],
    ["/admin/promotions", "Promotions", "admin-promotions"],
    ["/admin/staff", "Staff & roles", "admin-staff"],
    ["/admin/settings", "Settings & pages", "admin-settings"],
    ["/admin/settings?tab=banners", "Settings & pages", "admin-banners"],
    ["/admin/settings?tab=pages&page=delivery-information", "Settings & pages", "admin-pages"],
    ["/admin/audit", "Audit log", "admin-audit"],
  ];
  for (const [path, heading, name] of screens) {
    await test.step(path, async () => {
      await open(page, path, heading);
      await expectAccessible(page);
      await screenshot(page, testInfo, name);
    });
  }

  await test.step("order detail", async () => {
    await open(page, "/admin/orders", "Orders");
    await page.getByRole("link", { name: /^ORD-/ }).filter({ visible: true }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: /^Order #ORD-/ })).toBeVisible({ timeout: 30_000 });
    await settled(page);
    await expectAccessible(page);
    await screenshot(page, testInfo, "admin-order-detail");
  });

  await test.step("product editor", async () => {
    await open(page, "/admin/products", "Products");
    await page.getByRole("link", { name: /^Edit / }).filter({ visible: true }).first().click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
    await expect(page).toHaveURL(/\/admin\/products\/[0-9a-f-]{36}$/);
    await settled(page);
    await expectAccessible(page);
    await screenshot(page, testInfo, "admin-product-editor");
  });

  await test.step("unknown admin address", async () => {
    await page.goto("/admin/no-such-page");
    await expect(page.getByRole("heading", { level: 1, name: "We can’t find that page" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: "Back to dashboard" })).toBeVisible();
    await expectAccessible(page);
  });

  await test.step("adjust stock dialog (closed without saving)", async () => {
    await open(page, "/admin/inventory?view=all", "Inventory");
    await page.getByRole("button", { name: /^Adjust stock of / }).filter({ visible: true }).first().click();
    const dialog = page.getByRole("dialog", { name: "Adjust stock" });
    await expect(dialog).toBeVisible();
    await expectAccessible(page);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });
});

test("every staff member is a Marketplace Administrator, with no role filter or picker", async ({ page }) => {
  await signIn(page, "administrator");
  await open(page, "/admin/staff", "Staff & roles");
  await expect(page.getByRole("group", { name: "Filter by role" })).toHaveCount(0);
  await expect(page.getByText("Marketplace Administrator").first()).toBeVisible();
  await page.getByRole("button", { name: "Add staff member" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("combobox", { name: "Role" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Cancel" }).click();
});
