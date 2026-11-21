import type { NextRequest } from "next/server";
import { login } from "@/lib/auth-handlers";

export function POST(request: NextRequest) {
  return login(request);
}
