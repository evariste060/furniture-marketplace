"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

/** TanStack Query for interactive parts (cart, filters, admin). It calls the backend through the
 * /api/backend proxy (src/lib/api/client.ts); nothing it fetches is cached across users. */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
