import { expect, type Page } from "@playwright/test";

// Matches backend/scripts/e2e_seed.py. Fictional accounts in a database that
// is wiped before every run.
export const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-only-passphrase-7421";

export async function signIn(page: Page, email: string, path = "/") {
  await page.goto(path);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // The form stays on screen (button reads "Signing in…") until the session is loaded.
  await expect(page.getByLabel("Password")).toHaveCount(0);
}

export async function expectDashboard(page: Page, workspaceName: string) {
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByTestId("stat-workspace")).toHaveText(workspaceName);
}

interface ApiResult<T = unknown> {
  status: number;
  body: T;
}

/** Call the API from inside the page, exactly as the application would. */
export function api<T = unknown>(
  page: Page,
  method: string,
  path: string,
  options: { csrf?: boolean } = {},
): Promise<ApiResult<T>> {
  return page.evaluate(
    async ([method, path, csrf]) => {
      const token = document.cookie.match(/(?:^|; )mf_csrftoken=([^;]+)/)?.[1] ?? "";
      const headers: Record<string, string> = {};
      if (csrf && method !== "GET") headers["X-CSRFToken"] = token;
      const response = await fetch(`/api/v1${path}`, { method: method as string, headers });
      const text = await response.text();
      return { status: response.status, body: text ? JSON.parse(text) : null };
    },
    [method, path, options.csrf ?? true] as const,
  ) as Promise<ApiResult<T>>;
}

/** The id of one of the signed-in user's workspaces, looked up by name. */
export async function workspaceId(page: Page, name: string): Promise<string> {
  const { body } = await api<{ memberships: { workspace: { id: string; name: string } }[] }>(
    page,
    "GET",
    "/workspaces/",
  );
  const found = body.memberships.find((m) => m.workspace.name === name);
  if (!found) throw new Error(`The signed-in user is not a member of "${name}".`);
  return found.workspace.id;
}
