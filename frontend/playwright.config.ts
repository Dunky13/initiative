import { defineConfig, devices } from "@playwright/test";

import { SIGNED_IN } from "./e2e/shots/signedIn";

// Two kinds of run share this file, picked by --project:
//
// The browser journeys (e2e/*.journey.ts, project "journeys"): the image,
// served as the example compose file serves it, driven in Chromium. CI starts
// the server (.github/workflows/journeys.yml); locally, point JOURNEYS_URL at a
// fresh install. Each run needs an empty database: the first journey registers
// the first owner.
//
// The release screenshots (e2e/shots/*.shot.ts, projects "light" and "dark"):
// pictures for CHANGELOG.md, taken of a running dev environment with its seed
// data (`pnpm screenshots`, which finds this checkout's dev port). Each shot
// runs once per theme.
const SHOTS_URL =
  process.env.SHOTS_URL ?? `http://localhost:${process.env.DEV_FRONTEND_PORT ?? 5173}`;

/** One size for every screenshot, so a release's pictures sit together. */
const shot = {
  ...devices["Desktop Chrome"],
  baseURL: SHOTS_URL,
  viewport: { width: 1280, height: 800 },
  locale: "en-US",
  timezoneId: "UTC",
  storageState: SIGNED_IN,
};

export default defineConfig({
  testDir: "./e2e",
  // One install, built up in order: the journeys share its owner.
  workers: 1,
  fullyParallel: false,
  // A journey that passes on a second try is a flake to fix, not a pass.
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // In CI, a failure is also an annotation on the run.
  reporter: [
    ...(process.env.CI ? [["github"] as const] : []),
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "journeys",
      testMatch: "*.journey.ts",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: process.env.JOURNEYS_URL ?? "http://localhost:8173",
      },
    },
    {
      name: "shots-sign-in",
      testMatch: "shots/signIn.setup.ts",
      use: { ...devices["Desktop Chrome"], baseURL: SHOTS_URL },
    },
    {
      name: "light",
      testMatch: "shots/**/*.shot.ts",
      dependencies: ["shots-sign-in"],
      use: { ...shot, colorScheme: "light" },
    },
    {
      name: "dark",
      testMatch: "shots/**/*.shot.ts",
      dependencies: ["shots-sign-in"],
      use: { ...shot, colorScheme: "dark" },
    },
  ],
});
