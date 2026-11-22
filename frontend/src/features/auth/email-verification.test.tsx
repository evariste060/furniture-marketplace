import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import raw from "../../../messages/en.json";
import { MARKETPLACE_NAME, withMarketplace } from "@/lib/marketplace";
import { LoginView, RegisterView } from "./auth-forms";
import { VerifyEmailView } from "./email-verification";

const en = withMarketplace(raw);

/** Email verification on the storefront (backend 2026-11-12): registration's "check your email",
 * the /verify-email page, asking for a new link, and sign-in refused until verified. This app's
 * route handlers (fetch) and the backend proxy (browserApi) are mocked; the requests they get are
 * checked against the backend's contract (docs/api/email-verification.md). */

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.params }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ replace: nav.replace, push: nav.push }),
  usePathname: () => "/login",
}));
vi.mock("@/features/session/use-session", () => ({ SESSION_KEY: ["session"], useSession: () => ({ data: null, isPending: false }) }));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const v = en.store.auth.verify;
const a = en.store.auth;
const TOKEN = "Zk3".repeat(14) + "q"; // 43 URL-safe characters
const VERIFY = "/api/v1/auth/email/verify";
const RESEND = "/api/v1/auth/email/verification/resend";
const fetchMock = vi.fn();

function renderWith(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          {ui}
        </NextIntlClientProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}

/** What openapi-fetch resolves with. */
function answer(status: number, body?: unknown, headers: Record<string, string> = {}) {
  const ok = status >= 200 && status < 300;
  return { data: ok ? body : undefined, error: ok ? undefined : body, response: new Response(null, { status, headers }) };
}

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

// jsdom has no modal <dialog>: open and close it the way the browser does, without the top layer.
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  this.removeAttribute("open");
};

function open(url: string) {
  window.history.replaceState(null, "", url);
}

beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.replace.mockReset();
  nav.push.mockReset();
  fetchMock.mockReset();
  for (const fn of Object.values(api)) fn.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  open("/verify-email");
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// ---- registration ----------------------------------------------------------------------------------
async function fillRegistration(user: ReturnType<typeof userEvent.setup>, email = "aline@example.rw") {
  await user.type(screen.getByLabelText(a.firstName), "Aline");
  await user.type(screen.getByLabelText(a.lastName), "Uwase");
  await user.type(screen.getByLabelText(a.phone), "788123456");
  await user.type(screen.getByLabelText(new RegExp(`^${a.email}`)), email);
  await user.type(screen.getByLabelText(a.password, { selector: "input" }), "Kigali-2026");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: a.createAccount }));
}

describe("Registration", () => {
  it("opens the 'Check your inbox' card over the page, with the address, and does not sign in", async () => {
    fetchMock.mockResolvedValue(reply({ user: { id: "u1", is_staff: false }, verification_required: true }, 201));
    const user = userEvent.setup();
    renderWith(<RegisterView />);
    await fillRegistration(user);

    const dialog = await screen.findByRole("dialog", { name: v.checkTitle });
    expect(dialog).toHaveAttribute("open");
    const heading = screen.getByRole("heading", { name: v.checkTitle });
    await waitFor(() => expect(heading).toHaveFocus()); // announced to screen readers
    // The owner's Screen 1: the brand band, the address in bold, the spam reminder, one action.
    expect(within(dialog).getByText(MARKETPLACE_NAME)).toBeInTheDocument();
    expect(within(dialog).getByText(v.tagline)).toBeInTheDocument();
    expect(within(dialog).getByText("aline@example.rw").tagName).toBe("B");
    expect(within(dialog).getByText(v.spamNote)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: v.backToSignIn })).toHaveAttribute("href", "/login");
    // Honest: the backend answers before the email leaves, so the card never says it was delivered.
    expect(dialog.textContent).toContain("We’re sending a confirmation link to");
    expect(dialog.textContent).not.toMatch(/we(’|')ve sent|was delivered/i);
    expect(nav.replace).not.toHaveBeenCalled(); // not treated as signed in
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toMatchObject({ email: "aline@example.rw" });
    expect(document.querySelector(".animate-spin")).toBeNull();
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
  });

  it("resends after the cooldown, one request at a time, and says what happened", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValue(reply({ user: { id: "u1", is_staff: false }, verification_required: true }, 201));
    let finish: (value: unknown) => void = () => undefined;
    api.POST.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWith(<RegisterView />);
    await fillRegistration(user);
    await screen.findByRole("dialog");

    // The registration just asked for a link: the backend sends no other within its cooldown.
    const wait = screen.getByRole("button", { name: /Resend confirmation email in 1:00/ });
    expect(wait).toBeDisabled();
    for (let i = 0; i < 61; i++) act(() => void vi.advanceTimersByTime(1000)); // a 1-second tick each
    const resend = screen.getByRole("button", { name: v.resendLink });
    await user.click(resend);
    const busy = screen.getByRole("button", { name: v.sending });
    expect(busy).toBeDisabled();
    await user.click(busy);
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith(RESEND, { body: { email: "aline@example.rw" } });
    act(() => finish(answer(202, { message: "x" })));
    expect(await screen.findByRole("status")).toHaveTextContent(v.sentNeutral);
    expect(screen.getByRole("button", { name: /Resend confirmation email in 1:00/ })).toBeDisabled();

    // A rate limit or an outage is said plainly, and the link waits as the backend asks.
    for (let i = 0; i < 61; i++) act(() => void vi.advanceTimersByTime(1000));
    api.POST.mockResolvedValueOnce(answer(429, { error: { code: "rate_limited" } }, { "retry-after": "120" }));
    await user.click(screen.getByRole("button", { name: v.resendLink }));
    expect(await screen.findByText("Too many requests. Try again in 2 minutes.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resend confirmation email in 2:00/ })).toBeDisabled();
  });

  it("explains a failed resend and lets the customer try again at once", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValue(reply({ user: { id: "u1", is_staff: false }, verification_required: true }, 201));
    api.POST.mockRejectedValueOnce(new TypeError("offline"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderWith(<RegisterView />);
    await fillRegistration(user);
    await screen.findByRole("dialog");
    for (let i = 0; i < 61; i++) act(() => void vi.advanceTimersByTime(1000));
    await user.click(screen.getByRole("button", { name: v.resendLink }));
    expect(await screen.findByRole("status")).toHaveTextContent(v.unavailable);
    expect(screen.getByRole("button", { name: v.resendLink })).toBeEnabled();
  });

  it("closing the card, by its button or Escape, goes to sign-in", async () => {
    fetchMock.mockResolvedValue(reply({ user: { id: "u1", is_staff: false }, verification_required: true }, 201));
    const user = userEvent.setup();
    renderWith(<RegisterView />);
    await fillRegistration(user);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: v.close }));
    expect(nav.push).toHaveBeenCalledWith("/login");
    nav.push.mockReset();
    act(() => void dialog.dispatchEvent(new Event("cancel", { cancelable: true })));
    expect(nav.push).toHaveBeenCalledWith("/login");
  });

  it("keeps the form and explains when no verification email can be sent", async () => {
    fetchMock.mockResolvedValue(reply({ error: { code: "email_verification_unavailable", message: "internal" } }, 503));
    const user = userEvent.setup();
    renderWith(<RegisterView />);
    await fillRegistration(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(v.registerUnavailable);
    expect(screen.getByRole("button", { name: a.createAccount })).toBeEnabled();
    expect(screen.queryByText("internal")).not.toBeInTheDocument();
  });

  it("still explains a taken address on its field", async () => {
    fetchMock.mockResolvedValue(reply({ error: { code: "email_taken" } }, 409));
    const user = userEvent.setup();
    renderWith(<RegisterView />);
    await fillRegistration(user);
    expect(await screen.findByText(a.emailTaken)).toBeInTheDocument();
  });

  it("signs a phone-only registration straight in, as before", async () => {
    fetchMock.mockResolvedValue(reply({ user: { id: "u2", is_staff: false }, verification_required: false }, 201));
    const user = userEvent.setup();
    renderWith(<RegisterView />);
    await user.type(screen.getByLabelText(a.firstName), "Eric");
    await user.type(screen.getByLabelText(a.lastName), "Mugisha");
    await user.type(screen.getByLabelText(a.phone), "788123457");
    await user.type(screen.getByLabelText(a.password, { selector: "input" }), "Kigali-2026");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: a.createAccount }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/account"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

// ---- /verify-email ---------------------------------------------------------------------------------
describe("The verification page", () => {
  it("confirms once from the link, removes the token from the address and offers sign-in", async () => {
    open(`/verify-email#token=${TOKEN}`);
    let finish: (value: unknown) => void = () => undefined;
    api.POST.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderWith(<VerifyEmailView />);

    expect(await screen.findByRole("heading", { name: v.checkingTitle })).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).toBeNull(); // static: nothing spins
    expect(screen.queryByRole("heading", { name: v.verifiedTitle })).not.toBeInTheDocument();
    expect(window.location.hash).toBe(""); // out of the address bar at once
    expect(window.location.href).not.toContain(TOKEN);
    // StrictMode runs the effect twice: still one request.
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith(VERIFY, expect.objectContaining({ body: { token: TOKEN } }));

    act(() => finish(answer(200, { message: "ok" })));
    const heading = await screen.findByRole("heading", { name: v.verifiedTitle });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByRole("link", { name: v.goToLogin })).toHaveAttribute("href", "/login?verified=1");
    expect(screen.getByText(v.verifiedText)).toBeInTheDocument();
    expect(screen.getByText(MARKETPLACE_NAME)).toBeInTheDocument();
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
  });

  it("never shows success for a request that does not answer: it gives up after 15 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockImplementation(
      (_path: string, init: { signal: AbortSignal }) =>
        new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")))),
    );
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.checkingTitle })).toBeInTheDocument();
    act(() => void vi.advanceTimersByTime(14_000));
    expect(screen.getByRole("heading", { name: v.checkingTitle })).toBeInTheDocument();
    act(() => void vi.advanceTimersByTime(1_100));
    expect(await screen.findByRole("heading", { name: v.unavailableTitle })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: v.tryAgain })).toBeEnabled();
    expect(screen.queryByText(v.verifiedTitle)).not.toBeInTheDocument();
  });

  it("checks another link opened in the same tab instead of keeping the earlier success", async () => {
    // Reported 2026-11-13: after one link, any later link opened in that tab (only the #fragment
    // changes, so the browser does not reload) kept showing "Email confirmed".
    const OTHER = "Kq7".repeat(14) + "w";
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockResolvedValueOnce(answer(200, { message: "ok" }));
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.verifiedTitle })).toBeInTheDocument();

    api.POST.mockResolvedValueOnce(answer(422, { error: { code: "verification_token_expired" } }));
    act(() => {
      open(`/verify-email#token=${OTHER}`);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: v.expiredTitle })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: v.verifiedTitle })).not.toBeInTheDocument();
    expect(api.POST).toHaveBeenLastCalledWith(VERIFY, expect.objectContaining({ body: { token: OTHER } }));
    expect(window.location.hash).toBe("");

    // The first link opened again: asked again, and shown as used, not as a fresh success.
    api.POST.mockResolvedValueOnce(answer(422, { error: { code: "verification_token_used" } }));
    act(() => {
      open(`/verify-email#token=${TOKEN}`);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: v.usedTitle })).toBeInTheDocument();
    expect(api.POST).toHaveBeenCalledTimes(3);
  });

  it("ignores a slow answer for an earlier link once another link was opened", async () => {
    const OTHER = "Kq7".repeat(14) + "w";
    open(`/verify-email#token=${TOKEN}`);
    let finishFirst: (value: unknown) => void = () => undefined;
    api.POST.mockReturnValueOnce(new Promise((resolve) => (finishFirst = resolve)));
    renderWith(<VerifyEmailView />);
    await screen.findByRole("heading", { name: v.checkingTitle });

    api.POST.mockResolvedValueOnce(answer(422, { error: { code: "verification_token_invalid" } }));
    act(() => {
      open(`/verify-email#token=${OTHER}`);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: v.invalidTitle })).toBeInTheDocument();
    await act(async () => finishFirst(answer(200, { message: "ok" })));
    expect(screen.getByRole("heading", { name: v.invalidTitle })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: v.verifiedTitle })).not.toBeInTheDocument();
  });

  it("leaves the result alone when the fragment changes without a link", async () => {
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockResolvedValueOnce(answer(422, { error: { code: "verification_token_expired" } }));
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.expiredTitle })).toBeInTheDocument();
    act(() => {
      open("/verify-email#top");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("heading", { name: v.expiredTitle })).toBeInTheDocument();
    expect(api.POST).toHaveBeenCalledTimes(1);
  });

  it("accepts a ?token= link too and removes it", async () => {
    open(`/verify-email?token=${TOKEN}&utm=mail`);
    api.POST.mockResolvedValue(answer(200, { message: "ok" }));
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.verifiedTitle })).toBeInTheDocument();
    expect(window.location.search).toBe("?utm=mail");
    expect(api.POST).toHaveBeenCalledWith(VERIFY, expect.objectContaining({ body: { token: TOKEN } }));
  });

  it("explains a missing token and offers a new link, without calling the backend", async () => {
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.missingTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: v.resendTitle })).toBeInTheDocument();
    expect(screen.getByLabelText(a.email)).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("treats a malformed link as invalid without sending it", async () => {
    open("/verify-email#token=abc%20def");
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.invalidTitle })).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it.each([
    ["verification_token_invalid", v.invalidTitle, true],
    ["verification_token_expired", v.expiredTitle, true],
    ["verification_token_used", v.usedTitle, true],
    ["validation_error", v.invalidTitle, true],
  ])("explains %s", async (code, title, offersLink) => {
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockResolvedValue(answer(422, { error: { code, message: "Internal detail" } }));
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.queryByText("Internal detail")).not.toBeInTheDocument();
    expect(Boolean(screen.queryByRole("heading", { name: v.resendTitle }))).toBe(offersLink);
    if (code === "verification_token_used") {
      expect(screen.getByRole("link", { name: v.goToLogin })).toHaveAttribute("href", "/login?verified=1");
    }
  });

  it("lets the customer retry after a network failure, with the same token", async () => {
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockRejectedValueOnce(new TypeError("offline")).mockResolvedValueOnce(answer(200, { message: "ok" }));
    const user = userEvent.setup();
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.unavailableTitle })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: v.tryAgain }));
    expect(await screen.findByRole("heading", { name: v.verifiedTitle })).toBeInTheDocument();
    expect(api.POST).toHaveBeenNthCalledWith(2, VERIFY, expect.objectContaining({ body: { token: TOKEN } }));
  });

  it.each([
    [500, { error: { code: "internal_error" } }],
    [503, { error: { code: "login_unavailable" } }],
    [502, "<html>bad gateway</html>"],
  ])("treats an unexpected %s answer as a temporary problem", async (status, body) => {
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockResolvedValue(answer(status, body));
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.unavailableTitle })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: v.tryAgain })).toBeInTheDocument();
  });

  it("explains the rate limit with the wait the backend gives", async () => {
    open(`/verify-email#token=${TOKEN}`);
    api.POST.mockResolvedValue(answer(429, { error: { code: "rate_limited" } }, { "retry-after": "300" }));
    renderWith(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: v.limitedTitle })).toBeInTheDocument();
    expect(screen.getByText("Too many requests. Try again in 5 minutes.")).toBeInTheDocument();
  });
});

// ---- asking for a new link -------------------------------------------------------------------------
describe("Asking for a new link", () => {
  async function missingPage() {
    renderWith(<VerifyEmailView />);
    await screen.findByRole("heading", { name: v.missingTitle });
  }

  it("checks the address before sending anything", async () => {
    const user = userEvent.setup();
    await missingPage();
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    expect(screen.getByText(v.emailRequired)).toBeInTheDocument();
    await user.type(screen.getByLabelText(a.email), "not-an-email");
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    expect(screen.getByText(a.emailInvalid)).toBeInTheDocument();
    expect(screen.getByLabelText(a.email)).toHaveFocus();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("shows the same neutral message, never claims delivery, and sends one request at a time", async () => {
    let finish: (value: unknown) => void = () => undefined;
    api.POST.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();
    await missingPage();
    await user.type(screen.getByLabelText(a.email), "aline@example.rw");
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    const busy = screen.getByRole("button", { name: v.sending });
    expect(busy).toBeDisabled();
    await user.click(busy);
    await user.keyboard("{Enter}");
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith(RESEND, { body: { email: "aline@example.rw" } });

    act(() => finish(answer(202, { message: "If an account ..." })));
    expect(await screen.findByText(v.sentNeutral)).toBeInTheDocument();
    expect(v.sentNeutral).toMatch(/^If /); // conditional, as the backend's reply is
    expect(screen.getByRole("button", { name: /Send again in 1:00/ })).toBeDisabled();
  });

  it("waits as long as the backend's rate limit says", async () => {
    api.POST.mockResolvedValue(answer(429, { error: { code: "rate_limited" } }, { "retry-after": "120" }));
    const user = userEvent.setup();
    await missingPage();
    await user.type(screen.getByLabelText(a.email), "aline@example.rw");
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    expect(await screen.findByText("Too many requests. Try again in 2 minutes.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Send again in 2:00/ })).toBeDisabled();
  });

  it.each([
    ["a network failure", () => api.POST.mockRejectedValue(new TypeError("offline"))],
    ["no email provider", () => api.POST.mockResolvedValue(answer(503, { error: { code: "email_verification_unavailable" } }))],
  ])("explains %s and allows another try", async (_, arrange) => {
    arrange();
    const user = userEvent.setup();
    await missingPage();
    await user.type(screen.getByLabelText(a.email), "aline@example.rw");
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    expect(await screen.findByText(v.unavailable)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: v.sendNew })).toBeEnabled();
  });

  it("shows a backend validation refusal on the field", async () => {
    api.POST.mockResolvedValue(answer(422, { error: { code: "validation_error" } }));
    const user = userEvent.setup();
    await missingPage();
    await user.type(screen.getByLabelText(a.email), "aline@example.rw");
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    expect(await screen.findByText(a.emailInvalid)).toBeInTheDocument();
  });
});

// ---- sign-in ---------------------------------------------------------------------------------------
describe("Signing in before verifying", () => {
  async function signIn(user: ReturnType<typeof userEvent.setup>, identifier: string) {
    await user.type(screen.getByLabelText(a.identifier), identifier);
    await user.type(screen.getByLabelText(a.password, { selector: "input" }), "Kigali-2026");
    await user.click(screen.getByRole("button", { name: a.signIn }));
  }

  it("explains email_not_verified, keeps the form and sends a new link to the address typed", async () => {
    fetchMock.mockResolvedValue(reply({ error: { code: "email_not_verified", message: "Please verify" } }, 403));
    api.POST.mockResolvedValue(answer(202, { message: "x" }));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await signIn(user, "aline@example.rw");

    expect(await screen.findByText(v.notVerifiedTitle)).toBeInTheDocument();
    expect(screen.getByText(v.notVerifiedText)).toBeInTheDocument();
    expect(screen.queryByText("Please verify")).not.toBeInTheDocument();
    expect(screen.getByLabelText(a.identifier)).toHaveValue("aline@example.rw");
    expect(screen.getByLabelText(a.password, { selector: "input" })).toHaveValue("Kigali-2026");
    expect(nav.replace).not.toHaveBeenCalled();
    // The address is known: one button, no second email field.
    expect(screen.getAllByLabelText(/email/i).filter((el) => el.tagName === "INPUT")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: v.sendNew }));
    expect(api.POST).toHaveBeenCalledWith(RESEND, { body: { email: "aline@example.rw" } });
    expect(await screen.findByText(v.sentNeutral)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1); // never retries the sign-in by itself
  });

  it("asks for the email when the customer signed in with a phone number; Enter sends it, not the sign-in", async () => {
    fetchMock.mockResolvedValue(reply({ error: { code: "email_not_verified" } }, 403));
    api.POST.mockResolvedValue(answer(202, { message: "x" }));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await signIn(user, "0788123456");
    expect(await screen.findByText(v.notVerifiedTitle)).toBeInTheDocument();
    await user.type(screen.getByLabelText(a.email), "aline@example.rw{Enter}");
    expect(api.POST).toHaveBeenCalledWith(RESEND, { body: { email: "aline@example.rw" } });
    expect(await screen.findByText(v.sentNeutral)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1); // the sign-in form was not submitted again
  });

  it("clears the notice on the next attempt and signs in as before once verified", async () => {
    fetchMock
      .mockResolvedValueOnce(reply({ error: { code: "email_not_verified" } }, 403))
      .mockResolvedValueOnce(reply({ user: { id: "u1", is_staff: false } }));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await signIn(user, "aline@example.rw");
    expect(await screen.findByText(v.notVerifiedTitle)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: a.signIn }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/account"));
  });

  it("keeps the other sign-in errors as they were", async () => {
    fetchMock.mockResolvedValue(reply({ error: { code: "invalid_credentials" } }, 401));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await signIn(user, "aline@example.rw");
    expect(await screen.findByRole("alert")).toHaveTextContent(a.invalid);
    expect(screen.queryByText(v.notVerifiedTitle)).not.toBeInTheDocument();
  });

  it("confirms a verified email when coming from the verification page", () => {
    nav.params = new URLSearchParams({ verified: "1" });
    renderWith(<LoginView />);
    expect(screen.getByText(v.verifiedNotice)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: en.store.auth.google.continue })).toBeInTheDocument();
  });
});
