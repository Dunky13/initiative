import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { RELEASE_IMAGE_DIR, releaseImageUrl } from "./releaseImages";

const REPO_ROOT = path.resolve(__dirname, "../../..");

describe("releaseImageUrl", () => {
  it("serves a changelog picture from the app's own root", () => {
    expect(releaseImageUrl("frontend/public/release-images/gantt.webp", false)).toBe(
      "/release-images/gantt.webp"
    );
    expect(releaseImageUrl("./frontend/public/release-images/gantt.webp", false)).toBe(
      "/release-images/gantt.webp"
    );
  });

  it("takes the dark picture in the dark theme", () => {
    expect(releaseImageUrl("frontend/public/release-images/0.77/gantt.webp", true)).toBe(
      "/release-images/0.77/gantt.dark.webp"
    );
  });

  it("leaves any other address as written", () => {
    expect(releaseImageUrl("https://example.com/a.png", true)).toBe("https://example.com/a.png");
    expect(releaseImageUrl("frontend/public/screenshots/project.png", true)).toBe(
      "frontend/public/screenshots/project.png"
    );
  });
});

describe("CHANGELOG.md's pictures", () => {
  it("are each in the repository, light and dark, with alt text", () => {
    const changelog = fs.readFileSync(path.join(REPO_ROOT, "CHANGELOG.md"), "utf8");
    const pictures = [...changelog.matchAll(/!\[([^\]]*)\]\(([^)\s]+)/g)]
      .map(([, alt, src]) => ({ alt, src }))
      .filter(({ src }) => src.replace(/^\.\//, "").startsWith(RELEASE_IMAGE_DIR));

    for (const { alt, src } of pictures) {
      expect(alt.trim(), `${src} needs alt text`).not.toBe("");
      for (const dark of [false, true]) {
        const file = path.join(REPO_ROOT, "frontend/public", releaseImageUrl(src, dark));
        expect(fs.existsSync(file), `${file} is missing; run pnpm screenshots`).toBe(true);
      }
    }
  });
});
