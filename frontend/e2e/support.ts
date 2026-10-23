import { expect, type Page } from "@playwright/test";

// A server newer than the page it served offers to reload, whenever it
// notices; somebody in the middle of something says not yet.
export async function laterForUpdates(page: Page) {
  const prompt = page.getByRole("dialog", { name: /^Version .* is available$/ });
  await page.addLocatorHandler(prompt, () => prompt.getByRole("button", { name: "Later" }).click());
}

/**
 * The date of birth, typed into the picker. Every account is asked it once: a
 * fresh install asks beside the handle, and an account that signs up without
 * it meets a screen that asks before anything else.
 */
export async function giveBirthdate(page: Page) {
  const field = page.getByRole("button", { name: "Date of birth" });
  await field.click();
  const typed = page.getByRole("textbox", { name: "Type or pick a date" });
  await typed.fill("1990-04-12");
  await typed.press("Enter");
  await page.keyboard.press("Escape");
  await expect(field).toContainText("Apr 12, 1990");
}
