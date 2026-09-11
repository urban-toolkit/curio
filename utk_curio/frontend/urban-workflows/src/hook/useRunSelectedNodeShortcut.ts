import { useEffect, useRef } from "react";
import { useReactFlow } from "reactflow";
import { isRunNodeChord, isTypingTarget } from "../components/canvasKeyBindings";
import { modalStackDepth } from "../components/ModalShell";
import { useFlowContext } from "../providers/FlowProvider";

/**
 * Ctrl/Cmd + Enter runs the selected node when no editor has focus (#223).
 *
 * The in-editor half lives in ``runNodeMonacoAction``: Monaco owns the chord
 * while the caret is inside it — and already bound it to "insert line below",
 * which is what the keystroke used to do. So the two halves cannot be one
 * handler. This covers the other way a node is "current": clicked on the
 * canvas, with its editor closed.
 *
 * A plain window listener rather than React Flow's ``useKeyPress``, which fires
 * for modifier chords inside inputs and would run a node while the user is
 * typing into an agent chat.
 */
export function useRunSelectedNodeShortcut(enabled: boolean = true): void {
  const reactFlow = useReactFlow();
  const { playNodesUpTo } = useFlowContext();

  // The listener is attached once; reading through a ref keeps it on the
  // current play function instead of the one from the render that bound it.
  const playRef = useRef(playNodesUpTo);
  playRef.current = playNodesUpTo;

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isRunNodeChord(event)) return;
      // An open dialog owns the keyboard; running a node behind it would act
      // on something the user cannot see.
      if (modalStackDepth() > 0) return;
      if (isTypingTarget(event.target)) return;

      const selected = reactFlow.getNodes().filter((n) => n.selected);
      // Exactly one, deliberately. With none there is no "current" node, and
      // with several "run the current node" has no answer — running all of
      // them is a different action, and Run All already owns it.
      if (selected.length !== 1) return;

      event.preventDefault();
      // Same entry point as the node's play button, so the shortcut cannot
      // diverge from what clicking run does.
      playRef.current(selected[0].id);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, reactFlow]);
}

export default useRunSelectedNodeShortcut;
