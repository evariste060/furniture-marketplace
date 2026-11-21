import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { WriteReview } from "./write-review";

/** The review page's states with the backend mocked: a delivered order cannot be made from the
 * browser tests (staff deliver orders), so the form is checked here. */

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("next/image", () => ({ default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} /> }));

const TOKEN = "a".repeat(43);
const info = (status: "open" | "expired" | "used") => ({
  data: { status, expires_at: "2027-01-01T00:00:00Z", product: { name: "HP Pavilion 15 Laptop", slug: "hp-pavilion-15", image: null }, variant_name: "8GB · 512GB" },
  error: undefined,
  response: { status: 200, ok: true },
});
const failure = (status: number, code: string) => ({ data: undefined, error: { error: { code, message: code } }, response: { status, ok: false } });

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <WriteReview token={TOKEN} />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
});

describe("WriteReview", () => {
  it("checks the form, sends the review and thanks the buyer", async () => {
    api.GET.mockResolvedValue(info("open"));
    api.POST.mockResolvedValue({ data: { id: "r1", status: "pending" }, error: undefined, response: { status: 201, ok: true } });
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("HP Pavilion 15 Laptop")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Submit review" }));
    expect(screen.getByText("Choose a rating from 1 to 5 stars.")).toBeInTheDocument();
    expect(screen.getByText("Write at least 20 characters.")).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText("4 stars"));
    expect(screen.getByText("Very good")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Your review/), "Boots quickly and the battery lasts all day.");
    await user.click(screen.getByRole("button", { name: "Submit review" }));

    expect(await screen.findByRole("heading", { name: "Thank you!" })).toBeInTheDocument();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/reviews/{token}", {
      params: { path: { token: TOKEN } },
      body: { rating: 4, title: null, body: "Boots quickly and the battery lasts all day." },
    });
  });

  it("shows the expired and already-reviewed states", async () => {
    api.GET.mockResolvedValueOnce(info("expired"));
    renderPage();
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login?returnTo=/account/orders");
  });

  it("shows the already-reviewed state with the product link", async () => {
    api.GET.mockResolvedValueOnce(info("used"));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Already reviewed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the product" })).toHaveAttribute("href", "/product/hp-pavilion-15");
  });

  it("answers an unknown link", async () => {
    api.GET.mockResolvedValueOnce(failure(404, "review_link_not_found"));
    renderPage();
    expect(await screen.findByRole("heading", { name: "This link isn’t valid" })).toBeInTheDocument();
  });

  it("switches to already reviewed when another tab sent the review first", async () => {
    api.GET.mockResolvedValue(info("open"));
    api.POST.mockResolvedValue(failure(409, "already_reviewed"));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByLabelText("5 stars"));
    await user.type(screen.getByLabelText(/Your review/), "Exactly as described, fast delivery.");
    await user.click(screen.getByRole("button", { name: "Submit review" }));
    expect(await screen.findByRole("heading", { name: "Already reviewed" })).toBeInTheDocument();
  });
});
