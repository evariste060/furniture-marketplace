import type { NextRequest } from "next/server";
import { register } from "@/lib/auth-handlers";

export function POST(request: NextRequest) {
  return register(request);
}
