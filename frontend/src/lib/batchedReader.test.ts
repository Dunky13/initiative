import { describe, expect, it, vi } from "vitest";

import { batchedReader } from "@/lib/batchedReader";

describe("things asking for themselves", () => {
  const answer = (refs: string[]) => refs.map((ref) => ({ ref }));
  const byRef = (item: { ref: string }) => item.ref;

  it("go out as one request for everything asked in the same moment", async () => {
    const read = vi.fn(async (_communityId: number, refs: string[]) => answer(refs));
    const load = batchedReader(read, byRef, 10);

    const asked = await Promise.all([load(1, "task:1:status"), load(1, "task:2:due")]);

    expect(read).toHaveBeenCalledTimes(1);
    expect(asked.map((item) => item?.ref)).toEqual(["task:1:status", "task:2:due"]);
  });

  it("split at what one request may carry", async () => {
    // Past its ceiling the server refuses the request outright rather than
    // answering part of it, so one moment asking for more sends several.
    const read = vi.fn(async (_communityId: number, refs: string[]) => answer(refs));
    const load = batchedReader(read, byRef, 2);

    await Promise.all(["a:1", "a:2", "a:3", "a:4", "a:5"].map((ref) => load(1, ref)));

    expect(read.mock.calls.map(([, refs]) => refs.length)).toEqual([2, 2, 1]);
  });

  it("ask about a thing once, however many chips name it", async () => {
    const read = vi.fn(async (_communityId: number, refs: string[]) => answer(refs));
    const load = batchedReader(read, byRef, 10);

    const [first, second] = await Promise.all([load(1, "task:1"), load(1, "task:1")]);

    expect(read.mock.calls[0][1]).toEqual(["task:1"]);
    expect(first?.ref).toBe("task:1");
    expect(second?.ref).toBe("task:1");
  });

  it("hear nothing for what the server left out", async () => {
    // Gone, or not this reader's to see: the server answers the two the same.
    const load = batchedReader(async () => answer(["task:1"]), byRef, 10);
    expect(await load(1, "task:2")).toBeNull();
  });

  it("ask each community separately", async () => {
    const read = vi.fn(async (_communityId: number, refs: string[]) => answer(refs));
    const load = batchedReader(read, byRef, 10);

    await Promise.all([load(1, "task:1"), load(2, "task:1")]);

    expect(read.mock.calls.map(([communityId]) => communityId).sort()).toEqual([1, 2]);
  });
});
