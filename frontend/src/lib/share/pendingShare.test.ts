import { afterEach, describe, expect, it } from "vitest";

import {
  getPendingShare,
  isImage,
  markPendingShareOpened,
  receivedShare,
  setPendingShare,
} from "@/lib/share/pendingShare";

afterEach(() => setPendingShare(null));

describe("isImage", () => {
  it("tells a picture from any other file", () => {
    expect(isImage({ uri: "/a", name: "a.png", mimeType: "image/png" })).toBe(true);
    expect(isImage({ uri: "/b", name: "b.pdf", mimeType: "application/pdf" })).toBe(false);
  });
});

describe("receivedShare", () => {
  it("keeps the written text and every file", () => {
    const share = receivedShare({
      title: " A page ",
      texts: [" https://example.com ", "", null],
      files: [
        { uri: "/cache/a.jpg", name: "a.jpg", mimeType: "image/jpeg" },
        { uri: "/cache/b.pdf", name: "b.pdf", mimeType: "application/pdf" },
      ],
    });

    expect(share).toMatchObject({
      title: "A page",
      texts: ["https://example.com"],
      files: [
        { uri: "/cache/a.jpg", name: "a.jpg", mimeType: "image/jpeg" },
        { uri: "/cache/b.pdf", name: "b.pdf", mimeType: "application/pdf" },
      ],
      opened: false,
    });
  });

  it("is nothing for a share with nothing in it", () => {
    expect(
      receivedShare({
        title: "",
        texts: ["  "],
        files: [{ uri: "", name: "lost.pdf", mimeType: "application/pdf" }],
      })
    ).toBeNull();
  });

  it("types a file the system could not", () => {
    const share = receivedShare({ files: [{ uri: "/cache/c", name: "c", mimeType: "" }] });
    expect(share?.files[0].mimeType).toBe("application/octet-stream");
  });

  it("tells one share from the next", () => {
    const first = receivedShare({ texts: ["one"] });
    const second = receivedShare({ texts: ["one"] });
    expect(first?.id).not.toBe(second?.id);
  });
});

describe("the pending share", () => {
  it("is marked opened once the page has shown it", () => {
    setPendingShare(receivedShare({ texts: ["hello"] }));
    markPendingShareOpened();
    expect(getPendingShare()?.opened).toBe(true);
  });

  it("is replaced by a newer share", () => {
    setPendingShare(receivedShare({ texts: ["first"] }));
    setPendingShare(receivedShare({ texts: ["second"] }));
    expect(getPendingShare()?.texts).toEqual(["second"]);
  });
});
