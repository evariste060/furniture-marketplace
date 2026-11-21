import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { ServicesNav } from "@/components/store/services-nav";
import { EMPTY_REQUEST, firstErrorStep, serviceRequestServerErrors, stepErrors, validateServiceRequest, type ServiceRequestForm as Form } from "./request";
import { ServiceRequestWizard } from "./request-form";
import { promoIndex } from "./services-promo";
import { ServiceCard } from "./service-card";

/** Technical services (ADR-013): the request's rules, the step-by-step request wizard (from the
 * service through the confirmation), the service card and the "Services" nav dropdown. */

const nav = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  usePathname: () => nav.pathname,
}));
vi.mock("next/image", () => ({
  default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} />,
}));
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApi: api }));

const NOW = new Date("2026-11-17T10:00:00Z");
const FORM: Form = {
  ...EMPTY_REQUEST,
  fullName: " Aline Uwase ",
  phone: "788 123 456",
  clientType: "business",
};
const SERVICE = {
  slug: "cctv-security",
  name: "CCTV & Security Surveillance",
  short_description: "Cameras for homes and businesses.",
  icon: "cctv" as const,
  image: null,
};

function renderUi(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages} timeZone="Africa/Kigali">
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  nav.pathname = "/";
  api.GET.mockResolvedValue({
    data: { whatsapp: "+250 788 123 456", phone: "+250 788 123 456" },
    response: { ok: true, status: 200 },
  });
});
afterEach(() => vi.clearAllMocks());

describe("service request rules", () => {
  it("sends a valid form with blank optional fields as null", () => {
    const { errors, body } = validateServiceRequest(FORM, "rw", NOW);
    expect(errors).toEqual({});
    expect(body).toEqual({
      full_name: "Aline Uwase",
      phone: "0788123456",
      email: null,
      location: null,
      client_type: "business",
      message: null,
      preferred_date: null,
      locale: "rw",
      website: null,
    });
  });

  it("points at each mistake", () => {
    const { errors, body } = validateServiceRequest(
      {
        ...EMPTY_REQUEST,
        fullName: "A",
        phone: "0252 123 456",
        email: "nope",
        location: "x".repeat(121),
        preferredDate: "2026-11-16",
      },
      "en",
      NOW,
    );
    expect(body).toBeNull();
    expect(errors).toEqual({
      fullName: "tooShort",
      phone: "phoneInvalid",
      email: "emailInvalid",
      location: "tooLong",
      clientType: "clientTypeRequired",
      preferredDate: "dateInvalid",
    });
  });

  it("accepts a date from today up to one year ahead (Kigali)", () => {
    expect(validateServiceRequest({ ...FORM, preferredDate: "2026-11-17" }, "en", NOW).errors).toEqual({});
    expect(validateServiceRequest({ ...FORM, preferredDate: "2027-11-18" }, "en", NOW).errors).toEqual({});
    expect(validateServiceRequest({ ...FORM, preferredDate: "2027-11-19" }, "en", NOW).errors.preferredDate).toBe("dateInvalid");
  });

  it("passes the honeypot on for the server to drop", () => {
    expect(validateServiceRequest({ ...FORM, website: "spam" }, "en", NOW).body?.website).toBe("spam");
  });

  it("maps the server's 422 details onto the fields", () => {
    expect(serviceRequestServerErrors([{ loc: ["body", "phone"] }, { loc: ["body", "preferred_date"] }, { loc: ["query"] }])).toEqual({
      phone: "invalid",
      preferredDate: "dateInvalid",
    });
    expect(serviceRequestServerErrors(null)).toEqual({});
  });
});

describe("request wizard", () => {
  const WIZARD_SERVICE = {
    ...SERVICE,
    items: ["Camera installation", "Remote viewing"],
  };
  const continueButton = () => screen.getByRole("button", { name: "Continue" });
  const heading = (name: string) => screen.getByRole("heading", { level: 2, name });

  function renderWizard() {
    const user = userEvent.setup();
    renderUi(<ServiceRequestWizard service={WIZARD_SERVICE} />);
    return user;
  }

  async function toDetails(user: ReturnType<typeof userEvent.setup>) {
    await user.click(continueButton());
    await user.click(continueButton());
    expect(heading("Your details")).toBeInTheDocument();
  }

  async function fillDetails(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("Full name"), "Aline Uwase");
    await user.type(screen.getByLabelText("Phone number"), "788123456");
    await user.click(screen.getByRole("radio", { name: "A business" }));
  }

  it("splits the request into steps and checks each step before going on", () => {
    const { errors } = validateServiceRequest({ ...EMPTY_REQUEST, preferredDate: "2020-01-01" }, "en", NOW);
    expect(stepErrors(errors, "date")).toEqual({
      preferredDate: "dateInvalid",
    });
    expect(Object.keys(stepErrors(errors, "details")).sort()).toEqual(["clientType", "fullName", "phone"]);
    expect(firstErrorStep(errors)).toBe("date");
    expect(firstErrorStep({})).toBeNull();
  });

  it("starts with the service, then the date, marking the steps done", async () => {
    const user = renderWizard();
    expect(heading("Confirm the service")).toBeInTheDocument();
    expect(screen.getByText("Camera installation")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", "/services/cctv-security");
    await user.click(continueButton());
    expect(heading("Choose a date")).toBeInTheDocument();
    const steps = within(screen.getByRole("navigation", { name: "Request steps" }))
      .getAllByRole("listitem")
      .filter((li) => li.textContent);
    expect(steps.map((li) => li.textContent)).toEqual(["Service (completed)", "2Date", "3Your details", "4Review", "5Confirmation"]);
    expect(steps[1]).toHaveAttribute("aria-current", "step");
  });

  it("keeps the customer on a step until its required fields are right", async () => {
    const user = renderWizard();
    await toDetails(user);
    await user.click(continueButton());
    expect(screen.getAllByText("This field is required.")).toHaveLength(2);
    expect(screen.getByText("Choose who the service is for.")).toBeInTheDocument();
    expect(heading("Your details")).toBeInTheDocument();
  });

  it("keeps what was typed when going back and forth", async () => {
    const user = renderWizard();
    await toDetails(user);
    await fillDetails(user);
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(heading("Choose a date")).toBeInTheDocument();
    await user.click(continueButton());
    expect(screen.getByLabelText("Full name")).toHaveValue("Aline Uwase");
    expect(screen.getByRole("radio", { name: "A business" })).toBeChecked();
  });

  it("reviews, sends through the existing request and confirms with the reference and status", async () => {
    api.POST.mockResolvedValue({
      data: { reference: "SR-261117-ABCDEF" },
      response: { ok: true, status: 201 },
    });
    const user = renderWizard();
    await toDetails(user);
    await fillDetails(user);
    await user.click(continueButton());
    expect(heading("Review your request")).toBeInTheDocument();
    expect(screen.getByText("+250 788 123 456")).toBeInTheDocument();
    expect(screen.getByText("No preferred date")).toBeInTheDocument();
    expect(api.POST).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("heading", { name: "Request sent" })).toBeInTheDocument();
    expect(api.POST).toHaveBeenCalledWith("/api/v1/services/{slug}/requests", {
      params: { path: { slug: "cctv-security" } },
      body: expect.objectContaining({
        full_name: "Aline Uwase",
        phone: "0788123456",
        client_type: "business",
        locale: "en",
        preferred_date: null,
        website: null,
      }),
    });
    const done = screen.getByRole("status");
    expect(done).toHaveTextContent("SR-261117-ABCDEF");
    expect(done).toHaveTextContent("Received");
    expect(screen.getByRole("navigation", { name: "Request steps" }).querySelector("[aria-current=step]")).toHaveTextContent("Confirmation");
  });

  it("opens a section to edit from the review", async () => {
    const user = renderWizard();
    await toDetails(user);
    await fillDetails(user);
    await user.click(continueButton());
    await user.click(screen.getByRole("button", { name: /^Edits*Date$/ }));
    expect(heading("Choose a date")).toBeInTheDocument();
  });

  it("goes back to the step the server finds a mistake in", async () => {
    api.POST.mockResolvedValue({
      data: undefined,
      error: {
        error: {
          code: "validation_error",
          message: "x",
          details: [{ loc: ["body", "phone"] }],
        },
      },
      response: { ok: false, status: 422 },
    });
    const user = renderWizard();
    await toDetails(user);
    await fillDetails(user);
    await user.click(continueButton());
    await user.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Your details" })).toBeInTheDocument();
    expect(screen.getByText("Check this field.")).toBeInTheDocument();
  });

  it("says when too many requests were sent, and keeps the review", async () => {
    api.POST.mockResolvedValue({
      data: undefined,
      error: { error: { code: "rate_limited", message: "x" } },
      response: { ok: false, status: 429 },
    });
    const user = renderWizard();
    await toDetails(user);
    await fillDetails(user);
    await user.click(continueButton());
    await user.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests from this number");
    expect(heading("Review your request")).toBeInTheDocument();
  });
});

describe("service card and nav", () => {
  it("puts the two-place promotional card at the end of the 2nd row, or right after fewer services", () => {
    expect(promoIndex(12)).toBe(6);
    expect(promoIndex(6)).toBe(6);
    expect(promoIndex(3)).toBe(3);
  });

  const CARD_SERVICE = { ...SERVICE, items: Array.from({ length: 8 }, (_, i) => ({ id: `i${i}`, title: `Item ${i + 1}` })) };
  const face = (container: HTMLElement, name: "front" | "back") => container.querySelector(`[data-face=${name}]`) as HTMLElement;

  it("shows the service with Details and Book Now, like the product cards, and its back hidden", () => {
    const { container } = renderUi(<ServiceCard service={CARD_SERVICE} />);
    const heading = screen.getByRole("heading", { level: 2, name: SERVICE.name });
    expect(within(heading).getByRole("link")).toHaveAttribute("href", "/services/cctv-security");
    const front = within(face(container, "front"));
    expect(front.getByRole("link", { name: `Details: ${SERVICE.name}` })).toHaveAttribute("href", "/services/cctv-security");
    expect(front.getByRole("link", { name: `Book Now: ${SERVICE.name}` })).toHaveAttribute("href", "/services/cctv-security/request");
    expect(face(container, "back")).toHaveAttribute("inert");
    expect(face(container, "front")).not.toHaveAttribute("inert");
    expect(container.querySelector("[data-placeholder]")).not.toBeNull();
  });

  it("turns to What's included with a button (touch and keyboard), listing the service's own items", async () => {
    const user = userEvent.setup();
    const { container } = renderUi(<ServiceCard service={CARD_SERVICE} />);
    await user.click(screen.getByRole("button", { name: `See what’s included: ${SERVICE.name}` }));
    expect(face(container, "front")).toHaveAttribute("inert");
    expect(face(container, "back")).not.toHaveAttribute("inert");
    const back = within(face(container, "back"));
    expect(back.getByText("What’s included")).toBeInTheDocument();
    expect(back.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Item 1",
      "Item 2",
      "Item 3",
      "Item 4",
      "Item 5",
      "Item 6",
      "+ 2 more on the details page",
    ]);
    expect(back.getByRole("link", { name: `Book Now: ${SERVICE.name}` })).toHaveAttribute("href", "/services/cctv-security/request");
    await user.keyboard("{Escape}");
    expect(face(container, "back")).toHaveAttribute("inert");
  });

  it("turns on mouse hover only, and following a button does not turn it", () => {
    const { container } = renderUi(<ServiceCard service={CARD_SERVICE} />);
    const card = container.querySelector("article")!;
    fireEvent.pointerEnter(card, { pointerType: "touch" });
    expect(face(container, "back")).toHaveAttribute("inert");
    fireEvent.pointerEnter(card, { pointerType: "mouse" });
    expect(face(container, "back")).not.toHaveAttribute("inert");
    fireEvent.pointerLeave(card, { pointerType: "mouse" });
    expect(face(container, "back")).toHaveAttribute("inert");
    fireEvent.click(within(face(container, "front")).getByRole("link", { name: `Details: ${SERVICE.name}` }));
    expect(face(container, "back")).toHaveAttribute("inert");
  });

  it("says where to find the details when a service lists no items", async () => {
    const user = userEvent.setup();
    const { container } = renderUi(<ServiceCard service={{ ...SERVICE, items: [] }} />);
    await user.click(screen.getByRole("button", { name: `See what’s included: ${SERVICE.name}` }));
    expect(within(face(container, "back")).getByText(/See the details page or ask our team/)).toBeInTheDocument();
  });

  it("lists the services in the Services dropdown, with All services last", async () => {
    const user = userEvent.setup();
    renderUi(
      <ServicesNav
        services={[
          SERVICE,
          {
            ...SERVICE,
            slug: "electronics-repair",
            name: "Repair",
            icon: "wrench",
          },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "Services" })).toHaveAttribute("href", "/services");
    await user.click(screen.getByRole("button", { name: "Services menu" }));
    const links = within(screen.getByRole("region", { name: "Services menu" }))
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(links).toEqual(["/services/cctv-security", "/services/electronics-repair", "/services"]);
  });

  it("is a plain link without services", () => {
    renderUi(<ServicesNav services={[]} />);
    expect(screen.getByRole("link", { name: "Services" })).toHaveAttribute("href", "/services");
    expect(screen.queryByRole("button", { name: "Services menu" })).toBeNull();
  });

  it("marks Services on its pages", () => {
    nav.pathname = "/services/cctv-security";
    renderUi(<ServicesNav services={[SERVICE]} />);
    expect(screen.getByRole("link", { name: "Services" })).toHaveAttribute("aria-current", "page");
  });
});
