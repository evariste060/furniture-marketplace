import type { NextRequest } from "next/server";
import { session } from "@/lib/auth-handlers";

export function GET(request: NextRequest) {
  return session(request);
}
