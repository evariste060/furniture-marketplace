"use client";

import { ErrorView } from "@/features/errors/error-view";

/** ServerError.dc.html when a page fails to render. */
export default function PageError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <ErrorView {...props} />;
}
