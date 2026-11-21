"use client";

import Image from "next/image";
import { useState } from "react";
import { Package } from "lucide-react";
import { cx } from "@/lib/cx";
import type { ApiImage } from "@/lib/images";

/** A product, category or brand image from the API in a fixed box (the design's .imgbox), shown
 * whole (object-fit: contain). A missing or broken image becomes the neutral placeholder: a light
 * grey box with the package icon, never a broken-image icon. */
export function ProductImage({
  image,
  sizes,
  alt,
  className,
  iconSize = 32,
  preload = false,
}: {
  image: ApiImage | null;
  /** From IMAGE_SIZES in src/lib/images.ts. */
  sizes: string;
  /** Overrides the API's alt text (e.g. "" when a link next to it already names the product). */
  alt?: string;
  className?: string;
  iconSize?: number;
  preload?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={cx("relative flex flex-none items-center justify-center overflow-hidden rounded-img bg-page", className)}>
      {image && !failed ? (
        <Image
          src={image.url}
          alt={alt ?? image.alt}
          fill
          sizes={sizes}
          preload={preload}
          onError={() => setFailed(true)}
          className="object-contain"
        />
      ) : (
        <Package size={iconSize} strokeWidth={1.5} className="text-bd2" aria-hidden="true" />
      )}
    </span>
  );
}
