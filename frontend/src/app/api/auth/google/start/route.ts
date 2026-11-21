import type { NextRequest } from "next/server";
import { googleStart } from "@/lib/google-auth-handlers";

export function POST(request: NextRequest) {
  return googleStart(request);
}
