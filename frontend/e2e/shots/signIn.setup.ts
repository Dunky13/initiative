import { expect, test as setup } from "@playwright/test";

import { giveBirthdate, laterForUpdates } from "../support";
import { SIGNED_IN } from "./signedIn";

// The shots are taken as one of the seeded community admins
// (scripts/seed_dev_data.py), so the pictures show a community with
// something in it. SHOTS_EMAIL / SHOTS_PASSWORD pick somebody else.
setup("sign in", async ({ page }) => {
  await laterForUpdates(page);
  await page.goto("/login");
  await page.getByLabel("Email").fill(process.env.SHOTS_EMAIL ?? "admin1@example.com");
  await page.getByLabel("Password").fill(process.env.SHOTS_PASSWORD ?? "changeme");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  // The seed gives nobody a date of birth, so the first sign-in asks for one.
  const home = page.getByRole("heading", { name: "Home", level: 1 });
  const askAge = page.getByText("How old are you?");
  await expect(home.or(askAge)).toBeVisible();
  if (await askAge.isVisible()) {
    await giveBirthdate(page);
    await page.getByRole("button", { name: "Continue" }).click();
  }
  await expect(home).toBeVisible();
  await page.context().storageState({ path: SIGNED_IN });
});
