import { defineConfig } from "@playwright/test";

// Drives the real UI against the real backend (simulation mode).
// Start both servers first (see README) or let Playwright start them.
export default defineConfig({
  testDir: "./e2e",
  timeout: 15 * 60 * 1000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.IAP_E2E_BASE_URL ?? "http://localhost:3000",
    channel: process.env.IAP_E2E_CHANNEL ?? "chrome",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    { command: "cd ../backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000", url: "http://127.0.0.1:8000/api/health", reuseExistingServer: true, timeout: 60_000 },
    { command: "npm run dev", url: "http://localhost:3000", reuseExistingServer: true, timeout: 120_000 },
  ],
});
