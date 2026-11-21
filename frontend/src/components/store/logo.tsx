import Image from "next/image";
import { cx } from "@/lib/cx";

/** The real logo (1600 × 625). On white it multiplies into the background; on navy it sits on a
 * white plate (the footer). `eager` loads it at once where it is the largest thing above the fold. */
export function Logo({ height, alt, className, eager }: { height: number; alt: string; className?: string; eager?: boolean }) {
  return (
    <Image
      src="/brand/3sixty-logo.jpeg"
      alt={alt}
      width={Math.round((height * 1600) / 625)}
      height={height}
      loading={eager ? "eager" : undefined}
      className={cx("block w-auto mix-blend-multiply", className)}
      style={{ height }}
    />
  );
}
