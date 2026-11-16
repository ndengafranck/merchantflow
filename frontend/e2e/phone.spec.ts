import { devices, expect, test } from "@playwright/test";
import { expectDashboard, signIn } from "./helpers";

// Phone-sized viewport with touch, in the same browser engine as the rest.
const { viewport, userAgent, deviceScaleFactor, isMobile, hasTouch } = devices["Pixel 5"];
test.use({ viewport, userAgent, deviceScaleFactor, isMobile, hasTouch });

test("someone with one workspace lands in it and the layout fits a phone", async ({ page }) => {
  await signIn(page, "marie@example.test", "/login");
  await expect(page).toHaveURL(/\/w\/[0-9a-f-]{36}$/);
  await expectDashboard(page, "Akwa Phones");

  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflows).toBe(false);

  await expect(page.getByRole("link", { name: "Dashboard" })).toBeHidden();
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await expect(page.getByRole("link", { name: "Dashboard" })).toBeVisible();
});
