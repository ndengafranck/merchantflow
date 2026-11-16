import { expect, test } from "@playwright/test";
import { api, expectDashboard, signIn, workspaceId } from "./helpers";

interface Device {
  id: string;
  user_id: string;
  is_current: boolean;
  status: string;
}

test("revoking a workspace device closes that workspace to that browser", async ({ browser }) => {
  const jeanContext = await browser.newContext();
  const jean = await jeanContext.newPage();
  await signIn(jean, "jean@example.test");
  await expectDashboard(jean, "Akwa Phones");
  const me = await api<{ id: string }>(jean, "GET", "/auth/me/");

  const ownerContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  await signIn(owner, "awa@example.test");
  const akwa = await workspaceId(owner, "Akwa Phones");
  const list = await api<Device[]>(owner, "GET", `/workspaces/${akwa}/devices/`);
  const jeansDevice = list.body.find((d) => d.user_id === me.body.id)!;
  const revoked = await api<Device>(
    owner,
    "POST",
    `/workspaces/${akwa}/devices/${jeansDevice.id}/revoke/`,
  );
  expect(revoked.body.status).toBe("revoked");

  // Jean's browser: still signed in, but the workspace is closed to it.
  await jean.reload();
  await expect(jean.getByRole("alert")).toContainText("no longer authorised");
  expect((await api(jean, "GET", "/auth/me/")).status).toBe(200);
  expect((await api(jean, "POST", `/workspaces/${akwa}/sync/handshake/`)).status).toBe(403);

  // Signing out and in again on the same browser does not lift it.
  await jean.goto("/workspaces");
  await jean.getByRole("button", { name: "Sign out" }).click();
  await signIn(jean, "jean@example.test");
  await expect(jean.getByRole("alert")).toContainText("no longer authorised");

  const after = await api<Device[]>(owner, "GET", `/workspaces/${akwa}/devices/`);
  expect(after.body.filter((d) => d.user_id === me.body.id)).toHaveLength(1);
  await jeanContext.close();
  await ownerContext.close();
});

test("revoking a browser installation signs that browser out", async ({ browser }) => {
  const phoneContext = await browser.newContext();
  const phone = await phoneContext.newPage();
  await signIn(phone, "sam@example.test");
  await expectDashboard(phone, "Akwa Phones");

  const laptopContext = await browser.newContext();
  const laptop = await laptopContext.newPage();
  await signIn(laptop, "sam@example.test");

  const installations = await api<{ id: string; is_current: boolean }[]>(
    laptop,
    "GET",
    "/auth/installations/",
  );
  expect(installations.body).toHaveLength(2);
  const other = installations.body.find((i) => !i.is_current)!;
  expect((await api(laptop, "POST", `/auth/installations/${other.id}/revoke/`)).status).toBe(200);

  await phone.reload();
  await expect(phone).toHaveURL(/\/login$/);
  expect((await api(phone, "GET", "/auth/me/")).status).toBe(401);

  await laptop.reload();
  await expectDashboard(laptop, "Akwa Phones");
  await phoneContext.close();
  await laptopContext.close();
});
