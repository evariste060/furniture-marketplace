import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Badge } from "./badge";
import { Breadcrumb } from "./breadcrumb";
import { Button, buttonClasses } from "./button";
import { Field, Input, RadioOption } from "./form";
import { Pagination } from "./pagination";
import { ProductImage } from "./product-image";
import { Tabs } from "./tabs";
import { ToastProvider, useToast } from "./toast";
import { Toggle } from "./toggle";

vi.mock("next/image", () => ({
  default: (props: { src: string; alt: string; onError: () => void }) => <img src={props.src} alt={props.alt} onError={props.onError} />,
}));

describe("Button", () => {
  it("renders a real button of type button with the design's classes", () => {
    render(<Button variant="outline">Outline</Button>);
    const button = screen.getByRole("button", { name: "Outline" });
    expect(button).toHaveAttribute("type", "button");
    expect(button.className).toContain("border-pri/45");
    expect(buttonClasses({ size: "lg" })).toContain("h-13");
  });
});

describe("Badge", () => {
  it("uses the solid and soft tones", () => {
    render(
      <>
        <Badge tone="ok">In Stock</Badge>
        <Badge tone="soft-warn">Pending payment</Badge>
      </>,
    );
    expect(screen.getByText("In Stock").className).toContain("bg-ok-tx");
    expect(screen.getByText("Pending payment").className).toContain("bg-warn-bg");
  });
});

describe("Field", () => {
  it("labels the control and links its error text", () => {
    render(<Field label="Phone" error="Enter a valid Rwandan phone number">{(p) => <Input {...p} />}</Field>);
    const input = screen.getByLabelText("Phone");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a valid Rwandan phone number");
  });
});

describe("RadioOption and Toggle", () => {
  it("keeps native radio behaviour", async () => {
    render(
      <div role="radiogroup" aria-label="Type">
        <RadioOption name="t" label="Add stock" defaultChecked />
        <RadioOption name="t" label="Remove stock" />
      </div>,
    );
    await userEvent.click(screen.getByText("Remove stock"));
    expect(screen.getByRole("radio", { name: "Remove stock" })).toBeChecked();
  });

  it("is a switch with its state", async () => {
    function Demo() {
      const [on, setOn] = useState(false);
      return <Toggle checked={on} onChange={setOn} label="Active" />;
    }
    render(<Demo />);
    const toggle = screen.getByRole("switch", { name: "Active" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});

describe("Tabs", () => {
  it("switches with clicks and arrow keys", async () => {
    render(
      <Tabs
        label="Details"
        items={[
          { id: "a", label: "Specifications", content: "Spec panel" },
          { id: "b", label: "Description", content: "Description panel" },
        ]}
      />,
    );
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Spec panel");
    screen.getByRole("tab", { name: "Specifications" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Description" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Description" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Description panel");
  });
});

describe("Breadcrumb and Pagination", () => {
  it("marks the current page", () => {
    render(<Breadcrumb label="Breadcrumb" items={[{ label: "Home", href: "/" }, { label: "Phones" }]} />);
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByText("Phones")).toHaveAttribute("aria-current", "page");
  });

  it("links pages and disables previous on the first page", () => {
    render(
      <Pagination
        total={30}
        page={1}
        size={10}
        hrefFor={(n) => `/c?page=${n}`}
        labels={{ nav: "Pagination", previous: "Previous", next: "Next", page: (n) => `Page ${n}` }}
      />,
    );
    expect(screen.getByRole("link", { name: "Page 1" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute("href", "/c?page=2");
    expect(screen.queryByRole("link", { name: "Previous" })).toBeNull();
  });

  it("renders nothing for a single page", () => {
    const { container } = render(
      <Pagination total={3} page={1} size={10} hrefFor={String} labels={{ nav: "P", previous: "<", next: ">", page: String }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ProductImage", () => {
  it("shows the placeholder when there is no image or it fails to load", async () => {
    const { container, rerender } = render(<ProductImage image={null} sizes="80px" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
    rerender(<ProductImage image={{ url: "http://x/a.jpg", width: 1, height: 1, alt: "Phone", position: 0 }} sizes="80px" />);
    const img = screen.getByAltText("Phone");
    await act(async () => img.dispatchEvent(new Event("error")));
    expect(screen.queryByAltText("Phone")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("Toast", () => {
  it("announces messages in a polite status region", async () => {
    function Trigger() {
      const toast = useToast();
      return <button onClick={() => toast.show("Saved")}>Save</button>;
    }
    render(
      <ToastProvider closeLabel="Close">
        <Trigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});
