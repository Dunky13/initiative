/**
 * Pictures in the changelog.
 *
 * They live with the help center, in `docs/images/releases/`, and are
 * published with it to GitHub Pages: they ship in no install and no app
 * update. CHANGELOG.md names a picture by its place in the repository
 * (`docs/images/releases/gantt.webp`), which GitHub draws, and the app loads
 * the same file from the published docs site. The docs deploy when a release
 * reaches main, so a released entry's pictures are there by the time anyone
 * can read it.
 *
 * Every picture comes in two: `gantt.webp` taken in the light theme and
 * `gantt.dark.webp` in the dark one (`pnpm screenshots` takes both).
 */

import { DOCS_SITE_URL } from "@/lib/links";

/** Where the pictures sit in the repository. */
export const RELEASE_IMAGE_DIR = "docs/images/releases/";

/** The docs site serves `docs/` from its root. */
const PUBLISHED_FROM = "docs/";

const REPO_PATH = /^(?:\.\/)?(docs\/images\/releases\/[^?#]+)$/;

/** The dark-theme twin of a picture's path: `gantt.webp` → `gantt.dark.webp`. */
export const darkVariant = (path: string): string => path.replace(/(\.[a-z0-9]+)$/i, ".dark$1");

/** Where the app loads a changelog picture from, in the theme it is drawn in.
 *  Any other address is left as written. */
export const releaseImageUrl = (src: string, dark: boolean): string => {
  const match = src.match(REPO_PATH);
  if (!match) return src;
  const path = dark ? darkVariant(match[1]) : match[1];
  return `${DOCS_SITE_URL}${path.slice(PUBLISHED_FROM.length)}`;
};
