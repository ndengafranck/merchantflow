import { expect, test } from "@playwright/test";
import { api, expectDashboard, signIn, workspaceId } from "./helpers";

test("the chosen workspace lives in the URL and survives a reload", async ({ page }) => {
  await signIn(page, "awa@example.test");
  await page.getByRole("link", { name: /Akwa Phones/ }).click();
  await expect(page).toHaveURL(/\/w\/[0-9a-f-]{36}$/);
  await expectDashboard(page, "Akwa Phones");
  await expect(page.getByText("Owner", { exact: true }).first()).toBeVisible();

  await page.reload();
  await expectDashboard(page, "Akwa Phones");
});

test("back and forward move between workspaces and show the right data", async ({ page }) => {
  await signIn(page, "awa@example.test");
  await page.goto("/workspaces");
  await page.getByRole("link", { name: /Akwa Phones/ }).click();
  await expectDashboard(page, "Akwa Phones");
  const akwaUrl = page.url();

  await page.getByRole("link", { name: "Switch workspace" }).click();
  await page.getByRole("link", { name: /Bonanjo Mobile/ }).click();
  await expectDashboard(page, "Bonanjo Mobile");
  await expect(page.getByText("Affiliate", { exact: true }).first()).toBeVisible();
  const bonanjoUrl = page.url();
  expect(bonanjoUrl).not.toBe(akwaUrl);

  await page.goBack(); // the chooser
  await expect(page.getByRole("heading", { name: "Choose a workspace" })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(akwaUrl);
  await expectDashboard(page, "Akwa Phones");
  await expect(page.getByText("Owner", { exact: true }).first()).toBeVisible();

  await page.goForward();
  await page.goForward();
  await expect(page).toHaveURL(bonanjoUrl);
  await expectDashboard(page, "Bonanjo Mobile");
});

test("two tabs keep their own workspace", async ({ page, context }) => {
  await signIn(page, "awa@example.test");
  const akwa = await workspaceId(page, "Akwa Phones");
  const bonanjo = await workspaceId(page, "Bonanjo Mobile");
  const tabA = page;
  const tabB = await context.newPage();

  await tabA.goto(`/w/${akwa}`);
  await expectDashboard(tabA, "Akwa Phones");
  await tabB.goto(`/w/${bonanjo}`);
  await expectDashboard(tabB, "Bonanjo Mobile");

  // Tab B was used last. Tab A must not follow it, even after a reload.
  await tabA.reload();
  await expect(tabA).toHaveURL(new RegExp(`/w/${akwa}$`));
  await expectDashboard(tabA, "Akwa Phones");
  await tabB.reload();
  await expectDashboard(tabB, "Bonanjo Mobile");

  // "Last used" only decides where a fresh visit to "/" lands.
  const tabC = await context.newPage();
  await tabC.goto("/");
  await expectDashboard(tabC, "Bonanjo Mobile");
});

test("a workspace the user does not belong to is not available", async ({ page }) => {
  await signIn(page, "awa@example.test");
  const bonanjo = await workspaceId(page, "Bonanjo Mobile");
  await page.getByRole("button", { name: "Sign out" }).click();

  await signIn(page, "marie@example.test"); // member of Akwa Phones only
  await page.goto(`/w/${bonanjo}`);
  await expect(page.getByText("Workspace not available")).toBeVisible();
  expect((await api(page, "GET", `/workspaces/${bonanjo}/`)).status).toBe(404);
  expect((await api(page, "GET", `/workspaces/${bonanjo}/members/`)).status).toBe(404);

  await page.goto(`/w/${crypto.randomUUID()}`);
  await expect(page.getByText("Workspace not available")).toBeVisible();
  await page.getByRole("link", { name: "Choose a workspace" }).click();
  await expect(page.getByRole("link", { name: /Akwa Phones/ })).toBeVisible();
});

test("roles differ per workspace for the same person", async ({ page }) => {
  await signIn(page, "awa@example.test");
  const akwa = await workspaceId(page, "Akwa Phones");
  const bonanjo = await workspaceId(page, "Bonanjo Mobile");
  expect((await api(page, "GET", `/workspaces/${akwa}/members/`)).status).toBe(200);
  expect((await api(page, "GET", `/workspaces/${bonanjo}/members/`)).status).toBe(403);
});
