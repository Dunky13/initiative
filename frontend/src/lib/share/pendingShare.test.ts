import { afterEach, describe, expect, it, vi } from "vitest";

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

describe("a share waiting through a restart", () => {
  // A fresh copy of the module is the app started again.
  const restart = async () => {
    vi.resetModules();
    return import("@/lib/share/pendingShare");
  };

  it("is still waiting when the app comes back", async () => {
    setPendingShare(receivedShare({ texts: ["hello"] }));

    const after = await restart();

    expect(after.getPendingShare()).toMatchObject({ texts: ["hello"], opened: false });
    after.setPendingShare(null);
  });

  it("is let go once the share page has shown it", async () => {
    setPendingShare(receivedShare({ texts: ["hello"] }));
    markPendingShareOpened();

    const after = await restart();

    expect(after.getPendingShare()).toBeNull();
  });

  it("is let go after a day, when its files are gone", async () => {
    const share = receivedShare({ texts: ["hello"] });
    localStorage.setItem(
      "initiative-pending-share",
      JSON.stringify({ share, savedAt: Date.now() - 25 * 60 * 60 * 1000 })
    );

    const after = await restart();

    expect(after.getPendingShare()).toBeNull();
    expect(localStorage.getItem("initiative-pending-share")).toBeNull();
  });

  it("is told apart from the next share", async () => {
    setPendingShare(receivedShare({ texts: ["first"] }));

    const after = await restart();
    const kept = after.getPendingShare();
    const next = after.receivedShare({ texts: ["second"] });

    expect(next?.id).not.toBe(kept?.id);
    after.setPendingShare(null);
  });
});
