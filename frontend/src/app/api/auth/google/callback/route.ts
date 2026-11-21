import type { NextRequest } from "next/server";
import { googleCallback } from "@/lib/google-auth-handlers";

/** Google's redirect back after Continue with Google (GOOGLE_OAUTH_REDIRECT_URI on the backend). */
export function GET(request: NextRequest) {
  return googleCallback(request);
}
