import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setUnauthorizedHandler } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** A fetch double: the CSRF endpoint sets the cookie, other calls are scripted. */
function mockFetch(...responses: Response[]) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    if (String(input).endsWith("/auth/csrf/")) {
      document.cookie = `mf_csrftoken=token-${mock.mock.calls.length}; path=/`;
      return new Response(null, { status: 204 });
    }
    const next = responses.shift();
    if (!next) throw new Error(`Unexpected request to ${String(input)}`);
    return next;
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function headersOf(call: unknown[] | undefined): Record<string, string> {
  return ((call?.[1] as RequestInit | undefined)?.headers ?? {}) as Record<string, string>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

describe("api client", () => {
  it("sends reads without a CSRF token and with same-origin credentials", async () => {
    const fetchMock = mockFetch(json(200, { ok: true }));
    await expect(api("/auth/me/")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/me/");
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).credentials).toBe("same-origin");
    expect(headersOf(fetchMock.mock.calls[0])["X-CSRFToken"]).toBeUndefined();
  });

  it("obtains a CSRF token before the first write and sends it", async () => {
    const fetchMock = mockFetch(json(200, {}));
    await api("/auth/login/", { method: "POST", body: { email: "a@b.test", password: "x" } });
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toEqual([
      "/api/v1/auth/csrf/",
      "/api/v1/auth/login/",
    ]);
    expect(headersOf(fetchMock.mock.calls[1])["X-CSRFToken"]).toBe("token-1");
  });

  it("refreshes a stale CSRF token once and retries", async () => {
    document.cookie = "mf_csrftoken=stale; path=/";
    const fetchMock = mockFetch(
      json(403, { code: "csrf_failed", detail: "CSRF verification failed." }),
      new Response(null, { status: 204 }),
    );
    await expect(api("/auth/logout/", { method: "POST" })).resolves.toBeUndefined();
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual(["/api/v1/auth/logout/", "/api/v1/auth/csrf/", "/api/v1/auth/logout/"]);
    expect(headersOf(fetchMock.mock.calls[0])["X-CSRFToken"]).toBe("stale");
    expect(headersOf(fetchMock.mock.calls[2])["X-CSRFToken"]).not.toBe("stale");
  });

  it("turns the API error format into an ApiError with field errors", async () => {
    mockFetch(
      json(400, {
        code: "validation_error",
        detail: "The submitted data is not valid.",
        errors: { email: ["Enter a valid email address."] },
      }),
    );
    const error = await api("/auth/me/").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 400,
      code: "validation_error",
      fieldErrors: { email: ["Enter a valid email address."] },
    });
  });

  it("reports an unreachable server as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api("/auth/me/")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("notifies the session when the server answers 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(json(401, { code: "not_authenticated", detail: "Sign in." }));
    await expect(api("/workspaces/")).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not treat a failed login as an expired session", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(json(401, { code: "invalid_credentials", detail: "Incorrect email or password." }));
    await expect(api("/auth/me/", { skipUnauthorizedHandler: true })).rejects.toMatchObject({
      code: "invalid_credentials",
    });
    expect(handler).not.toHaveBeenCalled();
  });
});
