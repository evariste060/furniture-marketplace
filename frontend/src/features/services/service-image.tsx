"use client";

import Image from "next/image";
import { useState } from "react";
import type { ApiImage } from "@/lib/images";
import { cx } from "@/lib/cx";
import { ServiceIcon, type ServiceIconKey } from "./service-icon";

/** A service's photo, filling its box (object-fit: cover). Until staff upload a photo (or when it
 * fails to load) the placeholder shows: the brand's light tint with the service's icon. */
export function ServiceImage({
  image,
  icon,
  sizes,
  className,
  iconSize = 48,
  preload = false,
}: {
  image: ApiImage | null;
  icon: ServiceIconKey;
  sizes: string;
  className?: string;
  iconSize?: number;
  preload?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={cx("relative flex items-center justify-center overflow-hidden bg-light", className)}>
      {image && !failed ? (
        <Image src={image.url} alt="" fill sizes={sizes} preload={preload} onError={() => setFailed(true)} className="object-cover" />
      ) : (
        <span data-placeholder className="flex size-full items-center justify-center bg-gradient-to-br from-light to-white text-pri">
          <ServiceIcon icon={icon} size={iconSize} />
        </span>
      )}
    </span>
  );
}
