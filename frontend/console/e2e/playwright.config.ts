import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack (real data). E2E_BASE_URL defaults to the compose `web` service;
// credentials come from E2E_USERNAME / E2E_PASSWORD (never committed).
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: "./results/artifacts",
  reporter: [["list"], ["html", { outputFolder: "./results/report", open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://web:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
