import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../../../messages/en.json";
import { BACK_TO_TOP_AFTER, BackToTop } from "./back-to-top";

function scrollTo(y: number) {
  Object.defineProperty(window, "scrollY", { value: y, configurable: true });
  fireEvent.scroll(window);
}

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
});

describe("Back to top (SC-09)", () => {
  it("appears only after scrolling down, and scrolls back to the top", async () => {
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      cb(0);
      return 0; // already run: nothing pending
    });
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    render(
      <NextIntlClientProvider locale="en" messages={en}>
        <BackToTop />
      </NextIntlClientProvider>,
    );
    expect(screen.queryByRole("button", { name: en.store.backToTop })).toBeNull();

    await act(async () => scrollTo(BACK_TO_TOP_AFTER + 1));
    fireEvent.click(screen.getByRole("button", { name: en.store.backToTop }));
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }));

    await act(async () => scrollTo(100));
    expect(screen.queryByRole("button", { name: en.store.backToTop })).toBeNull();
  });
});
