/**
 * Ctrl/Cmd + Enter runs the node you are editing (#223).
 *
 * The report says "nothing happens", which understates it: Monaco already binds
 * this chord. ``InsertLineAfterAction`` claims ``CtrlCmd | Enter`` at
 * ``KeybindingWeight.EditorContrib``, so pressing it inserted a blank line
 * below the cursor — the muscle memory from Jupyter silently edited the code
 * instead of running it.
 *
 * So this has to OUTRANK a built-in, not fill a gap. ``editor.addAction``
 * registers at the standalone-editor weight, which sits above EditorContrib;
 * ``addCommand`` would not reliably displace an existing action's binding.
 */

/** Anything with the two Monaco methods used here, so callers need no monaco types. */
interface EditorLike {
  addAction: (action: {
    id: string;
    label: string;
    keybindings: number[];
    run: () => void;
  }) => { dispose: () => void };
}

interface MonacoLike {
  KeyMod: { CtrlCmd: number };
  KeyCode: { Enter: number };
}

export const RUN_NODE_ACTION_ID = "curio.runNode";
export const RUN_NODE_ACTION_LABEL = "Run this node";

/**
 * Bind the chord inside *editor* to *run*.
 *
 * *run* is read through a ref-like getter rather than captured: ``onMount``
 * fires once per editor, so a captured callback would pin the first render's
 * closure — and the run path depends on context that changes (the node's
 * current code, the flow's play function). Returns the disposer.
 */
const NOOP_DISPOSER = { dispose: () => {} };

export function registerRunNodeAction(
  editor: EditorLike,
  monaco: MonacoLike,
  getRun: () => (() => void) | undefined,
): { dispose: () => void } {
  // A keyboard convenience must not be able to break the editor it is attached
  // to. ``onMount`` runs inside React's commit, so a throw here would take the
  // whole node down over a shortcut — and the objects come from whatever
  // Monaco build is loaded, which older versions and test fakes do not
  // guarantee the shape of.
  if (
    typeof editor?.addAction !== "function" ||
    typeof monaco?.KeyMod?.CtrlCmd !== "number" ||
    typeof monaco?.KeyCode?.Enter !== "number"
  ) {
    return NOOP_DISPOSER;
  }

  return editor.addAction({
    id: RUN_NODE_ACTION_ID,
    label: RUN_NODE_ACTION_LABEL,
    keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
    run: () => {
      // Defensive: an editor can outlive the context that supplied the
      // callback (a node removed while its editor is focused).
      getRun()?.();
    },
  });
}
