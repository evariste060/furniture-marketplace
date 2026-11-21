import { createHmac, randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { expectAccessible, screenshot, stockedProduct } from "./helpers";

/** Frontend phase 4 against the dev API and its seed: mini cart, cart, the four checkout steps,
 * the payment page and the confirmation page. Mobile money is settled with a signed mock event,
 * as the provider would send it (PAYMENT_MOCK_WEBHOOK_SECRET, the same secret the API uses). */

const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const SECRET = process.env.PAYMENT_MOCK_WEBHOOK_SECRET;
const PHONE = "0788000111";

// Each test walks the whole checkout with axe checks on every step: 30 s is too tight on a cold server.
test.describe.configure({ timeout: 90_000 });

const visible = (page: Page, name: string | RegExp) => page.getByRole("button", { name }).filter({ visible: true }).first();
const visibleLink = (page: Page, name: string | RegExp) => page.getByRole("link", { name }).filter({ visible: true }).first();

/** The large options hide the native radio; people click the option, as here. */
async function choose(page: Page, name: RegExp) {
  const radio = page.getByRole("radio", { name });
  await page.locator("label").filter({ has: radio }).click();
  await expect(radio).toBeChecked();
}

async function addToCart(page: Page, testInfo: TestInfo, shots = false) {
  const product = await stockedProduct(page.request, API);
  await page.goto(`/product/${product.slug}`);
  // Exact: the "You may also like" cards have their own "Add to Cart: <product>" buttons.
  await visible(page, /^Add to Cart$/).click();
  const drawer = page.getByRole("dialog", { name: "Added to your cart" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText(product.name).first()).toBeVisible();
  if (shots) {
    await expectAccessible(page);
    await screenshot(page, testInfo, "mini-cart");
  }
  await drawer.getByRole("link", { name: "View cart & checkout" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Shopping Cart" })).toBeVisible();
}

async function checkout(page: Page, testInfo: TestInfo, method: "Cash on delivery" | "MTN Mobile Money", shots = false) {
  await visibleLink(page, /Proceed to Checkout/).click();
  await expect(page.getByRole("heading", { level: 1, name: "Contact details" })).toBeVisible();
  // The form checks what is typed before moving on.
  await visible(page, /Continue to delivery/).click();
  await expect(page.getByText("Enter your first name.")).toBeVisible();
  await page.getByLabel("First name").fill("Aline");
  await page.getByLabel("Last name").fill("Mukamana");
  await page.getByLabel("Phone number").fill("788 000 111");
  if (shots) {
    await expectAccessible(page);
    await screenshot(page, testInfo, "checkout-contact");
  }
  await visible(page, /Continue to delivery/).click();

  await expect(page.getByRole("heading", { level: 1, name: "Delivery" })).toBeVisible();
  await page.getByLabel("District").selectOption("Gasabo");
  await page.getByLabel("Street & house number").fill("KG 11 Ave, House 24");
  await expect(page.getByText(/Delivery zone: Gasabo/)).toBeVisible();
  if (shots) {
    await expectAccessible(page);
    await screenshot(page, testInfo, "checkout-delivery");
  }
  await visible(page, /Continue to payment/).click();

  await expect(page.getByRole("radio", { name: /MTN Mobile Money/ })).toBeVisible();
  await choose(page, new RegExp(method));
  if (shots) {
    await expectAccessible(page);
    await screenshot(page, testInfo, "checkout-payment");
  }
  await visible(page, /Review order/).click();

  await expect(page.getByRole("heading", { level: 1, name: "Review your order" })).toBeVisible();
  await expect(page.getByText("KG 11 Ave, House 24, Gasabo")).toBeVisible();
  await visible(page, /^Place order/).click();
  await expect(page.getByText("Please accept the policies to place your order.")).toBeVisible();
  await page.getByRole("checkbox", { name: /I agree to the/ }).check();
  if (shots) {
    await expectAccessible(page);
    await screenshot(page, testInfo, "checkout-review");
  }
  // From "Place order" until the order (or payment) page opens, a spinner shows; the emptied cart
  // never does.
  await page.evaluate(() => {
    const seen = { empty: false, placing: false };
    (window as unknown as { placingSeen: typeof seen }).placingSeen = seen;
    new MutationObserver(() => {
      const text = document.body.innerText;
      if (text.includes("Your cart is empty")) seen.empty = true;
      if (text.includes("This takes a few seconds")) seen.placing = true;
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  });
  await visible(page, /^Place order/).click();
  await page.waitForURL(/\/(order\/[^/]+\/confirmed|checkout\/pay\/[^/]+)$/);
  const seen = await page.evaluate(() => (window as unknown as { placingSeen: { empty: boolean; placing: boolean } }).placingSeen);
  expect(seen).toEqual({ empty: false, placing: true });
}

type Status = { order_number: string; status: string; amount: number; currency_code: string; reference: string | null };

async function paymentStatus(request: APIRequestContext, number: string): Promise<Status> {
  const res = await request.get(`${API}/api/v1/payments/${number}/status`, { headers: { "X-Order-Phone": PHONE } });
  expect(res.ok()).toBeTruthy();
  return (await res.json()) as Status;
}

/** Waits for the mobile money request the page started, then settles it as the provider would. */
async function settle(request: APIRequestContext, number: string, outcome: "succeeded" | "failed", previous: string | null = null) {
  let status: Status | undefined;
  await expect
    .poll(async () => {
      status = await paymentStatus(request, number);
      return status.status === "pending" && status.reference !== null && status.reference !== previous;
    })
    .toBe(true);
  const event = {
    event_id: `e2e-${randomUUID()}`,
    reference: status!.reference,
    status: outcome,
    amount: status!.amount,
    currency: status!.currency_code,
    ...(outcome === "failed" ? { reason: "declined" } : {}),
  };
  const body = JSON.stringify(event);
  const timestamp = Math.floor(Date.now() / 1000);
  const signature = `sha256=${createHmac("sha256", SECRET!).update(`${timestamp}.${body}`).digest("hex")}`;
  const res = await request.post(`${API}/api/v1/webhooks/mock`, {
    headers: { "content-type": "application/json", "x-mock-timestamp": String(timestamp), "x-mock-signature": signature },
    data: body,
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return status!.reference;
}

function orderFromUrl(page: Page): string {
  const match = /(ORD-[A-Z0-9-]+)/.exec(page.url());
  expect(match, page.url()).not.toBeNull();
  return match![1];
}

test("a guest orders with cash on delivery", async ({ page }, testInfo) => {
  await addToCart(page, testInfo, true);
  await expect(page.getByText("In stock").first()).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "cart");

  // A code the backend does not know is refused with a message.
  await page.getByLabel("Discount code").fill("NOSUCHCODE");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("This code isn't valid. Check it and try again.")).toBeVisible();

  await checkout(page, testInfo, "Cash on delivery", true);
  await expect(page).toHaveURL(/\/order\/ORD-[A-Z0-9-]+\/confirmed$/);
  await expect(page.getByRole("heading", { level: 1, name: "Thank you, Aline — your order is placed" })).toBeVisible();
  await expect(page.getByText("Pay on delivery", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Create account" })).toHaveAttribute("href", /\/register\?name=Aline\+Mukamana&phone=0788000111/);
  await expectAccessible(page);
  await screenshot(page, testInfo, "order-confirmed");

  // The order emptied the cart.
  await page.goto("/cart");
  await expect(page.getByRole("heading", { name: "Your cart is empty" })).toBeVisible();
});

test("a guest pays with mobile money after a declined request", async ({ page, request }, testInfo) => {
  test.skip(!SECRET, "PAYMENT_MOCK_WEBHOOK_SECRET is not set");
  await addToCart(page, testInfo);
  await checkout(page, testInfo, "MTN Mobile Money");
  await expect(page).toHaveURL(/\/checkout\/pay\/ORD-/);
  await expect(page.getByRole("heading", { level: 1, name: "Approve the payment on your phone" })).toBeVisible();
  const number = orderFromUrl(page);
  const first = await settle(request, number, "failed");
  await expect(page.getByRole("heading", { level: 1, name: "Payment not completed" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "payment-failed");

  await page.getByRole("button", { name: "Try again with the same number" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Approve the payment on your phone" })).toBeVisible();
  await expect(page.getByText(/Your items are held for/)).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "payment-waiting");
  await settle(request, number, "succeeded", first);

  await expect(page).toHaveURL(new RegExp(`/order/${number}/confirmed$`));
  await expect(page.getByRole("heading", { level: 1, name: "Thank you, Aline — your order is confirmed" })).toBeVisible();
  await expect(page.getByText("Paid", { exact: true })).toBeVisible();
});

test("a guest switches to cash on delivery after a failed payment", async ({ page, request }, testInfo) => {
  test.skip(!SECRET, "PAYMENT_MOCK_WEBHOOK_SECRET is not set");
  test.skip(testInfo.project.name === "mobile", "one viewport is enough for the switch");
  await addToCart(page, testInfo);
  await checkout(page, testInfo, "MTN Mobile Money");
  await expect(page.getByRole("heading", { level: 1, name: "Approve the payment on your phone" })).toBeVisible();
  const number = orderFromUrl(page);
  await settle(request, number, "failed");
  await page.getByRole("button", { name: "Choose another payment method" }).click();
  await choose(page, /Cash on delivery/);
  await expectAccessible(page);
  await page.getByRole("button", { name: "Use this method" }).click();
  await expect(page).toHaveURL(new RegExp(`/order/${number}/confirmed$`));
  await expect(page.getByRole("heading", { level: 1, name: "Thank you, Aline — your order is placed" })).toBeVisible();
});

test("a guest opening an order link in a new tab confirms the phone first", async ({ page, browser, request }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "one viewport is enough");
  await addToCart(page, testInfo);
  await checkout(page, testInfo, "Cash on delivery");
  await expect(page).toHaveURL(/\/confirmed$/);
  const number = orderFromUrl(page);

  const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
  const other = await context.newPage();
  await other.goto(`/order/${number}/confirmed`);
  await expect(other.getByRole("heading", { level: 1, name: "Confirm your order" })).toBeVisible();
  await other.getByLabel("Phone number").fill("788 999 999");
  await other.getByRole("button", { name: "Continue" }).click();
  await expect(other.getByRole("heading", { level: 1, name: "Confirm your order" })).toBeVisible();
  await other.getByLabel("Phone number").fill("788 000 111");
  await other.getByRole("button", { name: "Continue" }).click();
  await expect(other.getByRole("heading", { level: 1, name: /your order is placed/ })).toBeVisible();
  await context.close();
  expect((await paymentStatus(request, number)).status).toBe("pending");
});
