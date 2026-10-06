/**
 * In a notebook cell an editor is as tall as its lines, as a Jupyter cell is:
 * at least three lines, at most 400px for code and 240px for a spec, past which
 * it scrolls inside. `useNotebookEditorHeight` (components/editing) serves both
 * CodeEditor and GrammarEditor; on the canvas it leaves the editor filling its
 * node.
 *
 * The editor's look is not the notebook's alone: on the canvas too it is a gray
 * input box with no line numbers, gutter or ruler (`nodeEditorLook`). Only a
 * dashboard tile keeps Monaco's own look.
 */
import React from "react";
import { act, render } from "@testing-library/react";

import {
  clampNotebookEditorHeight,
  NOTEBOOK_CODE_EDITOR_MAX,
  NOTEBOOK_SPEC_EDITOR_MAX,
  useNotebookEditorHeight,
} from "../../components/editing/useNotebookEditorHeight";
import { nodeEditorLook } from "../../components/editing/nodeEditorLook";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";

describe("the height of an editor in a cell", () => {
  test("is its content's height", () => {
    expect(clampNotebookEditorHeight(133, 19, NOTEBOOK_CODE_EDITOR_MAX)).toBe(133);
  });

  test("is never under three lines, so a one-line cell still has room to type", () => {
    expect(clampNotebookEditorHeight(19, 19, NOTEBOOK_CODE_EDITOR_MAX)).toBe(57);
    expect(clampNotebookEditorHeight(0, 19, NOTEBOOK_CODE_EDITOR_MAX)).toBe(57);
  });

  test("stops at 400px for code and 240px for a spec, past which the editor scrolls", () => {
    expect(NOTEBOOK_CODE_EDITOR_MAX).toBe(400);
    expect(NOTEBOOK_SPEC_EDITOR_MAX).toBe(240);
    expect(clampNotebookEditorHeight(2000, 19, NOTEBOOK_CODE_EDITOR_MAX)).toBe(400);
    expect(clampNotebookEditorHeight(2000, 19, NOTEBOOK_SPEC_EDITOR_MAX)).toBe(240);
  });
});

/** Monaco as far as the hook uses it: the content height and its change event. */
function fakeEditor(contentHeight: number) {
  const editor = {
    height: contentHeight,
    listener: null as null | ((e: { contentHeight: number }) => void),
    disposed: false,
    getContentHeight: () => editor.height,
    getOption: () => 19,
    onDidContentSizeChange(cb: (e: { contentHeight: number }) => void) {
      editor.listener = cb;
      return { dispose: () => { editor.disposed = true; } };
    },
    grow(to: number) {
      editor.height = to;
      editor.listener?.({ contentHeight: to });
    },
  };
  return editor;
}
const fakeMonaco = { editor: { EditorOption: { lineHeight: 67 } } };

function Probe({ max, editor }: { max: number; editor: ReturnType<typeof fakeEditor> }) {
  const { attach, wrapperStyle } = useNotebookEditorHeight(max);
  React.useEffect(() => {
    attach(editor, fakeMonaco);
  }, []);
  return <div data-testid="wrapper" style={wrapperStyle} />;
}

function mount(on: boolean, max: number, editor: ReturnType<typeof fakeEditor>) {
  return render(
    <NotebookViewContext.Provider value={{ on, laneX: new Map(), cellWidth: 900, reveal: () => on }}>
      <Probe max={max} editor={editor} />
    </NotebookViewContext.Provider>,
  );
}

describe("useNotebookEditorHeight", () => {
  test("in the notebook view, sets the wrapper to the editor's content height as it changes", () => {
    const editor = fakeEditor(95);
    const { getByTestId, unmount } = mount(true, NOTEBOOK_CODE_EDITOR_MAX, editor);
    expect(getByTestId("wrapper").style.height).toBe("95px");

    act(() => editor.grow(171));
    expect(getByTestId("wrapper").style.height).toBe("171px");

    act(() => editor.grow(900));
    expect(getByTestId("wrapper").style.height).toBe("400px");

    unmount();
    expect(editor.disposed).toBe(true);
  });

  test("on the canvas, leaves the wrapper's height alone, so the editor fills the node", () => {
    const editor = fakeEditor(95);
    const { getByTestId } = mount(false, NOTEBOOK_SPEC_EDITOR_MAX, editor);
    expect(getByTestId("wrapper").getAttribute("style")).toBeNull();
    act(() => editor.grow(900));
    expect(getByTestId("wrapper").getAttribute("style")).toBeNull();
  });
});

describe("nodeEditorLook", () => {
  test("on the canvas and in the notebook view, makes the editor a plain gray input box: no line numbers, gutter or ruler", () => {
    const look = nodeEditorLook(false);
    expect(look.wrapperClassName).toBe("curio-node-input");
    expect(look.editorOptions).toMatchObject({
      lineNumbers: "off",
      glyphMargin: false,
      folding: false,
      renderLineHighlight: "none",
      overviewRulerLanes: 0,
    });
  });

  test("on a dashboard tile, leaves the editor as Monaco draws it", () => {
    const look = nodeEditorLook(true);
    expect(look.wrapperClassName).toBeUndefined();
    expect(look.editorOptions).toEqual({});
  });
});
