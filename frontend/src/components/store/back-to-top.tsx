"use client";

import { ArrowUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

/** How far down the page (px) before the button appears: past about one screen. */
export const BACK_TO_TOP_AFTER = 600;

/** "Back to top" (SC-09): a round button in the page corner, shown once the visitor has scrolled
 * down past BACK_TO_TOP_AFTER and hidden again near the top. It sits right above the WhatsApp
 * button, centred on it (above the phone tab bar on small screens), so the two never overlap.
 * Scrolls smoothly, or at once when the visitor prefers reduced motion. */
export function BackToTop() {
  const t = useTranslations("store");
  const [shown, setShown] = useState(false);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      setShown(window.scrollY > BACK_TO_TOP_AFTER);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  if (!shown) return null;
  return (
    <button
      type="button"
      aria-label={t("backToTop")}
      title={t("backToTop")}
      onClick={() => {
        const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
      }}
      className="fixed right-[22px] bottom-[152px] z-30 flex size-11 cursor-pointer animate-mega-in items-center justify-center rounded-full border border-bd bg-card text-tx shadow-sh2 transition-colors duration-150 hover:border-pri hover:text-pri-h motion-reduce:animate-none motion-reduce:transition-none sm:right-[38px] sm:bottom-[100px]"
    >
      <ArrowUp size={20} aria-hidden="true" />
    </button>
  );
}
