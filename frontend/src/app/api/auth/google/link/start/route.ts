import type { NextRequest } from "next/server";
import { googleLinkStart } from "@/lib/google-auth-handlers";

export function POST(request: NextRequest) {
  return googleLinkStart(request);
}
