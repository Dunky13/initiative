import { useEffect, useState } from "react";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import type { LinkedRef } from "@/lib/relationships";

const DEFAULT_COLOR = "#6366F1";

const EMPTY = {
  label: "",
  position: "",
  color: DEFAULT_COLOR,
  notes: "",
  isVisible: true,
  selectedTags: [] as TagSummary[],
  userId: null as number | null,
  links: [] as LinkedRef[],
};

/**
 * The fields of an item being added to a queue, which start empty each time
 * the dialog opens. An item that exists is drawn by its queue's layout, each
 * field saved on its own, so this holds nothing for one.
 */
export const useQueueItemForm = ({ open }: { open: boolean }) => {
  const [values, setValues] = useState(EMPTY);
  useEffect(() => {
    if (open) setValues(EMPTY);
  }, [open]);
  const set = (patch: Partial<typeof EMPTY>) => setValues((prev) => ({ ...prev, ...patch }));
  return {
    ...values,
    setLabel: (label: string) => set({ label }),
    setPosition: (position: string) => set({ position }),
    setColor: (color: string) => set({ color }),
    setNotes: (notes: string) => set({ notes }),
    setIsVisible: (isVisible: boolean) => set({ isVisible }),
    setSelectedTags: (selectedTags: TagSummary[]) => set({ selectedTags }),
    setUserId: (userId: number | null) => set({ userId }),
    setLinks: (links: LinkedRef[]) => set({ links }),
  };
};
