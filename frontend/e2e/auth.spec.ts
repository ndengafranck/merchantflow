import { expect, test } from "@playwright/test";
import { api, expectDashboard, signIn, workspaceId } from "./helpers";

test("anonymous visitor is sent to login and sees server errors", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email").fill("awa@example.test");
  await page.getByLabel("Password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Incorrect email or password.");
});

test("signing in sets HttpOnly cookies and stores nothing in the browser", async ({
  page,
  context,
}) => {
  await signIn(page, "awa@example.test");
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();

  const cookies = Object.fromEntries((await context.cookies()).map((c) => [c.name, c]));
  expect(cookies.mf_session).toMatchObject({ httpOnly: true, sameSite: "Lax" });
  expect(cookies.mf_device).toMatchObject({ httpOnly: true, sameSite: "Lax" });
  expect(cookies.mf_csrftoken).toMatchObject({ httpOnly: false });

  const visible = await page.evaluate(() => document.cookie);
  expect(visible).not.toContain("mf_session");
  expect(visible).not.toContain("mf_device");
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test("a write without the CSRF header is refused", async ({ page }) => {
  await signIn(page, "awa@example.test");
  expect((await api(page, "POST", "/auth/logout/", { csrf: false })).status).toBe(403);
  expect((await api(page, "GET", "/auth/me/")).status).toBe(200);
});

test("signing in returns to the workspace page that was asked for", async ({ page }) => {
  await signIn(page, "awa@example.test");
  const bonanjo = await workspaceId(page, "Bonanjo Mobile");
  await page.context().clearCookies({ name: "mf_session" });

  await signIn(page, "awa@example.test", `/w/${bonanjo}`);
  await expect(page).toHaveURL(new RegExp(`/w/${bonanjo}$`));
  await expectDashboard(page, "Bonanjo Mobile");
});

test("signing out ends the session", async ({ page }) => {
  await signIn(page, "marie@example.test");
  await expectDashboard(page, "Akwa Phones");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await api(page, "GET", "/auth/me/")).status).toBe(401);
});
