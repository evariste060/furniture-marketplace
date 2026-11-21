import type { NextRequest } from "next/server";
import { logoutEverywhere } from "@/lib/auth-handlers";

export function POST(request: NextRequest) {
  return logoutEverywhere(request);
}
