import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../../../messages/en.json";
import rw from "../../../messages/rw.json";
import { ProfileView } from "@/features/account/account-settings";
import { LoginView, RegisterView } from "./auth-forms";

/** Continue with Google on the login, register and profile pages, with this app's route handlers
 * (fetch) and the backend (browserApi) mocked. The existing forms must stay as they were. */

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => nav.params }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  usePathname: () => "/login",
}));
vi.mock("@/features/session/use-session", () => ({ SESSION_KEY: ["session"], useSession: () => ({ data: null, isPending: false }) }));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x";
const assign = vi.fn();
const fetchMock = vi.fn();

function renderWith(ui: ReactNode, locale: "en" | "rw" = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : rw}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

/** The pageshow event; `persisted` is true when the page comes from the back/forward cache. */
function pageShow(persisted: boolean): Event {
  return Object.assign(new Event("pageshow"), { persisted });
}

function reply(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const g = en.store.auth.google;
const a = en.store.account;

beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.replace.mockReset();
  fetchMock.mockReset();
  assign.mockReset();
  for (const fn of Object.values(api)) fn.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, assign } });
});
afterEach(() => vi.unstubAllGlobals());

describe("Continue with Google on Login", () => {
  it("sits above the unchanged sign-in form", () => {
    renderWith(<LoginView />);
    const google = screen.getByRole("button", { name: g.continue });
    const identifier = screen.getByLabelText(en.store.auth.identifier);
    // Above the form's first field, separated by the design's "or" divider.
    expect(google.compareDocumentPosition(identifier) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(en.store.auth.or)).toBeInTheDocument();
    expect(screen.getByLabelText(en.store.auth.password, { selector: "input" })).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: en.store.auth.showPassword })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.store.auth.forgot })).toHaveAttribute("href", "/forgot-password");
    expect(screen.getByRole("button", { name: en.store.auth.signIn })).toBeEnabled();
    expect(google).toHaveAttribute("type", "button"); // never submits the password form
  });

  it("starts through this app with where to return, the language and the hearted product, then goes to Google", async () => {
    nav.params = new URLSearchParams({ returnTo: "/cart", wishlist: "0b7c6f1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b" });
    let answer: (r: Response) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (answer = resolve)));
    const user = userEvent.setup();
    renderWith(<LoginView />, "rw");

    await user.click(screen.getByRole("button", { name: rw.store.auth.google.continue }));
    const pending = screen.getByRole("button", { name: rw.store.auth.google.starting });
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("aria-busy", "true");
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/auth/google/start");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      page: "login",
      returnTo: "/cart",
      wishlist: "0b7c6f1e-2a3d-4e5f-8a9b-0c1d2e3f4a5b",
      locale: "rw",
    });

    answer(reply({ authorization_url: AUTH_URL }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTH_URL));
  });

  it("gets its button back when the page is restored from the back/forward cache", async () => {
    fetchMock.mockResolvedValue(reply({ authorization_url: AUTH_URL }));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await user.click(screen.getByRole("button", { name: g.continue }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTH_URL));
    expect(screen.getByRole("button", { name: g.starting })).toBeDisabled(); // left for Google

    // A normal page show (not from the cache) changes nothing.
    act(() => void window.dispatchEvent(pageShow(false)));
    expect(screen.getByRole("button", { name: g.starting })).toBeDisabled();

    // Back from Google: the browser restores the page as it was left.
    act(() => void window.dispatchEvent(pageShow(true)));
    expect(screen.getByRole("button", { name: g.continue })).toBeEnabled();
  });

  it("never navigates to a URL that is not Google's", async () => {
    fetchMock.mockResolvedValue(reply({ authorization_url: "https://evil.example/" }));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await user.click(screen.getByRole("button", { name: g.continue }));
    expect(await screen.findByRole("alert")).toHaveTextContent(g.unavailable);
    expect(assign).not.toHaveBeenCalled();
  });

  it("explains a start that failed and lets the visitor try again", async () => {
    fetchMock.mockResolvedValueOnce(reply({ error: { code: "rate_limited" } }, 429));
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await user.click(screen.getByRole("button", { name: g.continue }));
    expect(await screen.findByRole("alert")).toHaveTextContent(g.limited);
    expect(screen.getByRole("button", { name: g.continue })).toBeEnabled();

    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    await user.click(screen.getByRole("button", { name: g.continue }));
    expect(await screen.findByRole("alert")).toHaveTextContent(g.unavailable);
  });

  it.each([
    ["google_auth_cancelled", g.cancelled],
    ["google_state_invalid", g.expired],
    ["google_account_exists", g.exists],
    ["google_staff_not_allowed", g.staff],
    ["google_email_unverified", g.unverified],
    ["google_unavailable", g.unavailable],
    ["something_new", g.failed],
  ])("explains the callback's %s", (code, message) => {
    nav.params = new URLSearchParams({ google_error: code });
    renderWith(<LoginView />);
    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it("disables Google while the password sign-in is running, and clears its error on submit", async () => {
    nav.params = new URLSearchParams({ google_error: "google_auth_cancelled" });
    fetchMock.mockReturnValue(new Promise(() => undefined)); // /api/auth/login never answers
    const user = userEvent.setup();
    renderWith(<LoginView />);
    await user.type(screen.getByLabelText(en.store.auth.identifier), "aline@example.rw");
    await user.type(screen.getByLabelText(en.store.auth.password, { selector: "input" }), "Kigali-2026");
    await user.click(screen.getByRole("button", { name: en.store.auth.signIn }));
    expect(screen.getByRole("button", { name: g.continue })).toBeDisabled();
    expect(screen.queryByText(g.cancelled)).not.toBeInTheDocument();
    expect((fetchMock.mock.calls[0] as [string])[0]).toBe("/api/auth/login");
  });

  it("shows no staff sign-in note (removed, SC-07)", () => {
    renderWith(<LoginView />);
    expect(screen.queryByText(/admin panel/i)).not.toBeInTheDocument();
  });
});

describe("Continue with Google on Register", () => {
  it("sits above the unchanged registration form and starts from the register page", async () => {
    fetchMock.mockResolvedValue(reply({ authorization_url: AUTH_URL }));
    const user = userEvent.setup();
    renderWith(<RegisterView />);
    const google = screen.getByRole("button", { name: g.continue });
    expect(google.compareDocumentPosition(screen.getByLabelText(en.store.auth.firstName)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: en.store.auth.createAccount })).toBeEnabled();

    await user.click(google);
    await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTH_URL));
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toMatchObject({ page: "register", returnTo: "/account" });
  });

  it("explains a cancellation that came back to the register page", () => {
    nav.params = new URLSearchParams({ google_error: "google_auth_cancelled" });
    renderWith(<RegisterView />);
    expect(screen.getByRole("alert")).toHaveTextContent(g.cancelled);
  });
});

// ---- Profile: Connected accounts ---------------------------------------------------------------

const profile = { id: "u1", full_name: "Aline Uwase", phone: "0788000111", email: "aline@example.rw" };

function me(flags: { google_linked: boolean; has_password: boolean }) {
  return { id: "u1", email: "aline@example.rw", phone: "0788000111", full_name: "Aline Uwase", is_active: true, is_staff: false, roles: ["customer"], created_at: "2026-11-01T00:00:00Z", ...flags };
}

function backend(flags: { google_linked: boolean; has_password: boolean } | "error") {
  api.GET.mockImplementation(async (path: string) => {
    if (path === "/api/v1/customers/me") return { data: profile, error: undefined, response: { status: 200, ok: true } };
    if (path === "/api/v1/auth/me") {
      if (flags === "error") return { data: undefined, error: { error: { code: "x" } }, response: { status: 500, ok: false } };
      return { data: me(flags), error: undefined, response: { status: 200, ok: true } };
    }
    throw new Error(`unexpected ${path}`);
  });
}

describe("Profile: Connected accounts", () => {
  it("shows Google as connected, with no Connect action, beside the password", async () => {
    backend({ google_linked: true, has_password: true });
    renderWith(<ProfileView />);
    expect(await screen.findByText(a.googleConnectedText)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: a.connectedTitle })).toBeInTheDocument();
    expect(screen.getByText(a.connected)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: a.connectGoogle })).not.toBeInTheDocument();
    expect(screen.getByText(a.passwordSet)).toBeInTheDocument();
    // The existing password form stays for accounts with a password.
    expect(screen.getByLabelText(a.currentPassword, { selector: "input" })).toBeInTheDocument();
  });

  it("offers Connect Google when not connected, and it starts a link flow through this app", async () => {
    backend({ google_linked: false, has_password: true });
    fetchMock.mockResolvedValue(reply({ authorization_url: AUTH_URL }));
    const user = userEvent.setup();
    renderWith(<ProfileView />);
    await user.click(await screen.findByRole("button", { name: a.connectGoogle }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTH_URL));
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/auth/google/link/start");
    expect(JSON.parse(init.body as string)).toEqual({ locale: "en", returnTo: "/account/profile" });
    expect(screen.getByText(a.notConnected)).toBeInTheDocument();
  });

  it("gets Connect Google back when the page is restored from the back/forward cache", async () => {
    backend({ google_linked: false, has_password: true });
    fetchMock.mockResolvedValue(reply({ authorization_url: AUTH_URL }));
    const user = userEvent.setup();
    renderWith(<ProfileView />);
    await user.click(await screen.findByRole("button", { name: a.connectGoogle }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(AUTH_URL));
    expect(screen.getByRole("button", { name: a.connectingGoogle })).toBeDisabled();
    act(() => void window.dispatchEvent(pageShow(true)));
    expect(screen.getByRole("button", { name: a.connectGoogle })).toBeEnabled();
  });

  it("reports an existing connection as information, and refreshes the status", async () => {
    backend({ google_linked: false, has_password: true });
    fetchMock.mockResolvedValue(reply({ error: { code: "google_already_linked" } }, 409));
    const user = userEvent.setup();
    renderWith(<ProfileView />);
    await user.click(await screen.findByRole("button", { name: a.connectGoogle }));
    // Shown as information (role status, the green alert), not as an error.
    expect((await screen.findByText(g.alreadyLinked)).closest("[role]")).toHaveAttribute("role", "status");
    await waitFor(() => expect(api.GET.mock.calls.filter(([p]) => p === "/api/v1/auth/me").length).toBe(2));
  });

  it("confirms a new connection and explains a conflict from the callback", async () => {
    backend({ google_linked: true, has_password: true });
    nav.params = new URLSearchParams({ google: "linked" });
    const first = renderWith(<ProfileView />);
    expect(await screen.findByText(a.googleLinkedNow)).toBeInTheDocument();
    first.unmount();

    backend({ google_linked: false, has_password: true });
    nav.params = new URLSearchParams({ google_error: "google_account_in_use" });
    renderWith(<ProfileView />);
    expect(await screen.findByText(g.inUse)).toBeInTheDocument();
  });

  it("does not ask a Google-only customer for a current password", async () => {
    backend({ google_linked: true, has_password: false });
    renderWith(<ProfileView />);
    expect(await screen.findByText(a.passwordNotSetText)).toBeInTheDocument();
    expect(screen.getByText(a.passwordNotSet)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: a.setPasswordTitle })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: a.setPassword })).toHaveAttribute("href", "/forgot-password");
    expect(screen.queryByLabelText(a.currentPassword, { selector: "input" })).not.toBeInTheDocument();
  });

  it("keeps the password form and offers a retry when the status cannot load", async () => {
    backend("error");
    renderWith(<ProfileView />);
    const section = (await screen.findByRole("heading", { name: a.connectedTitle })).closest("section")!;
    await waitFor(() => expect(section).toHaveTextContent(a.loadFailed));
    expect(screen.getByLabelText(a.currentPassword, { selector: "input" })).toBeInTheDocument();
  });
});
