import { expect, test } from "@playwright/test";
import { expectAccessible, screenshot } from "./helpers";

test("component gallery matches the style guide sections and is accessible", async ({ page }, testInfo) => {
  await page.goto("/dev/ui");
  await expect(page.getByRole("heading", { level: 1, name: "3 Sixty Technologies UI" })).toBeVisible();
  for (const name of ["Colours and where they go", "Type scale — Inter", "Buttons", "Status badges", "Form fields", "Icons & spacing"]) {
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  await expectAccessible(page);
  await screenshot(page, testInfo, "dev-ui");
});

test("dialog, drawer and toast open, trap focus and close with Escape", async ({ page }, testInfo) => {
  await page.goto("/dev/ui");
  await page.getByRole("button", { name: "Open dialog" }).click();
  const dialog = page.getByRole("dialog", { name: "Adjust stock" });
  await expect(dialog).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "dev-ui-dialog");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();

  await page.getByRole("button", { name: "Open drawer" }).click();
  const drawer = page.getByRole("dialog", { name: "Added to your cart" });
  await expect(drawer).toBeVisible();
  await screenshot(page, testInfo, "dev-ui-drawer");
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toBeHidden();

  await page.getByRole("button", { name: "Show toast" }).click();
  await expect(page.getByRole("status")).toContainText("Saved");
});

test("storefront home in English and Kinyarwanda, and the admin placeholder", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Furniture for Every Room, From Stores You Trust");
  await expectAccessible(page);

  await page.goto("/rw");
  await expect(page.locator("html")).toHaveAttribute("lang", "rw");
  await expectAccessible(page);

  await page.goto("/admin");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expectAccessible(page);
});

test("the backend proxy refuses other sites and keeps tokens out of the page", async ({ request }) => {
  const foreign = await request.post("/api/backend/api/v1/cart/items", {
    headers: { origin: "https://evil.example" },
    data: {},
  });
  expect(foreign.status()).toBe(403);
  expect((await request.get("/api/backend/api/v1/auth/login")).status()).toBe(404);
  const health = await request.get("/api/backend/api/v1/health");
  expect(health.status()).toBe(200);
  expect(await health.json()).toMatchObject({ status: "ok" });
});
