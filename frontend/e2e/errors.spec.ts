import { expect, test } from "@playwright/test";
import { expectAccessible, screenshot } from "./helpers";

/** Frontend phase 7: the not-found and error states (NotFound.dc.html, ServerError.dc.html). */

test("an unknown address shows the not-found page in the store frame, in both languages", async ({ page }, testInfo) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "We can’t find that page" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "not-found");

  const rw = await page.goto("/rw/no-such-page");
  expect(rw?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Ntitubonye iyi paji" })).toBeVisible();
  await expectAccessible(page);
});

test("a missing product shows the not-found page, and its search box searches", async ({ page }) => {
  await page.goto("/product/no-such-product-slug");
  await expect(page.getByRole("heading", { level: 1, name: "We can’t find that page" })).toBeVisible();
  const search = page.getByRole("main").getByRole("search");
  await search.getByRole("searchbox", { name: "Search products" }).fill("laptop");
  await search.getByRole("button", { name: "Search" }).click();
  await expect(page).toHaveURL(/\/search\?q=laptop$/);
});

test("the error page offers a retry and shows the error reference", async ({ page }, testInfo) => {
  // /dev/errors draws the error state that otherwise shows only when a page fails.
  await page.goto("/dev/errors");
  await expect(page.getByRole("heading", { level: 1, name: "Something went wrong on our side" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(page.getByText("Error reference: 1234567890")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "server-error");

  await page.goto("/dev/errors/admin");
  await expect(page.getByRole("heading", { level: 1, name: "Something went wrong on our side" })).toBeVisible();
  await expectAccessible(page);
});
