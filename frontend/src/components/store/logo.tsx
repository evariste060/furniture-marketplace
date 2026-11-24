import { Sofa } from "lucide-react";
import { cx } from "@/lib/cx";
import { MARKETPLACE_NAME } from "@/lib/marketplace";

/** The marketplace's wordmark (ADR-014 phase 6): a sofa mark and the configured name
 * (lib/marketplace.ts). It stands in for a logo until FurniHub artwork is approved; it is drawn,
 * not an image, so a rename needs no new file. `height` is the mark's size; the name is set
 * beside it. `eager` is kept for the callers of the old image logo and has no effect. */
export function Logo({ height, alt, className }: { height: number; alt: string; className?: string; eager?: boolean }) {
  return (
    <span
      role={alt ? "img" : undefined}
      aria-label={alt || undefined}
      aria-hidden={alt ? undefined : true}
      className={cx("inline-flex items-center gap-2 font-extrabold whitespace-nowrap text-head", className)}
      style={{ height, fontSize: Math.round(height * 0.52), lineHeight: 1 }}
    >
      <span className="flex flex-none items-center justify-center rounded-[22%] bg-pri text-white" style={{ width: height * 0.82, height: height * 0.82 }}>
        <Sofa size={Math.round(height * 0.5)} strokeWidth={2.25} aria-hidden="true" />
      </span>
      <span className="tracking-tight">{MARKETPLACE_NAME}</span>
    </span>
  );
}
