/**
 * A node's code editor, bound to the node's code in the dataflow's doc
 * (y-monaco): each keystroke anyone types shows in every tab as it is typed,
 * with each person's cursor in their color (`presence.remoteCursorStyle`).
 *
 * - **Undo is per node.** Ctrl+Z (Cmd+Z) and redo run a Yjs `UndoManager` on
 *   this node's code that tracks this tab's changes alone, so it never undoes
 *   someone else's typing. It takes the place of Monaco's own undo, which
 *   would replay this tab's stack over code others changed since.
 * - **Code typed before the bind** (the doc's first sync came after the
 *   editor mounted) goes into the doc first: an editor holding something
 *   else than what was last written into it holds the user's typing.
 * - **A node with no code yet** gets it in the doc at its editor's first
 *   change, from a tab that edits the dataflow.
 * - **Focus** is the tab's `editing` presence: removing a node someone else
 *   is editing asks first.
 *
 * Nothing binds while the canvas is not bound to a doc (a dataflow never
 * saved, a hosted guest's own canvas, the dashboard): the editor is then
 * Monaco's alone, its undo included.
 */
import { useEffect, type MutableRefObject } from "react";
import * as Y from "yjs";

import { CANVAS_ORIGIN, useDocBinding } from "../../providers/collab/docContext";
import { CONTENT, replaceText } from "../../providers/collab/docMapping";
import { markBound } from "../../providers/collab/boundTexts";
import { setEditing } from "../../providers/collab/presence";

/** The undo each editor's Ctrl+Z runs, while it is bound. */
const undoOf = new WeakMap<object, { manager: Y.UndoManager | null }>();

/** Ctrl+Z and redo in *editor* through its node's `UndoManager` while bound,
 *  Monaco's own otherwise. Registered once per editor. */
function takeUndo(editor: any, monaco: any): { manager: Y.UndoManager | null } {
    let slot = undoOf.get(editor);
    if (slot) return slot;
    slot = { manager: null };
    undoOf.set(editor, slot);
    const run = (redo: boolean) => {
        const manager = slot!.manager;
        if (manager) {
            if (redo) manager.redo();
            else manager.undo();
            return;
        }
        editor.trigger?.("keyboard", redo ? "redo" : "undo", null);
    };
    const { KeyMod, KeyCode } = monaco ?? {};
    if (typeof editor.addCommand === "function" && KeyMod && KeyCode) {
        editor.addCommand(KeyMod.CtrlCmd | KeyCode.KeyZ, () => run(false));
        editor.addCommand(KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.KeyZ, () => run(true));
        editor.addCommand(KeyMod.CtrlCmd | KeyCode.KeyY, () => run(true));
    }
    return slot;
}

export function useYMonacoBinding(
    editor: any,
    monaco: any,
    nodeId: string | undefined,
    options: {
        /** Whether this tab writes the node's code: a watcher's never does. */
        canWrite: boolean;
        /** What was last written into the editor from outside its typing. */
        baselineRef: MutableRefObject<string>;
    },
): void {
    const binding = useDocBinding();
    const provider = binding?.synced ? binding.provider : null;
    const { canWrite, baselineRef } = options;

    useEffect(() => {
        if (!editor || !monaco || !nodeId || !provider) return;
        const { doc, awareness } = provider;
        const nodes = doc.getMap("nodes");
        let disposed = false;
        let current: { binding: { destroy(): void }; undo: Y.UndoManager; text: Y.Text; release: () => void } | null = null;
        let watchedNode: Y.Map<unknown> | null = null;
        let firstChange: { dispose(): void } | null = null;
        const undo = takeUndo(editor, monaco);

        const textOf = (): Y.Text | null => {
            const node = nodes.get(nodeId);
            const content = node instanceof Y.Map ? node.get(CONTENT) : null;
            return content instanceof Y.Text ? content : null;
        };

        const unbind = () => {
            if (!current) return;
            current.binding.destroy();
            current.undo.destroy();
            current.release();
            current = null;
            undo.manager = null;
        };

        const onNodeChange = (event: Y.YMapEvent<unknown>) => {
            if (event.keysChanged.has(CONTENT)) void bind();
        };

        const watchNode = () => {
            const node = nodes.get(nodeId);
            const next = node instanceof Y.Map ? (node as Y.Map<unknown>) : null;
            if (next === watchedNode) return;
            watchedNode?.unobserve(onNodeChange);
            watchedNode = next;
            watchedNode?.observe(onNodeChange);
        };

        // A node with no code in the doc gets the editor's, at its first change.
        const awaitFirstChange = () => {
            const model = editor.getModel?.();
            if (firstChange || !canWrite || !model?.onDidChangeContent) return;
            firstChange = model.onDidChangeContent(() => {
                const node = nodes.get(nodeId);
                firstChange?.dispose();
                firstChange = null;
                if (disposed || !(node instanceof Y.Map) || node.get(CONTENT) instanceof Y.Text) return;
                doc.transact(() => node.set(CONTENT, new Y.Text(model.getValue())), CANVAS_ORIGIN);
            });
        };

        const bind = async () => {
            watchNode();
            const text = textOf();
            if (current && current.text === text) return;
            unbind();
            if (!text) {
                awaitFirstChange();
                return;
            }
            firstChange?.dispose();
            firstChange = null;
            const { MonacoBinding } = await import("y-monaco");
            const model = editor.getModel?.();
            const ytext = textOf();
            if (disposed || !model || !ytext || current) return;
            const typed = model.getValue();
            if (canWrite && typed !== ytext.toString() && typed !== baselineRef.current) {
                doc.transact(() => replaceText(ytext, typed), CANVAS_ORIGIN);
            }
            const made = new MonacoBinding(ytext, model, new Set([editor]), awareness);
            const manager = new Y.UndoManager(ytext, { trackedOrigins: new Set<unknown>([made, CANVAS_ORIGIN]) });
            current = { binding: made, undo: manager, text: ytext, release: markBound(doc, nodeId) };
            undo.manager = manager;
        };

        const onNodes = (event: Y.YMapEvent<unknown>) => {
            if (event.keysChanged.has(nodeId)) void bind();
        };
        nodes.observe(onNodes);
        void bind();

        const focus = editor.onDidFocusEditorText?.(() => setEditing(awareness, nodeId));
        const blur = editor.onDidBlurEditorText?.(() => {
            setEditing(awareness, null);
            awareness.setLocalStateField("selection", null);
        });
        if (editor.hasTextFocus?.()) setEditing(awareness, nodeId);

        return () => {
            disposed = true;
            nodes.unobserve(onNodes);
            watchedNode?.unobserve(onNodeChange);
            firstChange?.dispose();
            focus?.dispose?.();
            blur?.dispose?.();
            const state = awareness.getLocalState() as { editing?: string | null } | null;
            if (state?.editing === nodeId) setEditing(awareness, null);
            unbind();
        };
    }, [editor, monaco, nodeId, provider, canWrite, baselineRef]);
}
