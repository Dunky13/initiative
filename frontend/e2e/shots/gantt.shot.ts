import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openBarovia, showTasks, taskSection } from "./barovia";
import { shoot } from "./shoot";

// A shot is a short walk to the screen a change is about, then shoot(). Take
// them with `pnpm screenshots` (a dev environment running, with its seed
// data), look the pictures over, and commit them with the changelog entry
// that names them. `pnpm screenshots e2e/shots/gantt.shot.ts` retakes one.

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("gantt", async ({ page }) => {
  await openBarovia(page);
  await showTasks(page, "Gantt");
  await expect(page.getByRole("row", { name: /^Defeat Strahd von Zarovich, / })).toBeVisible();
  await shoot(page, "gantt", await taskSection(page));
});
