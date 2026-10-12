import { fireEvent, screen, waitFor } from "@testing-library/react";
import {
  $createNodeSelection,
  $createParagraphNode,
  $createTextNode,
  $getRoot,
  $setSelection,
  type LexicalEditor,
  type ParagraphNode,
  type SerializedEditorState,
} from "lexical";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import { Editor } from "@/components/ui/editor/editor";
import { $isImageNode } from "@/components/ui/editor/nodes/image-node";

const captionText = (text: string) => ({
  root: {
    type: "root",
    version: 1,
    direction: null,
    format: "",
    indent: 0,
    children: [
      {
        type: "paragraph",
        version: 1,
        direction: null,
        format: "",
        indent: 0,
        children: [
          { type: "text", version: 1, detail: 0, format: 0, mode: "normal", style: "", text },
        ],
      },
    ],
  },
});

const imageWithCaption = (text: string) => ({
  root: {
    type: "root",
    version: 1,
    direction: null,
    format: "",
    indent: 0,
    children: [
      {
        type: "paragraph",
        version: 1,
        direction: null,
        format: "",
        indent: 0,
        children: [
          {
            type: "image",
            version: 1,
            src: "/uploads/picture.png",
            altText: "a picture",
            width: 0,
            height: 0,
            maxWidth: 500,
            showCaption: true,
            caption: { editorState: captionText(text) },
          },
        ],
      },
    ],
  },
});

type Editable = HTMLElement & { __lexicalEditor: LexicalEditor };

const editorsIn = async (container: HTMLElement) =>
  waitFor(() => {
    const document = container.querySelector<Editable>('[data-lexical-editor="true"]');
    const caption = container.querySelector<Editable>(".ImageNode__contentEditable");
    expect(document).not.toBeNull();
    expect(caption).not.toBeNull();
    return { document: document as Editable, caption: caption as Editable };
  });

const captionOf = (state: SerializedEditorState | undefined): string => {
  const paragraph = state?.root.children[0] as { children: { caption?: unknown }[] } | undefined;
  return JSON.stringify(paragraph?.children[0]?.caption ?? null);
};

describe("an image caption", () => {
  beforeEach(() => {
    // The image component waits for its picture to load, which a test page's
    // never does.
    vi.stubGlobal(
      "Image",
      class {
        onload: (() => void) | null = null;
        set src(_value: string) {
          queueMicrotask(() => this.onload?.());
        }
      }
    );
  });

  it("is saved with the document when it is edited", async () => {
    const saved: SerializedEditorState[] = [];
    const { container } = renderPage(() => (
      <Editor
        editorSerializedState={imageWithCaption("Before") as unknown as SerializedEditorState}
        onSerializedChange={(state) => saved.push(state)}
      />
    ));

    const { caption } = await editorsIn(container);
    caption.__lexicalEditor.update(() => {
      $getRoot()
        .clear()
        .append($createParagraphNode().append($createTextNode("After")));
    });

    await waitFor(() => expect(captionOf(saved.at(-1))).toContain("After"));
  });

  it("shows a caption written elsewhere, as collaboration delivers it", async () => {
    const { container } = renderPage(() => (
      <Editor
        editorSerializedState={imageWithCaption("Before") as unknown as SerializedEditorState}
      />
    ));
    const { document, caption } = await editorsIn(container);

    // What a collaborator's edit does here: the image node's caption changes.
    document.__lexicalEditor.update(() => {
      const image = $getRoot().getFirstChildOrThrow<ParagraphNode>().getFirstChild();
      if ($isImageNode(image)) {
        image.setCaptionState(JSON.stringify(captionText("From elsewhere")));
      }
    });

    await waitFor(() => expect(caption).toHaveTextContent("From elsewhere"));
  });

  it("is no error when it was never written, on a page being read", async () => {
    // How an image is saved before anybody captions it: a root with nothing in
    // it, which Lexical refuses as an editor state.
    const state = imageWithCaption("unused");
    const image = (state.root.children[0] as { children: Record<string, unknown>[] }).children[0];
    image.showCaption = false;
    image.caption = {
      editorState: {
        root: { type: "root", format: "", indent: 0, version: 1, children: [], direction: null },
      },
    };
    const { container } = renderPage(() => (
      <Editor
        readOnly
        showToolbar={false}
        editorSerializedState={state as unknown as SerializedEditorState}
      />
    ));

    await waitFor(() => expect(container.querySelector('img[alt="a picture"]')).not.toBeNull());
    expect(container).not.toHaveTextContent("An error was thrown");
  });
});

describe("an image", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "Image",
      class {
        onload: (() => void) | null = null;
        set src(_value: string) {
          queueMicrotask(() => this.onload?.());
        }
      }
    );
  });

  it("opens full size from a page being read", async () => {
    renderPage(() => (
      <Editor
        readOnly
        showToolbar={false}
        editorSerializedState={imageWithCaption("x") as unknown as SerializedEditorState}
      />
    ));

    fireEvent.click(await screen.findByRole("button", { name: /a picture/ }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector('img[src="/uploads/picture.png"]')).not.toBeNull();
  });

  it("opens full size from a double click while the page is written", async () => {
    const { container } = renderPage(() => (
      <Editor
        showToolbar={false}
        editorSerializedState={imageWithCaption("x") as unknown as SerializedEditorState}
      />
    ));

    // A click selects it to resize, so it is no button of its own.
    const picture = await waitFor(() => {
      const image = container.querySelector<HTMLImageElement>('img[alt="a picture"]');
      expect(image).not.toBeNull();
      return image as HTMLImageElement;
    });
    expect(screen.queryByRole("button", { name: /a picture/ })).toBeNull();

    fireEvent.doubleClick(picture);

    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector('img[src="/uploads/picture.png"]')).not.toBeNull();
  });

  it("offers full size once it is selected while the page is written", async () => {
    const { container } = renderPage(() => (
      <Editor
        showToolbar={false}
        editorSerializedState={imageWithCaption("x") as unknown as SerializedEditorState}
      />
    ));
    const document = await waitFor(() => {
      const editable = container.querySelector<Editable>('[data-lexical-editor="true"]');
      expect(container.querySelector('img[alt="a picture"]')).not.toBeNull();
      return editable as Editable;
    });

    document.__lexicalEditor.update(() => {
      const image = $getRoot().getFirstChildOrThrow<ParagraphNode>().getFirstChild();
      const selection = $createNodeSelection();
      if (image) selection.add(image.getKey());
      $setSelection(selection);
    });

    fireEvent.click(await screen.findByRole("button", { name: /a picture/ }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector('img[src="/uploads/picture.png"]')).not.toBeNull();
  });
});
