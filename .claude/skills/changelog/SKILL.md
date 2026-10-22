---
name: changelog
description: Bring CHANGELOG.md's [Unreleased] section up to date — add terse entries for what this branch changed, tighten wordy entries, merge duplicates, sort every section by impact, then take light and dark screenshots of the changes worth seeing and put them under their bullets. Use when the user types /changelog, asks to update, tidy, tighten or illustrate the changelog or release notes, or wants screenshots of a feature for What's new.
user-invocable: true
---

# /changelog — Write, tighten, sort and illustrate the release notes

`CHANGELOG.md` is read in three places: the version dialog, the What's new
pages (`/whats-new`, whose teaser is a release's **first three bold
headlines**), and GitHub. People skim it. This skill keeps the `[Unreleased]`
section short, in order of what matters most, and illustrated where a picture
says it faster.

Run the steps in order. Only `## [Unreleased]` is ever edited: a released
section is what shipped, so leave its words alone, typos included.

## 1. Gather

```bash
git log --oneline --grep="bump version" -n 1      # the last release
git log --oneline origin/dev..HEAD                # this branch's commits
git diff origin/dev...HEAD --stat                 # what it touched
```

Read the `## [Unreleased]` section whole, then the branch's diff where the
commits leave a change unclear. Arguments narrow the job: `/changelog tighten`
skips adding, `/changelog screenshots gantt` jumps to step 5 for that bullet.

## 2. Add entries for this branch

One bullet per change a person would notice, under `### Added`, `### Changed`,
`### Removed` or `### Fixed`:

- Skip refactors, tests, CI, dependency bumps and internal renames.
- Skip a `Fixed` entry for a bug in a feature that is itself still under
  `[Unreleased]`: nobody has had the bug.
- A change to something already in `[Unreleased]` updates that bullet rather
  than adding a second one.
- Write it in the house style below from the start.

## 3. Tighten

Rewrite every `[Unreleased]` bullet that breaks the style, and merge bullets
that describe the same change (two "Gantt view" bullets become one, keeping
every fact either had that the reader needs).

### The style

```
- **<Headline>.** <What you can do now, and where.> <One more sentence only if needed.>
```

- **Headline**: the change in the reader's words, three to six words, bold,
  ending in a period. It is what the What's new teaser shows, so it must
  stand alone: "Gantt view for projects", not "Improvements".
- **Body**: at most two sentences, about 35 words. Say what a person can do
  and where to find it (**Project settings → Task types**). Name the menu or
  button in bold as the UI names it.
- **Fixed**: what works now, not the history of the bug. "Exports of a grouped
  table keep its groups (#2911)." — not what it used to do, and not why.
- **Cut**: implementation (how it is drawn, what is cached), every option
  listed out (give one or two and "and more"), "until now"/"used to"
  narration, reassurance that existing things keep working unless someone
  might reasonably fear otherwise.
- **Keep**, whatever the length: anything a person must act on (pick a model,
  re-subscribe, enter a key again), data that is deleted or migrated, a
  `**Server operators:**` note, issue numbers, doc links, a plug-in API
  version.
- Present tense, second person, no exclamation marks, no "now" in the
  headline.

### Example

Before:

```
- **Gantt view for projects.** A project's tasks as bars from start to due date on a timeline, by day, week or month. Drag a bar to move a task, drag an end to change one date, or drag across an undated task's row to give it dates. Arrows join each task to what it is blocked by, in red when it starts before that is done; drag from the dot at a bar's end onto another task to make it wait on that one. A task's parts sit under it and fold away. Group it like the board. The arrow keys move between tasks and fold them, and Alt with an arrow moves a task's dates. Projects with thousands of tasks stay quick, because only the rows on screen are drawn. A project that opened on its Calendar opens on its Gantt, with the same presets.
```

After:

```
- **Gantt view for projects.** Tasks as bars on a day, week or month timeline: drag to reschedule, drag between bars to make one task wait on another, and fold subtasks under their parent. A project that opened on its Calendar opens on its Gantt.
```

The last sentence stays because people with such a project will see it change.

## 4. Sort by impact

Within each section, order bullets by **how many people it reaches × how much
it changes what they do**, highest first:

1. A change people must act on, or that changes what they see every day
   (breaking changes, a moved setting, a new default view).
2. New tools, views and screens most members will use.
3. Improvements to common flows (tasks, boards, documents, Home).
4. Features for admins, managers and power users (layouts, dashboards' SQL,
   plug-in API).
5. Server-operator and platform-owner changes.

For `Fixed`: data loss or wrong data first, then something that could not be
done at all (sign-in, an app, an export), then wrong-but-usable, then
cosmetic.

Sections run `Added`, `Changed`, `Removed`, `Fixed`, `Security`, dropping
empty ones. The first three `Added` headlines are the release's teaser on
What's new, so they should be the three things most worth announcing.

Show the user the new order of headlines per section (one line each) before
moving on, so a misjudged rank is cheap to fix.

## 5. Screenshots

Bullets in `Added` and `Changed` with something to look at — a new screen,
view, dialog or control — can carry a picture, drawn under the bullet in the
app's theme. Propose which (skip fixes, operator changes, removals, anything
invisible, and bullets that already have a
`![…](frontend/public/release-images/…)` line) and confirm the list with the
user before shooting. One picture per bullet is the norm; use several, as a strip,
when the change shows on several screens.

The machinery (read these before the first shot of a session):

- `frontend/e2e/shots/shoot.ts` — `shoot(page, name, locator?)` writes
  `frontend/public/release-images/<name>.webp` and `<name>.dark.webp`.
- `frontend/e2e/shots/gantt.shot.ts` — the example shot; `barovia.ts` opens
  the seed's best-filled project (dated, typed, linked tasks) and switches its
  list, showing the Gantt in its layout menu first if it is hidden.
- `frontend/e2e/shots/signIn.setup.ts` — signs in as `admin1@example.com`
  (seeded, password `changeme`); every shot starts signed in.
- `scripts/screenshots.sh`, run as `cd frontend && pnpm screenshots [file]` —
  finds this checkout's dev port and runs the `light` and `dark` projects.
- `frontend/src/lib/releaseImages.test.ts` — fails if a picture the changelog
  names is missing a theme or its alt text.

### 5a. Get the dev environment up

```bash
cd frontend && bash -c '. ../scripts/dev-ports.sh >/dev/null && curl -s -o /dev/null -m 5 -w "%{http_code}\n" "http://localhost:$DEV_FRONTEND_PORT"'
```

Source `dev-ports.sh` from **bash**, never zsh (it hangs there).

If nothing answers, start it in the background (Bash `run_in_background`) with
`bash scripts/dev-pre-launch.sh` from the repo root. It syncs deps, starts the
`db` service with `docker compose`, migrates, seeds, and runs both servers.
Wait until both the frontend port and
`http://localhost:$DEV_BACKEND_PORT/api/v1/version` answer, with a background
until-loop rather than sleeps. If Docker's daemon is not reachable, tell the
user (Docker Desktop's WSL integration) and stop — don't work around it.

If you started it, leave it running when you finish and say so: stopping it
(`bash scripts/dev-cleanup.sh`) also removes the seed data.

### 5b. Find the way to the screen

The seed is TTRPG-themed (`scripts/seed/`): communities, initiatives, projects
(Barovia Arc, Castle Ravenloft, Phandalin Adventures, …), tasks, documents,
calendars, dashboards. Read the feature's code (its route under
`frontend/src/routes/`, the component, its strings in
`frontend/public/locales/en/`) to learn how a person reaches it, then walk it
once in a real browser before writing the spec — the project's `browser` MCP
server (`.mcp.json`, headless Chromium) if it is connected, otherwise a
throwaway spec that logs
`await page.locator("body").ariaSnapshot()` at each step. Sign in as
`admin1@example.com` / `changeme`, at 1280×800.

- Use seed data that shows the feature with something in it — a Gantt with
  several dated, linked tasks, not an empty one.
- If the seed lacks it, have the shot make it through the UI first, with names
  that fit the seed's theme. If that is long, suggest adding it to
  `scripts/seed/` instead and ask.
- The whole window when the change is a page; a `locator` (a dialog, a card, a
  panel) when it is one piece of a page.

### 5c. Write the shot

One file per picture, `frontend/e2e/shots/<name>.shot.ts`:

```ts
import { expect, test } from "@playwright/test";

import { laterForUpdates } from "../support";
import { shoot } from "./shoot";

test.beforeEach(async ({ page }) => laterForUpdates(page));

test("gantt", async ({ page }) => {
  await page.goto("/");
  // …walk to the screen by role and accessible name, as a person would…
  await expect(page.getByRole("…", { name: "…" })).toBeVisible();
  await shoot(page, "gantt");
});
```

- **Name** the picture for what it shows (`gantt-dependencies`, not `0-77-1`).
  `ls frontend/public/release-images/` first: reusing a name replaces a
  picture an earlier release already shows.
- **Navigate by role and name**, never CSS classes. Seeded ids differ per
  database, so reach a project by clicking its name, not a `/c/1/i/2/…` URL.
- **Wait for the content**, not a timeout. `shoot()` also waits for the
  network to go quiet and disables animations.
- **Both themes run the same spec**, so anything it creates is created twice;
  find it before creating it, or name it so a second copy doesn't spoil the
  picture.

### 5d. Take it and look at it

```bash
cd frontend && pnpm screenshots e2e/shots/<name>.shot.ts
```

**Read both files** and check them as a reader would:

- The feature is the subject and readable at ~620px wide (the dialog's width);
  if it is lost in a full window, shoot a locator instead.
- No spinner, skeleton, toast, update prompt, empty state or error.
- Only seed data, nothing personal.
- Light is light and dark is dark.

Fix the spec and retake until both are right. A failing spec: read the error
and the trace (`frontend/test-results/`), fix the walk, rerun — don't add
waits or retries to paper over it.

### 5e. Link it

Under its bullet, indented as a continuation of it, by repository path so
GitHub draws it too:

```markdown
- **Gantt view for projects.** Tasks as bars on a day, week or month timeline…

  ![A project's Gantt view: tasks as bars across three weeks, with arrows from each task to what it waits on](frontend/public/release-images/gantt.webp)
```

The alt text says what the picture shows, in one sentence.

Two or more pictures for one bullet go on consecutive lines, with no blank
line between them. The version dialog and What's new then draw them as a
strip of tiles that scrolls sideways, with the count in its corner, each
opening full size in the lightbox:

```markdown
  ![The task types in settings](frontend/public/release-images/task-types.webp)
  ![A board showing each task's type](frontend/public/release-images/task-type-icons.webp)
```

## 6. Check and hand back

```bash
cd frontend && pnpm exec vitest run src/lib/releaseImages.test.ts
```

Then report:

- Entries added, rewritten (headline only), and merged.
- The new order, per section.
- Each picture (embed the light `.webp` path) with its bullet, and the spec
  and image files.
- Whether the dev environment is still running, and how to stop it.

**Don't commit.** The user reviews the wording and the pictures first; when
they commit, `CHANGELOG.md` goes in the same commit as the work it describes.
