import { expect, test, type APIRequestContext } from "@playwright/test";
import { expectAccessible, screenshot } from "./helpers";

/** Frontend phase 3 against the dev API and its seed: category, brand, product and search pages. */

const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const isMobile = (name: string) => name === "mobile";

async function api<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(`${API}/api/v1${path}`);
  expect(res.ok(), path).toBeTruthy();
  return (await res.json()) as T;
}

/** An unknown slug streams the not-found page with noindex (HTTP 200: the check runs inside a
 * Suspense boundary after the shell is sent; ADR-011 phase 3). */
async function expectNotFound(request: APIRequestContext, path: string) {
  const html = await (await request.get(path)).text();
  expect(html).toContain('<meta name="robots" content="noindex"/>');
  expect(html).toContain("This page could not be found");
}

type Facets = { total: number; categories: Array<{ slug: string; name: string; count: number }> };

test("a category page lists its products with the API's count", async ({ page, request }, testInfo) => {
  const facets = await api<Facets>(request, "/catalog/facets?category=phones");
  await page.goto("/category/phones");
  await expect(page.getByRole("heading", { level: 1, name: "Phones" })).toBeVisible();
  // The compact header has no count; the listing toolbar shows it ("12 products found" / "12 products").
  const count = isMobile(testInfo.project.name) ? `${facets.total} products` : `${facets.total} products found`;
  await expect(page.getByText(count, { exact: true }).locator("visible=true")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Home" })).toBeVisible();
  if (!isMobile(testInfo.project.name)) {
    await expect(page.getByRole("link", { name: "Phones", exact: true }).and(page.locator("[aria-current=page]"))).toBeVisible();
  }
  await expectAccessible(page);
  await screenshot(page, testInfo, "category");

  await expectNotFound(request, "/category/no-such-category");
});

test("a brand page offers Category as its first filter", async ({ page, request }, testInfo) => {
  const facets = await api<Facets>(request, "/catalog/facets?brand=samsung");
  const category = facets.categories[0];
  await page.goto("/brand/samsung");
  await expect(page.getByRole("heading", { level: 1, name: "Samsung" })).toBeVisible();
  await expect(page.getByText(`Showing ${facets.total} products`)).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "brand");

  if (isMobile(testInfo.project.name)) {
    await page.getByRole("button", { name: "Filters" }).click();
    const sheet = page.getByRole("dialog", { name: "Filters" });
    await expect(sheet.getByRole("group", { name: "Brand" })).toHaveCount(0);
    await sheet.getByRole("button", { name: category.name, exact: true }).click();
    await sheet.getByRole("button", { name: /^Show / }).click();
  } else {
    await expect(page.getByRole("group", { name: "Brand" })).toHaveCount(0);
    await page.getByRole("radio", { name: `${category.name} (${category.count})` }).check();
    await page.getByRole("button", { name: "Apply Filters" }).click();
  }
  await expect(page).toHaveURL(new RegExp(`/brand/samsung\\?category=${category.slug}$`));
  await expect(page.getByRole("listitem").getByRole("article")).toHaveCount(category.count);
  await expect(page.getByRole("link", { name: `Remove ${category.name} filter` }).first()).toBeAttached();
});

type Product = {
  name: string;
  variants: Array<{ sku: string; price: number; attributes: Record<string, string> }>;
  rating: { count: number };
};

test("the product page shows variants, specifications and reviews", async ({ page, request }, testInfo) => {
  const product = await api<Product>(request, "/catalog/products/samsung-galaxy-a55-5g");
  const reviews = await api<{ total: number; items: Array<{ author_name: string }> }>(
    request,
    "/catalog/products/samsung-galaxy-a55-5g/reviews",
  );
  const [cheap, dear] = [...product.variants].sort((a, b) => a.price - b.price);
  await page.goto("/product/samsung-galaxy-a55-5g");
  await expect(page.getByRole("heading", { level: 1, name: product.name })).toBeVisible();
  await expect(page.getByText(`RWF ${cheap.price.toLocaleString("en-US")}`).first()).toBeVisible();

  // Picking the other storage changes the price (and the SKU on desktop).
  await page.getByRole("button", { name: new RegExp(`^${dear.attributes.storage}`) }).click();
  await expect(page.getByRole("button", { name: new RegExp(`^${dear.attributes.storage}`) })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".t-price-l").first()).toHaveText(`RWF ${dear.price.toLocaleString("en-US")}`);
  if (!isMobile(testInfo.project.name)) await expect(page.getByText(`SKU: ${dear.sku}`)).toBeVisible();

  const section = page.locator("#reviews");
  await expect(section.getByRole("heading", { name: "Customer reviews" })).toBeVisible();
  if (reviews.total) {
    await expect(section.getByText(reviews.items[0].author_name)).toBeVisible();
    await expect(section.getByText("Verified purchase").first()).toBeVisible();
  }
  if (isMobile(testInfo.project.name)) {
    // The buy bar replaces the tab bar on product pages.
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Buy Now" })).toBeVisible();
  } else {
    await expect(page.getByRole("tab", { name: "Specifications" })).toHaveAttribute("aria-selected", "true");
  }
  await expectAccessible(page);
  await screenshot(page, testInfo, "product");

  await expectNotFound(request, "/product/no-such-product");
});

test("Add to Cart on the product page adds the chosen quantity", async ({ page }, testInfo) => {
  test.skip(isMobile(testInfo.project.name), "the quantity and header count are checked on desktop");
  await page.goto("/product/anker-powercore-20000");
  const cart = page.getByRole("link", { name: /^Cart ?, \d+ item/ }).locator("visible=true");
  await expect(cart).toHaveAccessibleName(/^Cart ?, \d+ items?$/);
  const before = Number((await cart.textContent())?.match(/\d+/)?.[0]);
  await page.getByRole("button", { name: "Increase quantity" }).click();
  await expect(page.getByRole("group", { name: "Quantity" }).locator("[aria-live]")).toHaveText("2");
  await page.getByRole("button", { name: "Add to Cart" }).click();
  // The mini cart opens with the line just added (MiniCart.dc.html).
  const drawer = page.getByRole("dialog", { name: "Added to your cart" });
  await expect(drawer.getByRole("link", { name: "View cart & checkout" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(cart).toHaveAccessibleName(new RegExp(`^Cart ?, ${before + 2} items?$`));
});

test("search shows matches with category chips, and a helpful page when nothing matches", async ({ page, request }, testInfo) => {
  const facets = await api<Facets>(request, "/catalog/facets?q=galaxy");
  expect(facets.total).toBeGreaterThan(0);
  await page.goto("/search?q=galaxy");
  await expect(page.getByRole("heading", { level: 1, name: "Results for “galaxy”" })).toBeVisible();
  await expect(page.getByRole("link", { name: `All (${facets.total})` })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("listitem").getByRole("article")).toHaveCount(Math.min(facets.total, 12));
  // The header search box keeps the text.
  await expect(page.getByRole("searchbox", { name: "Search products" }).locator("visible=true")).toHaveValue("galaxy");
  await expectAccessible(page);
  await screenshot(page, testInfo, "search");

  await page.goto("/search?q=zzqqxx");
  await expect(page.getByRole("heading", { level: 1, name: "No results for “zzqqxx”" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Popular right now" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "search-empty");

  await page.goto("/search");
  await expect(page.getByRole("heading", { level: 1, name: "Search" })).toBeVisible();
});
