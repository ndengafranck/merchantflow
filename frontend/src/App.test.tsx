import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Membership } from "./api/types";
import { SessionProvider } from "./session/SessionProvider";

const user = { id: "u1", email: "owner@example.test", full_name: "Awa Owner", phone: "" };

function membership(id: string, name: string, role: Membership["role"]): Membership {
  return {
    id: `m-${id}`,
    role,
    status: "active",
    workspace: { id, name, slug: id, status: "active", currency: "XAF" },
    capabilities: [],
  };
}

type Handler = (init?: RequestInit) => { status: number; body?: unknown };

/** Minimal in-memory backend keyed by "METHOD path". */
function serve(routes: Record<string, Handler>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${String(input).replace("/api/v1", "")}`;
      calls.push(key);
      if (key === "GET /auth/csrf/") {
        document.cookie = "mf_csrftoken=test-token; path=/";
        return new Response(null, { status: 204 });
      }
      const handler = routes[key];
      if (!handler) throw new Error(`No handler for ${key}`);
      const { status, body } = handler(init);
      return new Response(body === undefined ? null : JSON.stringify(body), { status });
    }),
  );
  return calls;
}

function renderApp(path = "/") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}

const anonymous: Record<string, Handler> = {
  "GET /auth/me/": () => ({ status: 401, body: { code: "not_authenticated", detail: "No." } }),
};

afterEach(() => vi.unstubAllGlobals());

describe("signed-out visitor", () => {
  it("is shown the login screen after the loading state", async () => {
    serve(anonymous);
    renderApp("/");
    expect(screen.getByRole("status")).toHaveTextContent("Starting MerchantFlow");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("gets validation messages without a request being sent", async () => {
    const calls = serve(anonymous);
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(calls).not.toContain("POST /auth/login/");
  });

  it("sees the server's message when credentials are wrong", async () => {
    serve({
      ...anonymous,
      "POST /auth/login/": () => ({
        status: 401,
        body: { code: "invalid_credentials", detail: "Incorrect email or password." },
      }),
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "owner@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });
});

describe("signed-in user", () => {
  it("with one workspace lands on the dashboard and can sign out", async () => {
    const akwa = membership("w1", "Akwa Phones", "owner");
    const calls = serve({
      "GET /auth/me/": () => ({ status: 200, body: user }),
      "GET /workspaces/": () => ({
        status: 200,
        body: { current_workspace_id: null, memberships: [akwa] },
      }),
      "PUT /workspaces/current/": () => ({ status: 200, body: akwa }),
      "GET /workspaces/w1/": () => ({ status: 200, body: akwa }),
      "POST /auth/logout/": () => ({ status: 204 }),
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(calls).toContain("PUT /workspaces/current/");
    expect(screen.getByText("Awa Owner")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("with several workspaces must choose one", async () => {
    const akwa = membership("w1", "Akwa Phones", "owner");
    const bonanjo = membership("w2", "Bonanjo Mobile", "affiliate");
    let selected: unknown;
    serve({
      "GET /auth/me/": () => ({ status: 200, body: user }),
      "GET /workspaces/": () => ({
        status: 200,
        body: { current_workspace_id: null, memberships: [akwa, bonanjo] },
      }),
      "PUT /workspaces/current/": (init) => {
        selected = JSON.parse(String(init?.body));
        return { status: 200, body: bonanjo };
      },
      "GET /workspaces/w2/": () => ({ status: 200, body: bonanjo }),
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Choose a workspace" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Bonanjo Mobile/ }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(selected).toEqual({ workspace_id: "w2" });
    expect(screen.getByRole("link", { name: "Switch workspace" })).toBeInTheDocument();
  });

  it("with no workspace sees an empty state", async () => {
    serve({
      "GET /auth/me/": () => ({ status: 200, body: user }),
      "GET /workspaces/": () => ({
        status: 200,
        body: { current_workspace_id: null, memberships: [] },
      }),
    });
    renderApp("/");
    expect(await screen.findByText("No workspaces yet")).toBeInTheDocument();
  });

  it("is returned to login when the session expires mid-use", async () => {
    const akwa = membership("w1", "Akwa Phones", "owner");
    serve({
      "GET /auth/me/": () => ({ status: 200, body: user }),
      "GET /workspaces/": () => ({
        status: 200,
        body: { current_workspace_id: "w1", memberships: [akwa] },
      }),
      "GET /workspaces/w1/": () => ({
        status: 401,
        body: { code: "not_authenticated", detail: "Session ended." },
      }),
    });
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows a retryable error when the dashboard request fails", async () => {
    const akwa = membership("w1", "Akwa Phones", "owner");
    let attempts = 0;
    serve({
      "GET /auth/me/": () => ({ status: 200, body: user }),
      "GET /workspaces/": () => ({
        status: 200,
        body: { current_workspace_id: "w1", memberships: [akwa] },
      }),
      "GET /workspaces/w1/": () =>
        ++attempts === 1
          ? { status: 500, body: { code: "error", detail: "Server error." } }
          : { status: 200, body: akwa },
    });
    renderApp("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument(),
    );
  });
});

describe("startup failure", () => {
  it("shows an error state when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderApp("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server");
  });
});
