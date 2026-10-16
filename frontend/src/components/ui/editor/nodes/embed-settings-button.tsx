import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import type { NodeKey } from "lexical";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useEditorModal } from "@/components/ui/editor/editor-hooks/use-modal";
import { LazyEmbedDialog } from "@/components/ui/editor/plugins/lazy-embed-dialog";

/** The button that reopens an embed's settings, where the page can be edited. */
export function EmbedSettingsButton({ nodeKey }: { nodeKey: NodeKey }) {
  const { t } = useTranslation("editor");
  const [editor] = useLexicalComposerContext();
  const [modal, showModal] = useEditorModal();
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="-my-1 size-7 shrink-0"
        onClick={() =>
          showModal(t("embeds.settings"), (onClose) => (
            <LazyEmbedDialog activeEditor={editor} nodeKey={nodeKey} onClose={onClose} />
          ))
        }
        aria-label={t("embeds.settings")}
        title={t("embeds.settings")}
      >
        <Settings2 className="size-3.5" />
      </Button>
      {modal}
    </>
  );
}
