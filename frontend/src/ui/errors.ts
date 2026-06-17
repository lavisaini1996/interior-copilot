export type ErrorKind = "expense_cap" | "network" | "generic";

export class ApiError extends Error {
  readonly kind: ErrorKind;
  readonly status?: number;

  constructor(message: string, kind: ErrorKind, status?: number) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }
}

export const EXPENSE_CAP_MESSAGE =
  "AI usage expense cap reached. Image and design generation are paused until your API quota resets or billing is updated. Try again later, or ask your admin to increase the limit.";

export const NETWORK_ERROR_MESSAGE =
  "Cannot reach the AI service. Check your internet connection, disable VPN/proxy if misconfigured, and retry.";

const EXPENSE_CAP_MARKERS = [
  "expense cap",
  "spending cap",
  "quota exceeded",
  "exceeded your current quota",
  "resource_exhausted",
  "resource exhausted",
  "rate limit",
  "rate_limit",
  "too many requests",
  "billing",
  "paid plan",
  "insufficient quota",
  "quota limit",
  "billing account",
  "budget exceeded",
  "usage limit",
];

const NETWORK_MARKERS = [
  "cannot reach the ai provider",
  "getaddrinfo failed",
  "network error",
  "connection refused",
  "failed to fetch",
  "name or service not known",
];

export function classifyErrorMessage(message: string, status?: number): ErrorKind {
  const low = message.toLowerCase();
  if (status === 429) return "expense_cap";
  if (EXPENSE_CAP_MARKERS.some((m) => low.includes(m))) return "expense_cap";
  if (status === 503 || NETWORK_MARKERS.some((m) => low.includes(m))) return "network";
  return "generic";
}

export function parseApiErrorResponse(status: number, body: string): ApiError {
  let detail = (body || "").trim();
  if (detail) {
    try {
      const json = JSON.parse(detail) as { detail?: unknown };
      if (typeof json.detail === "string") {
        detail = json.detail;
      } else if (Array.isArray(json.detail)) {
        detail = json.detail
          .map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
            return JSON.stringify(item);
          })
          .join("\n");
      } else if (json.detail != null) {
        detail = String(json.detail);
      }
    } catch {
      // keep raw body
    }
  }

  if (!detail) detail = `Request failed (HTTP ${status})`;
  const kind = classifyErrorMessage(detail, status);
  const message =
    kind === "expense_cap" ? EXPENSE_CAP_MESSAGE : kind === "network" ? NETWORK_ERROR_MESSAGE : detail;
  return new ApiError(message, kind, status);
}

export type UiError = {
  title: string;
  message: string;
  kind: ErrorKind;
};

export function toUiError(e: unknown): UiError {
  if (e instanceof ApiError) {
    return {
      title: errorTitle(e.kind),
      message: e.message,
      kind: e.kind,
    };
  }

  const message = e instanceof Error ? e.message : String(e);
  const kind = classifyErrorMessage(message);
  return {
    title: errorTitle(kind),
    message:
      kind === "expense_cap" ? EXPENSE_CAP_MESSAGE : kind === "network" ? NETWORK_ERROR_MESSAGE : message,
    kind,
  };
}

function errorTitle(kind: ErrorKind): string {
  if (kind === "expense_cap") return "Expense cap reached";
  if (kind === "network") return "Connection problem";
  return "Something went wrong";
}
