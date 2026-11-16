// The only module that talks HTTP. Authentication is a session cookie the
// browser attaches by itself and that this code can never read (HttpOnly).
// The one thing we handle is the CSRF token, which is not a credential.

const API_ROOT = "/api/v1";
const CSRF_COOKIE = "mf_csrftoken";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: FieldErrors;

  constructor(status: number, code: string, message: string, fieldErrors: FieldErrors = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
  }
}

/** Message suitable for showing to a user, whatever was thrown. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Please try again.";
}

let onUnauthorized: (() => void) | null = null;

/** Called when the server says the session has ended (any 401 outside login). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

function readCookie(name: string): string | null {
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return null;
}

async function csrfToken(forceRefresh = false): Promise<string> {
  if (forceRefresh || !readCookie(CSRF_COOKIE)) {
    await fetch(`${API_ROOT}/auth/csrf/`, { credentials: "same-origin" });
  }
  return readCookie(CSRF_COOKIE) ?? "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Extra headers, for example X-Device-Id on synchronisation calls. */
  headers?: Record<string, string>;
  /** Set for the login call, where a 401 means "wrong password". */
  skipUnauthorizedHandler?: boolean;
}

async function send(path: string, options: RequestOptions, freshCsrf: boolean): Promise<Response> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) headers["X-CSRFToken"] = await csrfToken(freshCsrf);
  return fetch(`${API_ROOT}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: { code?: unknown; detail?: unknown; errors?: unknown } = {};
  try {
    payload = await response.json();
  } catch {
    // Not JSON (for example a proxy error page): fall through to the generic message.
  }
  const code = typeof payload.code === "string" ? payload.code : "error";
  const detail =
    typeof payload.detail === "string" && payload.detail
      ? payload.detail
      : `The server could not complete the request (${response.status}).`;
  const fieldErrors =
    payload.errors && typeof payload.errors === "object" ? (payload.errors as FieldErrors) : {};
  return new ApiError(response.status, code, detail, fieldErrors);
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await send(path, options, false);
    if (response.status === 403) {
      const error = await parseError(response.clone());
      // A stale CSRF token (another tab signed in or out): refresh it once.
      if (error.code === "csrf_failed") response = await send(path, options, true);
    }
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check your connection.");
  }

  if (response.ok) {
    return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  }
  if (response.status === 401 && !options.skipUnauthorizedHandler) onUnauthorized?.();
  throw await parseError(response);
}
