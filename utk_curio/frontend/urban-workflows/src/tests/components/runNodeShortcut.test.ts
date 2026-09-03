/**
 * Ctrl/Cmd + Enter runs the node you are editing (#223).
 *
 * The report says "nothing happens", which understates it. Monaco already binds
 * this chord: ``InsertLineAfterAction`` claims ``CtrlCmd | Enter``, so the
 * Jupyter muscle memory silently inserted a blank line into the code instead of
 * running it. The fix has to OUTRANK a built-in, not fill a gap — which is why
 * the in-editor half uses ``editor.addAction`` and is separate from the canvas
 * half tested here.
 */
import {
  isRunNodeChord,
  isTypingTarget,
  RUN_NODE_SHORTCUT_LABEL,
} from "../../components/canvasKeyBindings";
import {
  RUN_NODE_ACTION_ID,
  registerRunNodeAction,
} from "../../components/editing/runNodeMonacoAction";

const chord = (over: Partial<Record<string, unknown>> = {}) =>
  ({
    key: "Enter",
    ctrlKey: true,
    metaKey: false,
    shiftKey: false,
    altKey: false,
    ...over,
  }) as Parameters<typeof isRunNodeChord>[0];

describe("isRunNodeChord", () => {
  test("Ctrl+Enter and Cmd+Enter both count", () => {
    // Accepted regardless of platform: a Mac user on an external PC keyboard
    // reaches for Ctrl, and nothing else claims this chord.
    expect(isRunNodeChord(chord())).toBe(true);
    expect(isRunNodeChord(chord({ ctrlKey: false, metaKey: true }))).toBe(true);
  });

  test("plain Enter is not it", () => {
    expect(isRunNodeChord(chord({ ctrlKey: false }))).toBe(false);
  });

  test("Shift+Enter is not it", () => {
    // In a code editor Shift+Enter is a newline. Taking it would make the
    // editor unusable for multi-line code.
    expect(isRunNodeChord(chord({ shiftKey: true }))).toBe(false);
  });

  test("Alt does not count as the modifier", () => {
    expect(isRunNodeChord(chord({ ctrlKey: false, altKey: true }))).toBe(false);
  });

  test("another key with the modifier is not it", () => {
    expect(isRunNodeChord(chord({ key: "s" }))).toBe(false);
  });
});

describe("isTypingTarget", () => {
  const el = (html: string) => {
    const host = document.createElement("div");
    host.innerHTML = html;
    return host.firstElementChild as HTMLElement;
  };

  test("stands down inside form fields", () => {
    // The canvas binding is a window listener, so it sees keystrokes aimed at
    // every field on the page — an agent chat composer, a rename box.
    for (const html of ["<input />", "<textarea></textarea>", "<select></select>"]) {
      expect(isTypingTarget(el(html))).toBe(true);
    }
  });

  test("stands down inside Monaco", () => {
    // Not because typing is happening, but because Monaco registers the chord
    // itself — letting the window handler fire too would run the node twice.
    const editor = el('<div class="monaco-editor"><div class="line"></div></div>');
    expect(isTypingTarget(editor.querySelector(".line"))).toBe(true);
  });

  test("does not stand down on the canvas", () => {
    expect(isTypingTarget(el('<div class="react-flow__pane"></div>'))).toBe(false);
  });

  test("survives a null or non-element target", () => {
    expect(isTypingTarget(null)).toBe(false);
    expect(isTypingTarget({} as EventTarget)).toBe(false);
  });
});

describe("the Monaco action", () => {
  const monaco = { KeyMod: { CtrlCmd: 2048 }, KeyCode: { Enter: 3 } };

  test("registers the chord through addAction", () => {
    // addAction, not addCommand: it registers at the standalone-editor weight,
    // above the EditorContrib weight that InsertLineAfterAction holds.
    const added: any[] = [];
    const editor = {
      addAction: (a: any) => {
        added.push(a);
        return { dispose: jest.fn() };
      },
    };

    registerRunNodeAction(editor, monaco, () => () => {});
    expect(added).toHaveLength(1);
    expect(added[0].id).toBe(RUN_NODE_ACTION_ID);
    expect(added[0].keybindings).toEqual([monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter]);
  });

  test("calls the CURRENT run function, not the one bound at mount", () => {
    // onMount fires once per editor, so a captured callback would pin the first
    // render's closure and run a stale node.
    let added: any;
    const editor = {
      addAction: (a: any) => {
        added = a;
        return { dispose: jest.fn() };
      },
    };
    const first = jest.fn();
    const second = jest.fn();
    let current = first;

    registerRunNodeAction(editor, monaco, () => current);
    current = second;
    added.run();

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  test("survives the run function going away", () => {
    // An editor can outlive the context that supplied it — a node removed
    // while its editor has focus.
    let added: any;
    const editor = {
      addAction: (a: any) => {
        added = a;
        return { dispose: jest.fn() };
      },
    };
    registerRunNodeAction(editor, monaco, () => undefined);
    expect(() => added.run()).not.toThrow();
  });
});

describe("the shortcut label", () => {
  test("names a modifier and the key", () => {
    expect(RUN_NODE_SHORTCUT_LABEL).toMatch(/^(Ctrl|Cmd)\+Enter$/);
  });
});
