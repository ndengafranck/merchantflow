import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
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

const akwa = membership("w1", "Akwa Phones", "owner");
const bonanjo = membership("w2", "Bonanjo Mobile", "affiliate");

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

/** A signed-in backend with the given memberships. */
function signedIn(memberships: Membership[], last: string | null = null): Record<string, Handler> {
  const routes: Record<string, Handler> = {
    "GET /auth/me/": () => ({ status: 200, body: user }),
    "GET /workspaces/": () => ({
      status: 200,
      body: { current_workspace_id: last, memberships },
    }),
    "PUT /workspaces/current/": () => ({ status: 200, body: memberships[0] }),
    "POST /auth/logout/": () => ({ status: 204 }),
  };
  for (const m of memberships) {
    routes[`GET /workspaces/${m.workspace.id}/`] = () => ({ status: 200, body: m });
  }
  return routes;
}

const anonymous: Record<string, Handler> = {
  "GET /auth/me/": () => ({ status: 401, body: { code: "not_authenticated", detail: "No." } }),
};

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
}

const path = () => screen.getByTestId("location").textContent;

function renderApp(initialPath = "/") {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SessionProvider>
        <App />
        <LocationProbe />
      </SessionProvider>
    </MemoryRouter>,
  );
}

async function dashboardFor(name: string) {
  await screen.findByRole("heading", { name: "Dashboard" });
  // The stat card is filled from the workspace-scoped request, not from memory.
  expect(screen.getByTestId("stat-workspace")).toHaveTextContent(name);
}

afterEach(() => vi.unstubAllGlobals());

describe("signed-out visitor", () => {
  it("is shown the login screen after the loading state", async () => {
    serve(anonymous);
    renderApp("/");
    expect(screen.getByRole("status")).toHaveTextContent("Starting MerchantFlow");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(path()).toBe("/login");
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

  it("returns to the workspace page that was asked for after signing in", async () => {
    let loggedIn = false;
    const routes = signedIn([akwa, bonanjo]);
    serve({
      ...routes,
      "GET /auth/me/": () =>
        loggedIn ? { status: 200, body: user } : anonymous["GET /auth/me/"]!(),
      "POST /auth/login/": () => {
        loggedIn = true;
        return { status: 200, body: user };
      },
    });
    renderApp("/w/w2");
    await userEvent.type(await screen.findByLabelText("Email"), "owner@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "a-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await dashboardFor("Bonanjo Mobile");
    expect(path()).toBe("/w/w2");
  });
});

describe("landing page", () => {
  it("someone with one workspace goes straight to it", async () => {
    const calls = serve(signedIn([akwa]));
    renderApp("/");
    await dashboardFor("Akwa Phones");
    expect(path()).toBe("/w/w1");
    expect(screen.queryByRole("link", { name: "Switch workspace" })).not.toBeInTheDocument();
    await waitFor(() => expect(calls).toContain("PUT /workspaces/current/"));
  });

  it("someone with several workspaces chooses, and the choice is a URL", async () => {
    serve(signedIn([akwa, bonanjo]));
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Choose a workspace" })).toBeInTheDocument();
    expect(path()).toBe("/workspaces");
    const option = screen.getByRole("link", { name: /Bonanjo Mobile/ });
    expect(option).toHaveAttribute("href", "/w/w2");
    await userEvent.click(option);
    await dashboardFor("Bonanjo Mobile");
    expect(path()).toBe("/w/w2");
  });

  it("returns to the workspace used last", async () => {
    serve(signedIn([akwa, bonanjo], "w2"));
    renderApp("/");
    await dashboardFor("Bonanjo Mobile");
    expect(path()).toBe("/w/w2");
  });

  it("someone with no workspace sees an empty state", async () => {
    serve(signedIn([]));
    renderApp("/");
    expect(await screen.findByText("No workspaces yet")).toBeInTheDocument();
  });
});

describe("workspace in the URL", () => {
  it("decides what is shown, whatever the session used last", async () => {
    // Another tab has since moved the session's "last used" to w2.
    const calls = serve(signedIn([akwa, bonanjo], "w2"));
    renderApp("/w/w1");
    await dashboardFor("Akwa Phones");
    expect(path()).toBe("/w/w1");
    expect(calls).toContain("GET /workspaces/w1/");
    expect(calls).not.toContain("GET /workspaces/w2/");
  });

  it("switching workspace discards the previous workspace's data", async () => {
    const calls = serve(signedIn([akwa, bonanjo]));
    renderApp("/w/w1");
    await dashboardFor("Akwa Phones");

    await userEvent.click(screen.getByRole("link", { name: "Switch workspace" }));
    await userEvent.click(await screen.findByRole("link", { name: /Bonanjo Mobile/ }));

    await dashboardFor("Bonanjo Mobile");
    expect(path()).toBe("/w/w2");
    expect(screen.queryByText("Akwa Phones")).not.toBeInTheDocument();
    expect(calls.filter((c) => c === "GET /workspaces/w2/")).toHaveLength(1);
  });

  it("an unknown or foreign workspace id shows a not-available state", async () => {
    const calls = serve(signedIn([akwa]));
    renderApp("/w/not-mine");
    expect(await screen.findByText("Workspace not available")).toBeInTheDocument();
    expect(path()).toBe("/w/not-mine");
    expect(calls).not.toContain("GET /workspaces/not-mine/");
    expect(calls).not.toContain("PUT /workspaces/current/");
    expect(screen.getByRole("link", { name: "Choose a workspace" })).toHaveAttribute(
      "href",
      "/workspaces",
    );
  });

  it("navigation links stay inside the workspace", async () => {
    serve(signedIn([akwa, bonanjo]));
    renderApp("/w/w2/anything-unknown");
    await dashboardFor("Bonanjo Mobile");
    expect(path()).toBe("/w/w2");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/w/w2");
  });
});

describe("session end", () => {
  it("signing out goes to login and does not carry the old page to the next user", async () => {
    let loggedIn = true;
    serve({
      ...signedIn([akwa, bonanjo]),
      "GET /auth/me/": () =>
        loggedIn ? { status: 200, body: user } : anonymous["GET /auth/me/"]!(),
      "POST /auth/logout/": () => {
        loggedIn = false;
        return { status: 204 };
      },
      "POST /auth/login/": () => {
        loggedIn = true;
        return { status: 200, body: user };
      },
    });
    renderApp("/w/w2");
    await dashboardFor("Bonanjo Mobile");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await screen.findByRole("button", { name: "Sign in" });
    expect(path()).toBe("/login");

    await userEvent.type(screen.getByLabelText("Email"), "owner@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "a-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("heading", { name: "Choose a workspace" });
    expect(path()).toBe("/workspaces");
  });

  it("an expired session returns to login", async () => {
    serve({
      ...signedIn([akwa], "w1"),
      "GET /workspaces/w1/": () => ({
        status: 401,
        body: { code: "not_authenticated", detail: "Session ended." },
      }),
    });
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("failures", () => {
  it("shows the server's reason when this device is no longer authorised", async () => {
    serve({
      ...signedIn([akwa]),
      "GET /workspaces/w1/": () => ({
        status: 403,
        body: {
          code: "device_not_authorized",
          detail: "This device is no longer authorised for this workspace.",
        },
      }),
    });
    renderApp("/w/w1");
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer authorised");
  });

  it("shows a retryable error when the dashboard request fails", async () => {
    let attempts = 0;
    serve({
      ...signedIn([akwa]),
      "GET /workspaces/w1/": () =>
        ++attempts === 1
          ? { status: 500, body: { code: "error", detail: "Server error." } }
          : { status: 200, body: akwa },
    });
    renderApp("/w/w1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Server error.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await dashboardFor("Akwa Phones");
  });

  it("shows an error state when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderApp("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the server");
  });
});
