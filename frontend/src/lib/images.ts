/** All image URL logic lives here (ADR-009). Today next/image's own optimizer resizes the URL the
 * API returns; the Cloudflare Image Transformations loader is added here when R2 is set up. */

export type ApiImage = {
  url: string;
  width: number;
  height: number;
  alt: string;
  position: number;
};

/** The image with the lowest position, or null when there is none. */
export function primaryImage(images: readonly ApiImage[] | null | undefined): ApiImage | null {
  if (!images?.length) return null;
  return [...images].sort((a, b) => a.position - b.position)[0];
}

/** `sizes` for common boxes, so the browser picks the right width from 400/800/1600. */
export const IMAGE_SIZES = {
  card: "(max-width: 700px) 50vw, 240px",
  gallery: "(max-width: 700px) 100vw, 600px",
  thumb: "80px",
  /** The listing card's photo: 128–160px wide by the card's width (listing-card.tsx). */
  listing: "160px",
  hero: "(max-width: 700px) 100vw, 50vw",
} as const;
