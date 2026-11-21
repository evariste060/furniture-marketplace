"use client";

import { ErrorView } from "@/features/errors/error-view";

const SAMPLE = Object.assign(new Error("Preview of the error page"), { digest: "1234567890" });

/** Development only: the storefront error state (ServerError.dc.html), which otherwise shows only
 * when a page fails, drawn here for review and the browser tests. */
export default function StoreErrorPreview() {
  return <ErrorView error={SAMPLE} reset={() => undefined} />;
}
