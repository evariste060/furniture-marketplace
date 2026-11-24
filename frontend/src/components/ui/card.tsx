import type { HTMLAttributes } from "react";
import { cx } from "@/lib/cx";

const PADDING = { none: "", 16: "p-4", 20: "p-5", 24: "p-6", 32: "p-8" } as const;

/** .card: white, 1px border, 12px radius; optional .sh shadow. */
export function Card({
  padding = "none",
  shadow = false,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & { padding?: keyof typeof PADDING; shadow?: boolean }) {
  return (
    <div
      className={cx("rounded-xl border border-bd bg-card", PADDING[padding], shadow && "shadow-sh", className)}
      {...props}
    />
  );
}
