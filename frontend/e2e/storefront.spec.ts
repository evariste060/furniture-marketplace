import { expect, test } from "@playwright/test";
import { expectAccessible, screenshot } from "./helpers";

/** Frontend phase 2 against the dev API and its seed (5 categories, 12 brands, products on sale). */

const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const isMobile = (name: string) => name === "mobile";

test("home is built from the API, in English and Kinyarwanda", async ({ page, request }, testInfo) => {
  const categories = (await (await request.get(`${API}/api/v1/catalog/categories`)).json()) as Array<{ name: string; parent_id: string | null }>;
  await page.goto("/");
  await expect(page.locator("h1:visible")).toBeVisible();
  for (const c of categories.filter((c) => c.parent_id === null)) {
    await expect(page.getByRole("link", { name: c.name }).first()).toBeAttached();
  }
  await expect(page.getByRole("heading", { name: "Featured Products" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "New Arrivals" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "home");

  await page.goto("/rw");
  await expect(page.locator("html")).toHaveAttribute("lang", "rw");
  await expect(page.getByRole("heading", { name: "Ibicuruzwa byatoranyijwe" })).toBeVisible();
  await expectAccessible(page);
});

test("the hero showcase spotlights each category's best seller with its related products", async ({ page, request }, testInfo) => {
  const tree = (await (await request.get(`${API}/api/v1/catalog/categories`)).json()) as Array<{ name: string; slug: string; parent_id: string | null }>;
  const first = tree.filter((c) => c.parent_id === null)[0];
  const best = (await (
    await request.get(`${API}/api/v1/catalog/products?category=${first.slug}&size=6&sort_by=bestselling&sort_direction=desc`)
  ).json()) as { items: Array<{ name: string; slug: string }> };
  test.skip(best.items.length < 2, "needs products in the first category");

  await page.goto("/");
  const hero = page.getByRole("region", { name: "Product showcase", exact: true });
  // The pointer on the hero pauses the rotation, as for a shopper about to click.
  await hero.hover();
  await expect(hero.getByText(best.items[0].name, { exact: true })).toBeVisible();
  await expect(hero.getByText(`More in ${first.name}`)).toBeVisible();
  await expect(hero.getByRole("link", { name: new RegExp(best.items[1].name) })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "hero-showcase");

  // A related product's Add to Cart shows on hover (always on touch screens) and opens the mini cart.
  const tile = hero.getByRole("listitem").first();
  // The cards fly into place one a second (and again after the accessibility check, which turns
  // motion off and on): hover the first once it has landed.
  await expect.poll(() => tile.evaluate((li) => li.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length)).toBe(0);
  await tile.hover();
  await tile.getByRole("button", { name: new RegExp(`^Add to Cart: ${best.items[1].name}`) }).click();
  const drawer = page.getByRole("dialog", { name: "Added to your cart" });
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  await hero.hover();
  await hero.getByRole("link", { name: "Shop Now" }).click();
  await expect(page).toHaveURL(new RegExp(`/product/${best.items[0].slug}$`));
});

test("the header switches language on the same page",async ({ page }, testInfo) => {
  test.skip(isMobile(testInfo.project.name), "the mobile switch is in the menu (tested below)");
  await page.goto("/deals");
  await page.getByRole("button", { name: /Language: English/ }).click();
  await page.getByRole("link", { name: "Kinyarwanda", exact: true }).click();
  await expect(page).toHaveURL(/\/rw\/deals$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Poromosiyo");
});

test("the All Categories mega menu shows each category's best sellers on hover", async ({ page, request }, testInfo) => {
  test.skip(isMobile(testInfo.project.name), "phones use the menu drawer");
  const tree = (await (await request.get(`${API}/api/v1/catalog/categories`)).json()) as Array<{ name: string; slug: string; parent_id: string | null }>;
  const second = tree.filter((c) => c.parent_id === null)[1];
  const best = (await (
    await request.get(`${API}/api/v1/catalog/products?category=${second.slug}&size=6&sort_by=bestselling&sort_direction=desc`)
  ).json()) as { items: Array<{ name: string; slug: string }> };
  test.skip(!best.items.length, "needs products in the second category");

  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Categories" });
  await nav.getByRole("button", { name: "All Categories" }).hover();
  const menu = nav.getByRole("region", { name: "All Categories" });
  await expect(menu).toBeVisible();
  await menu.getByRole("link", { name: second.name, exact: true }).hover();
  const product = menu.getByRole("link", { name: best.items[0].name });
  await expect(product).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "mega-menu");

  await product.click();
  await expect(page).toHaveURL(new RegExp(`/product/${best.items[0].slug}$`));
  await expect(menu).toBeHidden();
});

test("the Brands dropdown opens a brand's page", async ({ page, request }, testInfo) => {
  test.skip(isMobile(testInfo.project.name), "phones use the menu drawer");
  const brands = (await (await request.get(`${API}/api/v1/catalog/brands`)).json()) as Array<{ name: string; slug: string }>;
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Categories" });
  await nav.getByRole("button", { name: "Brands" }).hover();
  const menu = nav.getByRole("region", { name: "Brands" });
  await expect(menu).toBeVisible();
  for (const b of brands) await expect(menu.getByRole("link", { name: new RegExp(`^${b.name}`) })).toBeVisible();
  await screenshot(page, testInfo, "brands-menu");
  await menu.getByRole("link", { name: new RegExp(`^${brands[0].name}`) }).click();
  await expect(page).toHaveURL(new RegExp(`/brand/${brands[0].slug}$`));
});

test("brands page lists the API's brands", async ({ page, request }, testInfo) => {
  const brands = (await (await request.get(`${API}/api/v1/catalog/brands`)).json()) as Array<{ name: string; slug: string }>;
  await page.goto("/brands");
  await expect(page.getByRole("heading", { level: 1, name: "Brands" })).toBeVisible();
  for (const b of brands) {
    await expect(page.locator(`a[href="/brand/${b.slug}"]`)).toBeVisible();
  }
  await expectAccessible(page);
  await screenshot(page, testInfo, "brands");
});

test("deals lists products on sale, filters by brand and sorts", async ({ page, request }, testInfo) => {
  const facets = await (await request.get(`${API}/api/v1/catalog/facets?on_sale=true`)).json();
  await page.goto("/deals");
  await expect(page.getByRole("heading", { level: 1, name: "Deals" })).toBeVisible();
  await expect(page.getByText(`Showing ${facets.total} products`)).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "deals");

  const brand = facets.brands.find((b: { count: number }) => b.count > 0) as { slug: string; name: string; count: number };
  if (isMobile(testInfo.project.name)) {
    await page.getByRole("button", { name: "Filters" }).click();
    const sheet = page.getByRole("dialog", { name: "Filters" });
    await sheet.getByRole("button", { name: brand.name, exact: true }).click();
    await expect(sheet.getByRole("button", { name: `Show ${brand.count} product` })).toBeVisible();
    await expectAccessible(page);
    await screenshot(page, testInfo, "deals-filters");
    await sheet.getByRole("button", { name: /^Show / }).click();
  } else {
    await page.getByRole("checkbox", { name: `${brand.name} (${brand.count})` }).check();
    await page.getByRole("button", { name: "Apply Filters" }).click();
  }
  await expect(page).toHaveURL(new RegExp(`brand=${brand.slug}`));
  await expect(page.getByRole("listitem").getByRole("article")).toHaveCount(brand.count);
  await expect(page.getByRole("link", { name: `Remove ${brand.name} filter` }).first()).toBeAttached();

  await page.getByLabel("Sort by").locator("visible=true").selectOption("price_asc");
  await expect(page).toHaveURL(/sort=price_asc/);
});

test("the mobile menu lists categories, closes on outside click and Escape, and returns focus", async ({ page }, testInfo) => {
  test.skip(!isMobile(testInfo.project.name), "phone layout");
  await page.goto("/");
  const opener = page.getByRole("button", { name: "Open menu" });
  await opener.click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("link", { name: "Phones" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Deals" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "menu");

  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(opener).toBeFocused();

  await opener.click();
  await expect(menu).toBeVisible();
  await page.mouse.click(370, 400); // the backdrop, right of the 320px panel
  await expect(menu).toBeHidden();

  await opener.click();
  await menu.getByRole("link", { name: "RW", exact: false }).last().click();
  await expect(page).toHaveURL(/\/rw$/);
});

test("All Categories opens All Products, which loads further pages while scrolling", async ({ page }, testInfo) => {
  await page.goto("/");
  if (isMobile(testInfo.project.name)) {
    // The bottom tab bar's Categories goes to the same page as the desktop mega menu's "Browse all products".
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Categories" }).click();
  } else {
    const nav = page.getByRole("navigation", { name: "Categories" });
    await nav.getByRole("button", { name: "All Categories" }).click();
    await nav.getByRole("region", { name: "All Categories" }).getByRole("link", { name: "Browse all products" }).click();
  }
  await expect(page).toHaveURL(/\/products$/);
  await expect(page.getByRole("heading", { level: 1, name: "All Products" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Menu" })).toBeHidden();

  const all = (await (await page.request.get(`${API}/api/v1/catalog/products?size=1`)).json()).total as number;
  test.skip(all <= 12, "needs more than one page of products");
  // visible=true: after a client navigation the previous page stays in the DOM, hidden.
  const cards = page.locator("main ul.grid > li > article").locator("visible=true");
  await expect(cards).toHaveCount(12);
  await expectAccessible(page);

  const requested: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/backend/api/v1/catalog/products")) requested.push(new URL(r.url()).searchParams.get("page") ?? "");
  });
  const end = page.getByRole("status").filter({ hasText: "You've seen all" });
  // The wheel scrolls what is under the cursor: over the results, not the filter panel (which
  // scrolls on its own), where "Browse all products" leaves it on desktop.
  await cards.first().hover();
  for (let i = 0; i < 20 && !(await end.isVisible()); i++) {
    await page.mouse.wheel(0, 4000);
    await page.waitForTimeout(400);
  }
  await expect(end).toBeVisible();
  await expect(cards).toHaveCount(all);
  const names = await cards.locator("a.t-h4").allTextContents();
  expect(new Set(names).size).toBe(names.length);
  // Page 1 came with the HTML; each later page was requested once.
  expect(requested).toEqual(Array.from({ length: Math.ceil(all / 12) - 1 }, (_, i) => String(i + 2)));
});

test("Add to Cart on a card adds the shown variant and updates the count", async ({ page }) => {
  await page.goto("/deals");
  // Desktop "Cart" + hidden ", 2 items" reads "Cart , 2 items"; the mobile icon link "Cart, 2 items".
  const cart = page.getByRole("link", { name: /^Cart ?, \d+ item/ }).locator("visible=true");
  await expect(cart).toHaveAccessibleName(/^Cart ?, \d+ items?$/);
  const before = Number((await cart.evaluate((el) => el.textContent ?? el.getAttribute("aria-label") ?? "")).match(/\d+/)?.[0]);
  // Every card's button adds the variant it shows straight away, also for multi-variant products.
  await page.locator("button", { hasText: "Add to Cart" }).first().click();
  // The mini cart opens with the line just added (MiniCart.dc.html).
  const drawer = page.getByRole("dialog", { name: "Added to your cart" });
  await expect(drawer.getByRole("link", { name: "View cart & checkout" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(cart).toHaveAccessibleName(new RegExp(`^Cart ?, ${before + 1} items?$`));
});

test("a guest's heart click goes to sign in with the product to save", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Add to wishlist: / }).first().click();
  await expect(page).toHaveURL(/\/login\?returnTo=%2F&wishlist=[0-9a-f-]{36}$/);
});
