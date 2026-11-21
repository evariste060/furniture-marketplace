import type { HTMLAttributes } from "react";
import { cx } from "@/lib/cx";

/** A grey block in the shape of content that is loading. Give it the real element's size so the
 * page does not move when the content arrives. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return <span aria-hidden="true" className={cx("block animate-pulse rounded-lg bg-subtle", className)} {...props} />;
}
