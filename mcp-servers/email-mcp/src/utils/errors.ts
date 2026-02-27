export enum EmailError {
  AUTH_FAILED = "Authentication failed — check credentials.json and token.json",
  TOKEN_EXPIRED = "Token expired — re-run Gmail Watcher to refresh",
  INVALID_RECIPIENT = "Invalid recipient email address",
  QUOTA_EXCEEDED = "Gmail API quota exceeded — retry later",
  RATE_LIMITED = "Rate limited by Gmail API — wait 60 seconds",
  THREAD_NOT_FOUND = "Thread ID not found — it may have been deleted",
  NETWORK_ERROR = "Network error — check internet connection",
  UNKNOWN = "Unexpected error",
}

export function errorResponse(
  error: EmailError,
  detail?: string,
): { content: Array<{ type: "text"; text: string }>; isError: true } {
  return {
    content: [
      {
        type: "text" as const,
        text: `Error: ${error}${detail ? `\nDetail: ${detail}` : ""}`,
      },
    ],
    isError: true,
  };
}

export function handleGmailError(error: unknown): never {
  const err = error as {
    response?: { status?: number };
    code?: number;
    message?: string;
  };
  const status = err?.response?.status ?? err?.code;

  switch (status) {
    case 401:
      throw new Error(EmailError.AUTH_FAILED);
    case 403:
      throw new Error(EmailError.QUOTA_EXCEEDED);
    case 429:
      throw new Error(EmailError.RATE_LIMITED);
    case 404:
      throw new Error(EmailError.THREAD_NOT_FOUND);
    default:
      if (
        err.message?.includes("ENOTFOUND") ||
        err.message?.includes("ETIMEDOUT")
      ) {
        throw new Error(EmailError.NETWORK_ERROR);
      }
      throw new Error(
        `${EmailError.UNKNOWN}: ${err.message ?? "Unknown error"}`,
      );
  }
}

export function catchToErrorResponse(error: unknown): {
  content: Array<{ type: "text"; text: string }>;
  isError: true;
} {
  const message =
    error instanceof Error ? error.message : "An unexpected error occurred";
  return {
    content: [{ type: "text", text: `Error: ${message}` }],
    isError: true,
  };
}
