import { defineConfig, devices } from "@playwright/test";

// The browser tests run the real stack: Django on a throwaway PostgreSQL
// database and the Vite dev server in front of it, on ports that do not clash
// with a developer's own servers.
const BACKEND_PORT = 8100;
const FRONTEND_PORT = 5183;
const ORIGIN = `http://localhost:${FRONTEND_PORT}`;
const PYTHON = process.env.E2E_PYTHON ?? ".venv/bin/python";
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ??
  "postgres://merchantflow:merchantflow_dev@127.0.0.1:5432/merchantflow_e2e";

export default defineConfig({
  testDir: "./e2e",
  // One worker: the tests share one database and some of them revoke devices.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: ORIGIN,
    trace: "off",
    launchOptions: process.env.PW_CHROMIUM_PATH
      ? { executablePath: process.env.PW_CHROMIUM_PATH }
      : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PYTHON} scripts/e2e_seed.py && ${PYTHON} manage.py runserver 127.0.0.1:${BACKEND_PORT} --noreload`,
      cwd: "../backend",
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health/`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL,
        DJANGO_SECRET_KEY: "insecure-e2e-only",
        DJANGO_DEBUG: "true",
        DJANGO_ALLOWED_HOSTS: "localhost,127.0.0.1",
        DJANGO_CSRF_TRUSTED_ORIGINS: ORIGIN,
        DJANGO_SECURE_COOKIES: "false",
      },
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT}`,
      url: ORIGIN,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_PROXY_TARGET: `http://127.0.0.1:${BACKEND_PORT}` },
    },
  ],
});
