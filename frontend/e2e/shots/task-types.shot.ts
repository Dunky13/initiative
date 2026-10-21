import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { openBarovia } from "./barovia";
import { shoot } from "./shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("task types", async ({ page }) => {
  await openBarovia(page);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("tab", { name: "Task types" }).click();
  const types = page.getByRole("table");
  await expect(types.getByRole("textbox", { name: "Name" })).toHaveCount(4);
  const card = page
    .getByText("Types are the kinds of task this project holds")
    .locator("xpath=ancestor::*[.//table][1]");
  await shoot(page, "task-types", card);
});
