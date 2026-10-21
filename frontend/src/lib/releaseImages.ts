/**
 * Pictures in the changelog.
 *
 * CHANGELOG.md is read on GitHub as well as in the app, so it names a picture
 * by its place in the repository (`frontend/public/release-images/gantt.webp`),
 * which GitHub draws. The app serves the same file from the root of its own
 * bundle, so a release's pictures travel with the release, on the web and in
 * the native apps alike.
 *
 * Every picture comes in two: `gantt.webp` taken in the light theme and
 * `gantt.dark.webp` in the dark one (`pnpm screenshots` takes both).
 */

/** Where the pictures sit in the repository. */
export const RELEASE_IMAGE_DIR = "frontend/public/release-images/";

const REPO_PATH = /^(?:\.\/)?frontend\/public(\/release-images\/[^?#]+)$/;

/** The address the app serves a changelog picture from, in the theme it is
 *  drawn in. Any other address is left as written. */
export const releaseImageUrl = (src: string, dark: boolean): string => {
  const match = src.match(REPO_PATH);
  if (!match) return src;
  const path = match[1];
  return dark ? path.replace(/(\.[a-z0-9]+)$/i, ".dark$1") : path;
};
