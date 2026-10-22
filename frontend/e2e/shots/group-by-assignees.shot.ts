import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openBarovia, showTasks, taskSection } from "./barovia";
import { shoot } from "./shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("group by assignees", async ({ page }) => {
  await openBarovia(page);
  await showTasks(page, "Gantt", "Assignees");
  await expect(page.getByRole("treegrid", { name: "Gantt" }).getByText("Unassigned")).toBeVisible();
  await shoot(page, "group-by-assignees", await taskSection(page));
});
