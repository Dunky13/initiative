import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The browser MCP server in .mcp.json runs with `--browser chromium`: the
 * Chromium that `pnpm exec playwright install chromium` downloads for the
 * journeys and the release screenshots. Each Playwright release wants its own
 * Chromium build, so @playwright/mcp has to be one built on the same Playwright
 * minor as @playwright/test, or it looks for a browser nobody installed.
 */
const installed = (name: string) =>
  JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "../../node_modules", name, "package.json"), "utf8")
  ) as { version: string; dependencies?: Record<string, string> };

const minor = (version: string) => version.split(".").slice(0, 2).join(".");

describe("the browser MCP server", () => {
  it("is built on the Playwright the tests use", () => {
    const test = installed("@playwright/test").version;
    const mcp = installed("@playwright/mcp").dependencies?.["playwright-core"] ?? "";
    expect(
      minor(mcp),
      `@playwright/mcp is built on Playwright ${mcp}, @playwright/test is ${test}: pick the @playwright/mcp release built on ${minor(test)}`
    ).toBe(minor(test));
  });
});
