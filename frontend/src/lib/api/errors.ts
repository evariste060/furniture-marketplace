/** The backend's error body: {"error": {"code", "message", "details"}} (plan A3). */
export type ApiErrorBody = { error?: { code?: string; message?: string; details?: unknown } };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  static from(status: number, body: unknown): ApiError {
    const error = (body as ApiErrorBody | undefined)?.error;
    return new ApiError(
      status,
      error?.code ?? "unknown_error",
      error?.message ?? `Request failed (${status})`,
      error?.details,
    );
  }
}

/** The `reason` a 422 detail carries (e.g. promotion_not_applicable: "expired"), if any. */
export function detailReason(error: unknown): string | null {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return null;
  for (const detail of error.details as unknown[]) {
    const reason = (detail as { reason?: unknown } | null)?.reason;
    if (typeof reason === "string") return reason;
  }
  return null;
}
