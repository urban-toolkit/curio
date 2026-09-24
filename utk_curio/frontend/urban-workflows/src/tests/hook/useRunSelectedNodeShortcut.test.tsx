import React from "react";
import { render, fireEvent } from "@testing-library/react";

/**
 * The canvas half of Ctrl/Cmd+Enter (#223), which had no test of any kind
 * (#354).
 *
 * ``runNodeShortcut.test.ts`` covers the pure predicates and the Monaco action
 * registration. This hook is the other half: the window listener that runs the
 * selected node when no editor has focus. It is a global keydown listener, so
 * every one of its stand-down conditions is load-bearing - without them the
 * chord runs a node while the user is typing into an agent chat, or while a
 * dialog they cannot see through owns the keyboard.
 */
const mockPlayNodesUpTo = jest.fn();
let mockNodes: Array<{ id: string; selected?: boolean }> = [];
let mockModalDepth = 0;

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => mockNodes }),
}));
// Indirected so a test can swap the play function between renders, which is
// what the ref inside the hook exists to cope with.
let mockCurrentPlay: (id: string) => void = (id) => mockPlayNodesUpTo(id);
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playNodesUpTo: (id: string) => mockCurrentPlay(id) }),
}));
jest.mock("../../components/ModalShell", () => ({
  modalStackDepth: () => mockModalDepth,
}));

import { useRunSelectedNodeShortcut } from "../../hook/useRunSelectedNodeShortcut";

function Host({ enabled = true }: { enabled?: boolean }) {
  useRunSelectedNodeShortcut(enabled);
  return (
    <div>
      <input data-testid="text-field" />
      <textarea data-testid="composer" />
      <div className="monaco-editor">
        <span data-testid="editor-gutter" />
      </div>
      <div data-testid="canvas" />
    </div>
  );
}

/** The chord, dispatched at *target* (defaults to the document body). */
function pressRunChord(
  target: Document | Element | Window | Node = document.body,
  init: Partial<KeyboardEventInit> = {},
) {
  return fireEvent.keyDown(target, {
    key: "Enter",
    ctrlKey: true,
    bubbles: true,
    ...init,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockNodes = [{ id: "n1", selected: true }];
  mockModalDepth = 0;
  mockCurrentPlay = (id) => mockPlayNodesUpTo(id);
});

describe("useRunSelectedNodeShortcut", () => {
  test("runs the one selected node", () => {
    render(<Host />);
    pressRunChord();
    expect(mockPlayNodesUpTo).toHaveBeenCalledWith("n1");
  });

  test("accepts Cmd+Enter as well as Ctrl+Enter", () => {
    // Both modifiers work on every platform by design (isRunNodeChord).
    render(<Host />);
    pressRunChord(document.body, { ctrlKey: false, metaKey: true });
    expect(mockPlayNodesUpTo).toHaveBeenCalledWith("n1");
  });

  test("takes the keystroke, so nothing else acts on it too", () => {
    render(<Host />);
    const notPrevented = pressRunChord();
    // fireEvent returns false when preventDefault was called.
    expect(notPrevented).toBe(false);
  });

  test("ignores a plain Enter and a Shift+Enter", () => {
    // Shift+Enter is a newline in an editor; taking it would make multi-line
    // code impossible to write.
    render(<Host />);
    pressRunChord(document.body, { ctrlKey: false });
    pressRunChord(document.body, { shiftKey: true });
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });
});

describe("the conditions it stands down for", () => {
  test("does nothing when disabled", () => {
    // MainCanvas passes !dashboardOn: dashboard mode hides the play button, so
    // the shortcut must not be a hidden way to reach it.
    render(<Host enabled={false} />);
    pressRunChord();
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });

  test("does nothing while a dialog is open", () => {
    // Running a node behind a modal acts on something the user cannot see.
    mockModalDepth = 1;
    render(<Host />);
    pressRunChord();
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });

  test.each([
    ["an input", "text-field"],
    ["a textarea", "composer"],
    ["anything inside Monaco", "editor-gutter"],
  ])("does nothing while typing in %s", (_label, testId) => {
    // Monaco is excluded for a different reason than the others: it binds the
    // chord itself, so firing here too would run the node twice.
    const { getByTestId } = render(<Host />);
    pressRunChord(getByTestId(testId));
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });

  test("does nothing when no node is selected", () => {
    mockNodes = [{ id: "n1" }, { id: "n2" }];
    render(<Host />);
    pressRunChord();
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });

  test("does nothing when several nodes are selected", () => {
    // "Run the current node" has no answer with a multi-selection, and running
    // all of them is a different action that Run All already owns.
    mockNodes = [{ id: "n1", selected: true }, { id: "n2", selected: true }];
    render(<Host />);
    pressRunChord();
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });
});

describe("its listener lifecycle", () => {
  test("stops listening once unmounted", () => {
    // A window listener that outlives the canvas would run nodes on a page
    // that no longer shows them.
    const { unmount } = render(<Host />);
    unmount();
    pressRunChord();
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });

  test("calls the current play function, not the one from the binding render", () => {
    // The listener is attached once and reads through a ref. Without that it
    // would keep calling the closure from the render that bound it, which goes
    // stale on any FlowProvider re-render.
    const { rerender } = render(<Host />);
    const laterPlay = jest.fn();
    mockCurrentPlay = laterPlay;
    rerender(<Host />);

    pressRunChord();

    expect(laterPlay).toHaveBeenCalledWith("n1");
    expect(mockPlayNodesUpTo).not.toHaveBeenCalled();
  });
});
