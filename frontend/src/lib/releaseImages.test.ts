import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { darkVariant, RELEASE_IMAGE_DIR, releaseImageUrl } from "./releaseImages";

const REPO_ROOT = path.resolve(__dirname, "../../..");

const SITE = "https://beyonders-studio.github.io/initiative/";

describe("releaseImageUrl", () => {
  it("loads a changelog picture from the docs site", () => {
    expect(releaseImageUrl("docs/images/releases/gantt.webp", false)).toBe(
      `${SITE}images/releases/gantt.webp`
    );
    expect(releaseImageUrl("./docs/images/releases/gantt.webp", false)).toBe(
      `${SITE}images/releases/gantt.webp`
    );
  });

  it("takes the dark picture in the dark theme", () => {
    expect(releaseImageUrl("docs/images/releases/0.77/gantt.webp", true)).toBe(
      `${SITE}images/releases/0.77/gantt.dark.webp`
    );
  });

  it("leaves any other address as written", () => {
    expect(releaseImageUrl("https://example.com/a.png", true)).toBe("https://example.com/a.png");
    expect(releaseImageUrl("docs/images/logo.svg", true)).toBe("docs/images/logo.svg");
  });
});

describe("CHANGELOG.md's pictures", () => {
  it("are each in the repository, light and dark, with alt text", () => {
    const changelog = fs.readFileSync(path.join(REPO_ROOT, "CHANGELOG.md"), "utf8");
    const pictures = [...changelog.matchAll(/!\[([^\]]*)\]\(([^)\s]+)/g)]
      .map(([, alt, src]) => ({ alt, src: src.replace(/^\.\//, "") }))
      .filter(({ src }) => src.startsWith(RELEASE_IMAGE_DIR));

    for (const { alt, src } of pictures) {
      expect(alt.trim(), `${src} needs alt text`).not.toBe("");
      for (const file of [src, darkVariant(src)]) {
        expect(
          fs.existsSync(path.join(REPO_ROOT, file)),
          `${file} is missing; run pnpm screenshots`
        ).toBe(true);
      }
    }
  });
});
