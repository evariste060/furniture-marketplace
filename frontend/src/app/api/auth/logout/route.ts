import type { NextRequest } from "next/server";
import { logout } from "@/lib/auth-handlers";

export function POST(request: NextRequest) {
  return logout(request);
}
