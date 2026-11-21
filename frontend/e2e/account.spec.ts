import { randomInt } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { expectAccessible, screenshot, stockedProduct } from "./helpers";

/** Frontend phase 5 against the dev API: registration, the account area (addresses, profile,
 * password, orders), sign-out and sign-in, Track, and the auth and review pages' other states. */

const API = process.env.API_URL ?? "http://127.0.0.1:8000";
const PASSWORD = "Kigali-2026";
const NEW_PASSWORD = "Kigali-2027";

/** Recently visited pages stay in the DOM, hidden (Next.js keeps their state): only the visible
 * field counts. */
const field = (page: Page, label: string) => page.getByLabel(label, { exact: true }).filter({ visible: true });
const visible = (page: Page, role: "button" | "link", name: string | RegExp) => page.getByRole(role, { name }).filter({ visible: true }).first();

/** An account menu item: the side menu, or on phones the tab bar's Account popup (opened first). */
async function accountMenu(page: Page, role: "button" | "link", name: string) {
  const tab = page.getByRole("button", { name: "Account", exact: true }).filter({ visible: true });
  if (await tab.count()) await tab.click();
  await visible(page, role, name).click();
}

async function choose(page: Page, name: RegExp) {
  const radio = page.getByRole("radio", { name });
  await page.locator("label").filter({ has: radio }).click();
  await expect(radio).toBeChecked();
}

/** A new account's own phone number, so every run registers afresh. */
function newPhone(): string {
  return `078${String(randomInt(0, 10_000_000)).padStart(7, "0")}`;
}

test("a customer registers, manages the account, orders and tracks the order", async ({ page, browser }, testInfo) => {
  test.setTimeout(240_000);
  const phone = newPhone();

  // Registration, filled in from the order confirmation link.
  await page.goto(`/register?name=Aline%20Mukamana&phone=${phone}`);
  await expect(page.getByRole("heading", { level: 1, name: "Create your account" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "First name" })).toHaveValue("Aline");
  await expect(page.getByRole("textbox", { name: "Last name" })).toHaveValue("Mukamana");
  await expect(page.getByLabel("Phone number")).toHaveValue(`${phone.slice(1, 4)} ${phone.slice(4, 7)} ${phone.slice(7)}`);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Please accept the Terms and Privacy Policy.")).toBeVisible();
  await field(page, "Password").fill(PASSWORD);
  await page.getByRole("checkbox", { name: /I agree to the/ }).check();
  await expectAccessible(page);
  await screenshot(page, testInfo, "register");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("heading", { level: 1, name: "Hello, Aline" })).toBeVisible();
  await expect(page.getByText("You haven’t placed an order yet.")).toBeVisible();

  // On phones the account pages are in a popup above the tab bar's Account item; Escape and a tap
  // outside close it.
  if (testInfo.project.name === "mobile") {
    const tab = page.getByRole("button", { name: "Account", exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-expanded", "true");
    const menu = page.getByRole("navigation", { name: "Account" }).filter({ visible: true });
    await expect(menu.getByRole("link")).toHaveCount(5);
    await expect(menu.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expectAccessible(page);
    await screenshot(page, testInfo, "account-menu");
    await page.keyboard.press("Escape");
    await expect(tab).toHaveAttribute("aria-expanded", "false");
    await expect(tab).toBeFocused();
    await tab.click();
    await page.getByRole("heading", { level: 1 }).click();
    await expect(tab).toHaveAttribute("aria-expanded", "false");
  }

  // Addresses: add two, move the default, delete one.
  await accountMenu(page, "link", "Addresses");
  await expect(page.getByRole("heading", { level: 1, name: "Addresses" })).toBeVisible();
  await expect(page.getByText(/You haven’t saved an address yet/)).toBeVisible();
  // The address form opens in a popup and closes once the address is saved.
  await page.getByRole("button", { name: "Add new address" }).click();
  const popup = page.getByRole("dialog", { name: "New address" });
  await expect(popup).toBeVisible();
  const form = popup.getByRole("form", { name: "New address" });
  await expect(form.getByLabel("Recipient name")).toHaveValue("Aline Mukamana");
  await form.getByRole("button", { name: "Save address" }).click();
  await expect(form.getByText("Choose a district.")).toBeVisible();
  await form.getByLabel("Label").fill("Home");
  await form.getByLabel("District").selectOption("Gasabo");
  await form.getByLabel("Sector").fill("Kimironko");
  await form.getByLabel("Street & house").fill("KG 11 Ave, House 24");
  await form.getByLabel("Landmark or directions").fill("Near Kimironko market, blue gate");
  await expectAccessible(page);
  await screenshot(page, testInfo, "address-popup");
  await form.getByRole("button", { name: "Save address" }).click();
  await expect(popup).toBeHidden();
  const home = page.getByRole("article", { name: "Home" });
  await expect(home.getByText("Default", { exact: true })).toBeVisible();
  await expect(home.getByText("Landmark: Near Kimironko market, blue gate")).toBeVisible();

  await page.getByRole("button", { name: "Add new address" }).click();
  await form.getByLabel("Label").fill("Office");
  await form.getByLabel("District").selectOption("Nyarugenge");
  await form.getByLabel("Street & house").fill("KN 4 Ave, Kigali Heights");
  await form.getByRole("button", { name: "Save address" }).click();
  const office = page.getByRole("article", { name: "Office" });
  await expect(office).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "addresses");
  await office.getByRole("button", { name: /Set as default/ }).click();
  await expect(office.getByText("Default", { exact: true })).toBeVisible();
  await expect(home.getByText("Default", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Delete Office" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete this address?" });
  await expect(dialog).toBeVisible();
  await expectAccessible(page);
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(office).toHaveCount(0);
  await expect(home.getByText("Default", { exact: true })).toBeVisible();

  // Profile: details and password.
  await accountMenu(page, "link", "Profile & security");
  await expect(page.getByRole("heading", { level: 1, name: "Profile & security" })).toBeVisible();
  await page.getByRole("textbox", { name: "First name" }).fill("Alina");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await field(page, "Current password").fill("Wrong-Pass-1");
  await field(page, "New password").fill(NEW_PASSWORD);
  await field(page, "Confirm new password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("Your current password isn’t right.")).toBeVisible();
  await field(page, "Current password").fill(PASSWORD);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText(/Password updated\. You were signed out/)).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "profile");

  // An order as the signed-in customer: the contact step and the saved address are filled in.
  const product = await stockedProduct(page.request, API);
  await page.goto(`/product/${product.slug}`);
  // Exact: the "You may also like" cards have their own "Add to Cart: <product>" buttons.
  await visible(page, "button", /^Add to Cart$/).click();
  await page.getByRole("dialog", { name: "Added to your cart" }).getByRole("link", { name: "View cart & checkout" }).click();
  await visible(page, "link", /Proceed to Checkout/).click();
  await expect(page.getByRole("textbox", { name: "First name" })).toHaveValue("Alina");
  await visible(page, "button", /Continue to delivery/).click();
  await expect(page.getByRole("radio", { name: /Home/ })).toBeChecked();
  await visible(page, "button", /Continue to payment/).click();
  await choose(page, /Cash on delivery/);
  await visible(page, "button", /Review order/).click();
  await page.getByRole("checkbox", { name: /I agree to the/ }).check();
  await visible(page, "button", /^Place order/).click();
  await expect(page).toHaveURL(/\/order\/ORD-[A-Z0-9-]+\/confirmed$/);
  const number = /(ORD-[A-Z0-9-]+)/.exec(page.url())![1]!;
  await expect(page.getByRole("link", { name: "Track order", exact: true })).toHaveAttribute("href", new RegExp(`/track\\?order=${number}$`));

  // The order in the account.
  await page.goto("/account/orders");
  await expect(page.getByRole("heading", { level: 2, name: `Order #${number}` })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "account-orders");
  await page.getByRole("link", { name: "View details" }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: `Order #${number}` })).toBeVisible();
  await expect(page.getByText("Pay on delivery")).toBeVisible();
  await expect(page.getByText("KG 11 Ave, House 24, Kimironko, Gasabo")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "order-detail");
  await accountMenu(page, "link", "Overview");
  await expect(page.getByRole("link", { name: new RegExp(number) })).toBeVisible();
  await expect(page.getByText("Home · KG 11 Ave, House 24, Kimironko, Gasabo")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "account");

  // Track, as a guest in another browser.
  const context = await browser.newContext({ baseURL: testInfo.project.use.baseURL, viewport: testInfo.project.use.viewport });
  const guest = await context.newPage();
  await guest.goto(`/track?order=${number}`);
  await expect(guest.getByLabel("Order number")).toHaveValue(number);
  await guest.getByLabel("Phone number").fill("788 999 999");
  await guest.getByRole("button", { name: "Track order" }).click();
  await expect(guest.getByRole("alert").filter({ hasText: "We couldn’t find that order." })).toBeVisible();
  await guest.getByLabel("Phone number").fill(phone.slice(1));
  await guest.getByRole("button", { name: "Track order" }).click();
  await expect(guest.getByText(`#${number}`)).toBeVisible();
  await expect(guest.getByText("Order placed")).toBeVisible();
  await expectAccessible(guest);
  await screenshot(guest, testInfo, "track");
  await context.close();

  // Sign out, sign back in with the new password; the hearted product is saved on the way.
  await page.goto("/account");
  await accountMenu(page, "button", "Log out");
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/account");
  await expect(page).toHaveURL(/\/login\?returnTo=%2Faccount$/);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "login");

  await page.goto(`/login?returnTo=${encodeURIComponent(`/product/${product.slug}`)}&wishlist=${product.id}`);
  await field(page, "Email or phone number").fill(phone);
  await field(page, "Password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(new RegExp(`/product/${product.slug}$`));
  await expect(visible(page, "button", `Remove from wishlist: ${product.name}`)).toHaveAttribute("aria-pressed", "true");

  // The header's Wishlist link opens the saved products (the phone header has none); the heart on
  // a card removes one.
  if (testInfo.project.name === "mobile") await page.goto("/account/wishlist");
  else await visible(page, "link", /^Wishlist/).click();
  await expect(page).toHaveURL(/\/account\/wishlist$/);
  await expect(page.getByRole("heading", { level: 1, name: "Wishlist" })).toBeVisible();
  await expect(page.getByText("1 saved product")).toBeVisible();
  await expect(visible(page, "link", product.name)).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "wishlist");
  await visible(page, "button", `Remove from wishlist: ${product.name}`).click();
  await expect(page.getByText(/Your wishlist is empty/)).toBeVisible();
});

test("the sign-in and password pages check what is typed", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "one viewport is enough for the messages");
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter your email or phone number.")).toBeVisible();
  await expect(page.getByText("Enter your password.")).toBeVisible();
  await field(page, "Email or phone number").fill(newPhone());
  await field(page, "Password").fill("Not-The-Password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "That email, phone number or password isn’t right." })).toBeVisible();
  // The return path stays on this site.
  await page.goto("/login?returnTo=%2F%2Fevil.example");
  await expect(page.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", /returnTo=%2Faccount/);

  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Forgot your password?" })).toBeVisible();
  await page.getByLabel("Phone number or email").fill("not an email");
  await page.getByRole("button", { name: "Send reset code" }).click();
  await expect(page.getByText("Enter a valid email or a Rwandan mobile number")).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "forgot");

  // Opened without the forgot step: the page asks for the phone or email too.
  await page.goto("/reset-password");
  await expect(page.getByRole("heading", { level: 1, name: "Reset your password" })).toBeVisible();
  await page.getByRole("button", { name: "Reset password" }).click();
  await expect(page.getByText("Enter the 6-digit code.")).toBeVisible();
  await page.getByLabel("Digit 1").fill("123456");
  await expect(page.getByLabel("Digit 6")).toHaveValue("6");
  await expectAccessible(page);
  await screenshot(page, testInfo, "reset");
});

test("an unknown review link says so", async ({ page }, testInfo) => {
  await page.goto("/review/not-a-real-review-link-token-000000");
  await expect(page.getByRole("heading", { level: 1, name: "This link isn’t valid" })).toBeVisible();
  await expectAccessible(page);
  await screenshot(page, testInfo, "review-invalid");
});
