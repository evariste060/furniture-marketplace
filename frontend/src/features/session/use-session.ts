"use client";

import { useQuery } from "@tanstack/react-query";
import type { SessionUser } from "@/lib/auth-handlers";

export const SESSION_KEY = ["session"] as const;

/** The signed-in user for the header, from /api/auth/session (never cached by the server; the
 * catalogue pages around it stay cacheable). */
export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: async (): Promise<SessionUser | null> => {
      const res = await fetch("/api/auth/session", { cache: "no-store" });
      if (!res.ok) throw new Error(`session ${res.status}`);
      return ((await res.json()) as { user: SessionUser | null }).user;
    },
    staleTime: 60_000,
  });
}

/** "Aline Uwase" → "Aline"; the header's account label. */
export function firstName(fullName: string | null | undefined): string | null {
  const first = fullName?.trim().split(/\s+/)[0];
  return first || null;
}
