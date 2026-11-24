"use client";

import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

/** .toggle: an on/off switch. */
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
  className,
}: {
  checked: boolean;
  onChange?: (next: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label className={cx("inline-flex cursor-pointer items-center gap-2 text-sm", className)}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange?.(!checked)}
        className={cx(
          "relative h-[22px] w-10 flex-none cursor-pointer rounded-[11px] border-0 p-0 disabled:cursor-not-allowed disabled:opacity-45",
          checked ? "bg-pri" : "bg-bd2",
        )}
      >
        <span
          aria-hidden="true"
          className={cx("absolute top-[3px] size-4 rounded-full bg-card", checked ? "left-[21px]" : "left-[3px]")}
        />
      </button>
      {label}
    </label>
  );
}
