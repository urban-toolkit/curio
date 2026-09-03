/**
 * Canvas keyboard bindings.
 *
 * Extracted so they can be asserted directly: MainCanvas pulls in the whole
 * editor/registry/vega module graph, which is far too much to mount just to
 * check a key list.
 */

/**
 * Keys that delete the current canvas selection.
 *
 * React Flow's own default is `'Backspace'` only, which left Windows users with
 * a dead Delete key (#153). `useKeyPress` treats each array entry as an
 * independent binding and early-returns on `isInputDOMNode`, so neither key can
 * fire while the caret is in Monaco or a text input.
 */
export const DEFAULT_DELETE_KEY_CODES: string[] = ['Backspace', 'Delete'];


/**
 * Is *event* the "run this node" chord? (#223)
 *
 * Cmd on macOS, Ctrl elsewhere, matching Monaco's own ``KeyMod.CtrlCmd`` so the
 * in-editor and on-canvas bindings are the same key to the user. Both are
 * accepted regardless of platform rather than sniffing the user agent: a Mac
 * user on an external PC keyboard reaches for Ctrl, and there is nothing else
 * on this chord to conflict with.
 *
 * Shift+Enter is deliberately NOT it. In a code editor that is a newline, and
 * taking it would make the editor unusable for multi-line code.
 */
export function isRunNodeChord(event: {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  if (event.key !== "Enter") return false;
  if (event.shiftKey || event.altKey) return false;
  return event.ctrlKey || event.metaKey;
}

/**
 * Should a global key handler stand down for *target*?
 *
 * The canvas-level binding is a window listener, so it sees keystrokes aimed at
 * every field on the page: an agent chat composer, a rename box, a dialog. Each
 * of those either owns Enter already or is somewhere running a node would be a
 * non-sequitur.
 *
 * Monaco is excluded too, but for a different reason: it registers the chord
 * itself, so letting the window handler also fire would run the node twice.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== "function") return false;
  const tag = el.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if (el.isContentEditable) return true;
  // Monaco renders its caret into a textarea, but a click on the gutter or the
  // margin leaves focus on a non-input descendant of the editor.
  return el.closest(".monaco-editor") != null;
}

/**
 * How to write the run chord for a human, per platform.
 *
 * Both modifiers work everywhere (see ``isRunNodeChord``); this is only about
 * naming the one a given user is most likely to reach for.
 */
export const RUN_NODE_SHORTCUT_LABEL: string =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform ?? "")
    ? "Cmd+Enter"
    : "Ctrl+Enter";
