import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

/** Every page is checked against WCAG 2.1 A and AA with axe. axe measures text contrast as drawn,
 * so text caught fading in or out (the home hero changes every few seconds) reads as too light.
 * The scan therefore runs with reduced motion, where the animations are off and everything is
 * drawn in its final state, as people who ask for reduced motion see it; then motion is back on. */
export async function expectAccessible(page: Page) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  // Transitions already under way end (they are short); the animations stop at once.
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity));
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze()
    .finally(() => page.emulateMedia({ reducedMotion: null }));
  const summary = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(summary, summary.join("\n")).toEqual([]);
}

/** A full-page screenshot per viewport (desktop 1440px, mobile 390px) for design review. They are
 * written to e2e/screenshots (git-ignored). */
export async function screenshot(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: `e2e/screenshots/${name}-${testInfo.project.name}.png`, fullPage: true });
}

type ListedProduct = { id: string; slug: string; name: string; variants: { stock_status: string }[] };

/** A cheap product with plenty of stock, read from the public catalogue. Every run places real
 * orders against the dev data, so a fixed product sells out; this picks the cheapest one-variant
 * product that is still "in stock" (not low), below the free-delivery amount (RWF 50,000 in the dev settings) so the fee shows. */
export async function stockedProduct(request: APIRequestContext, api: string): Promise<ListedProduct> {
  const response = await request.get(`${api}/api/v1/catalog/products`, {
    params: { in_stock: true, max_price: 49_999, sort_by: "price", size: 50 },
  });
  expect(response.ok()).toBeTruthy();
  const { items } = (await response.json()) as { items: ListedProduct[] };
  const product = items.find((p) => p.variants.length === 1 && p.variants[0]?.stock_status === "in_stock");
  if (!product) throw new Error("No cheap product is in stock in the dev data: restock it from the admin or reseed.");
  return product;
}
