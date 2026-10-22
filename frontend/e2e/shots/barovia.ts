import { expect, type Page } from "@playwright/test";

/**
 * Barovia Arc, the seed's horror campaign (scripts/seed/projects.py): dated
 * tasks a few weeks either side of today, a Milestone and an Idea among them,
 * and tasks that wait on others. Reached from its bookmark, as admin1 has it.
 */
export async function openBarovia(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch to Primary Community" }).click();
  await page.getByRole("link", { name: /Barovia Arc/ }).click();
  await expect(page.getByRole("heading", { name: "Barovia Arc", level: 1 })).toBeVisible();
}

/** Switch the project's tasks to `layout`, grouped by `groupBy`. A new
 *  project shows its board alone, so the Gantt is first shown in its layout
 *  menu through Edit layouts, as a person would. */
export async function showTasks(page: Page, layout: "Board" | "Gantt", groupBy = "None") {
  const menu = page.getByRole("combobox", { name: "Layout" });
  await menu.click();
  const shown = await page.getByRole("option", { name: layout }).count();
  await page.keyboard.press("Escape");
  if (!shown) {
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    await page.getByRole("tab", { name: "Layouts" }).click();
    await page.getByRole("link", { name: "Edit layouts" }).click();
    const editor = page.getByRole("dialog", { name: "Edit layouts" });
    await editor.getByRole("combobox", { name: "Layout being edited" }).click();
    await page.getByRole("option", { name: new RegExp(`^${layout}`) }).click();
    await editor.getByRole("switch", { name: "Shown in the layout menu" }).check();
    await editor.getByRole("button", { name: "Save" }).click();
    await expect(editor.getByRole("button", { name: "Save" })).toBeDisabled();
    await editor.getByRole("button", { name: "Close the editor" }).click();
    await openBarovia(page);
  }
  await menu.click();
  await page.getByRole("option", { name: layout }).click();
  await page.getByRole("combobox", { name: "Group by" }).click();
  await page.getByRole("option", { name: groupBy, exact: true }).click();
}

/** The project's task list: its heading, toolbar and the list itself, scrolled
 *  to the top of the window, clear of the buttons floating over its corner. */
export async function taskSection(page: Page) {
  const heading = page.getByRole("heading", { name: "Project tasks" });
  await heading.evaluate((element) => element.scrollIntoView({ block: "start" }));
  return heading.locator("xpath=ancestor::*[.//*[@role='treegrid']][1]");
}
