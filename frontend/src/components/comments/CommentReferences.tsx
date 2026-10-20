import { createContext, type ReactNode, useContext, useMemo } from "react";

import { MentionCommunity } from "@/hooks/useMentionedPeople";
import { useChipStates } from "@/hooks/useSmartChips";
import { collectCommentReferences } from "@/lib/commentReferences";

interface Resolved {
  /** Current names by `kind:id`. */
  titles: Map<string, string>;
  /** Whether the answer has arrived. Until it has, a comment shows the words
   *  it was written with rather than flickering. */
  ready: boolean;
}

const CommentReferencesContext = createContext<Resolved>({
  titles: new Map(),
  ready: false,
});

export const useCommentReferences = () => useContext(CommentReferencesContext);

/**
 * Resolves everything a thread refers to, once.
 *
 * A thread of forty comments naming the same task asks about it once, and a
 * rename reaches all forty without any of them being edited.
 *
 * The people it names ask for themselves (`useMentionedPerson`), in the
 * community this says they were written in.
 */
export function CommentReferences({
  contents,
  communityId,
  children,
}: {
  contents: string[];
  /** The community the contents were written in, where that is not the one
   *  the page is in. */
  communityId?: number;
  children: ReactNode;
}) {
  const { refs } = useMemo(() => collectCommentReferences(contents), [contents]);

  const { states, isFetched } = useChipStates(refs, true, communityId);

  const value = useMemo<Resolved>(() => {
    const titles = new Map<string, string>();
    for (const state of states) {
      if (state.text) titles.set(state.ref, state.text);
    }
    return { titles, ready: isFetched };
  }, [states, isFetched]);

  return (
    <CommentReferencesContext.Provider value={value}>
      <MentionCommunity.Provider value={communityId ?? null}>{children}</MentionCommunity.Provider>
    </CommentReferencesContext.Provider>
  );
}
