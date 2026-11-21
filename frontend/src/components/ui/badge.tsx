import type { HTMLAttributes } from "react";
import { cx } from "@/lib/cx";

/** .badge: solid tones sit on product images; soft tones are for tables and the admin. */
export type BadgeTone =
  | "ok" | "warn" | "err" | "info" // solid: b-ok, b-warn, b-err, b-info
  | "soft-ok" | "soft-warn" | "soft-err" | "soft-info" | "soft-neutral" | "soft-purple"; // s-*

const TONES: Record<BadgeTone, string> = {
  // WCAG AA: white on --ok is 3.30:1, so solid green uses --ok-tx (5.02:1).
  ok: "bg-ok-tx text-white",
  warn: "bg-warn text-warn-ink",
  err: "bg-err text-white",
  info: "bg-pri text-white",
  "soft-ok": "bg-ok-bg text-ok-tx",
  "soft-warn": "bg-warn-bg text-warn-tx",
  "soft-err": "bg-err-bg text-err-tx",
  "soft-info": "bg-light text-pri-h", // --pri on --light is 4.44:1
  "soft-neutral": "bg-subtle text-tx2",
  "soft-purple": "bg-pur-bg text-pur",
};

export function Badge({
  tone = "soft-neutral",
  pill = false,
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone; pill?: boolean }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 px-2 py-[3px] text-cap font-semibold whitespace-nowrap",
        pill ? "rounded-full" : "rounded-sm",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}

/** .count: the small number on the cart icon. */
export function CountBadge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cx(
        "inline-block h-[18px] min-w-[18px] rounded-[9px] bg-pri px-[5px] text-center text-xs font-semibold text-white",
        className,
      )}
      {...props}
    />
  );
}
