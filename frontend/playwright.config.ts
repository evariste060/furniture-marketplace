import { defineConfig, devices } from "@playwright/test";

/** End-to-end tests against a production build (`next build` + `next start`) on port 3100, with the
 * API running on API_URL (default http://127.0.0.1:8000). Every page is also checked with axe. */
const PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  // One worker: parallel workers against one `next start` and the dev API timed out on a
  // development machine with little free memory (2026-10-27). The suite is small.
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: { baseURL: `http://localhost:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: `npm run build && npx next start -p ${PORT}`,
    url: `http://localhost:${PORT}/dev/ui`,
    timeout: 300_000,
    reuseExistingServer: !process.env.CI,
    env: {
      ENABLE_DEV_UI: "true",
      SITE_URL: `http://localhost:${PORT}`,
      API_URL: process.env.API_URL ?? "http://127.0.0.1:8000",
      IMAGE_REMOTE_PATTERNS: process.env.IMAGE_REMOTE_PATTERNS ?? "http://localhost:8000/media/**",
    },
  },
});
