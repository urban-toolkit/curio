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
 *   editor mounted) goes into the doc first, as this tab's change: an editor
 *   holding something else than what was last written into it holds the
 *   user's typing.
 * - **A node with no code in the doc** gets what its editor shows (the
 *   starter of a node just dropped), or, while it shows nothing, its first
 *   change, from a tab that edits the dataflow.
 * - **A starter is not an edit.** While the doc holds no code for the node
 *   and the editor shows none of its own (its empty spec, or a starter its
 *   node chose in this tab from its input, `hook/useStarterSpec`), nothing is
 *   written and nothing is bound: y-monaco would carry the starter into the
 *   doc as typing. The editor binds at its first edit, or when code reaches
 *   the node's text from elsewhere (another tab, an agent, Solve), which
 *   takes the starter's place. At the first edit the node's code starts as
 *   what the editor showed, and the edit is this tab's first change over it,
 *   so Ctrl+Z puts the starter back.
 * - **Focus** is the tab's `editing` presence: removing a node someone else
 *   is editing asks first.
 * - **An agent's change** to the node's code or spec, landing while the agent
 *   is writing the node (`collab/agentHolds`), has its lines marked for a
 *   moment in the agent's tint (`agentChangeMarks`), until the agent lets go
 *   of the node at the latest: decorations of the editor's own, which never
 *   reach its text or the doc.
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
import { agentHoldOf, subscribeAgentHolds } from "../../providers/collab/agentHolds";
import { agentCategoryKey } from "../menus/nodes/agentsPalette/agentCategoryStyle";
import { changedLinesBetween, dropLineMarks, markChangedLines } from "./agentChangeMarks";

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
    // Actions of this editor's own: a command (`addCommand`) is bound for every
    // editor on the page, the last one bound winning, so Ctrl+Z in one node
    // ran another's undo; and an action outranks Monaco's own binding of the
    // chord (runNodeMonacoAction.ts).
    if (typeof editor.addAction === "function" && KeyMod && KeyCode) {
        editor.addAction({
            id: "curio.undoOwnTyping",
            label: "Undo",
            keybindings: [KeyMod.CtrlCmd | KeyCode.KeyZ],
            run: () => run(false),
        });
        editor.addAction({
            id: "curio.redoOwnTyping",
            label: "Redo",
            keybindings: [KeyMod.CtrlCmd | KeyMod.Shift | KeyCode.KeyZ, KeyMod.CtrlCmd | KeyCode.KeyY],
            run: () => run(true),
        });
    }
    return slot;
}

/** Code is empty only when it holds nothing at all. */
const holdsNothing = (text: string): boolean => text === "";

export function useYMonacoBinding(
    editor: any,
    monaco: any,
    nodeId: string | undefined,
    options: {
        /** Whether this tab writes the node's code: a watcher's never does. */
        canWrite: boolean;
        /** What was last written into the editor from outside its typing. */
        baselineRef: MutableRefObject<string>;
        /** Whether *text* holds no code at all, as this editor reads it: only
         *  "" for code (the default); for a spec, its empty `{}` too. */
        isEmpty?: (text: string) => boolean;
        /** A starter the node chose in this tab from its input, which the
         *  editor is handed as its content and which is not the node's code
         *  until someone edits it; null when the editor is handed none. */
        starter?: string | null;
    },
): void {
    const binding = useDocBinding();
    const provider = binding?.synced ? binding.provider : null;
    const { canWrite, baselineRef, isEmpty = holdsNothing, starter = null } = options;

    // Run again when the editor is handed a starter: the bind it had, to the
    // node's empty text, goes before the starter lands (this effect's cleanup
    // runs before the effect that writes it into the editor), and the editor
    // waits for an edit or for code instead.
    useEffect(() => {
        if (!editor || !monaco || !nodeId || !provider) return;
        const { doc, awareness } = provider;
        const nodes = doc.getMap("nodes");
        let disposed = false;
        let current: { binding: { destroy(): void }; undo: Y.UndoManager; text: Y.Text; release: () => void } | null = null;
        let watchedNode: Y.Map<unknown> | null = null;
        // While the doc holds no code for the node: the editor's changes, for
        // its first edit, and the node's empty text, for code written into it
        // elsewhere; and whether such code came, which the bind marks.
        let edits: { dispose(): void } | null = null;
        let watchedText: Y.Text | null = null;
        let codeCame = false;
        // That first edit came, and the bind writes it over what the editor
        // showed before it.
        let edited = false;
        const undo = takeUndo(editor, monaco);

        /** Whether an editor showing *shown* shows none of the node's code:
         *  nothing, or the starter it was handed. */
        const showsNoCode = (shown: string) => isEmpty(shown) || (starter !== null && shown === starter);

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
            if (!event.keysChanged.has(CONTENT)) return;
            const text = textOf();
            if (waiting() && !event.transaction.local && text && !isEmpty(text.toString())) codeCame = true;
            void bind();
        };

        const watchNode = () => {
            const node = nodes.get(nodeId);
            const next = node instanceof Y.Map ? (node as Y.Map<unknown>) : null;
            if (next === watchedNode) return;
            watchedNode?.unobserve(onNodeChange);
            watchedNode = next;
            watchedNode?.observe(onNodeChange);
        };

        const waiting = () => edits !== null || watchedText !== null;

        const stopWaiting = () => {
            edits?.dispose();
            edits = null;
            watchedText?.unobserve(onCodeCame);
            watchedText = null;
        };

        // Code written into the node's empty text elsewhere binds the editor,
        // which then shows it in place of what it showed.
        function onCodeCame(event: Y.YTextEvent) {
            if (!watchedText || isEmpty(watchedText.toString())) return;
            if (!event.transaction.local) codeCame = true;
            void bind();
        }

        // While the doc holds no code for the node (*text* is its empty text,
        // or null when it has none): the editor's first edit becomes the
        // node's code, from a tab that edits the dataflow, and code written
        // into *text* elsewhere binds the editor.
        const awaitCode = (text: Y.Text | null) => {
            const model = editor.getModel?.();
            if (!edits && canWrite && model?.onDidChangeContent) {
                let shown = model.getValue();
                edits = model.onDidChangeContent(() => {
                    const before = shown;
                    shown = model.getValue();
                    const node = nodes.get(nodeId);
                    if (disposed || showsNoCode(shown) || !(node instanceof Y.Map)) return;
                    const held = node.get(CONTENT);
                    stopWaiting();
                    // The node's code starts as what the editor showed; the
                    // bind writes the edit over it as this tab's change.
                    doc.transact(() => {
                        if (held instanceof Y.Text) replaceText(held, before);
                        else node.set(CONTENT, new Y.Text(before));
                    }, CANVAS_ORIGIN);
                    edited = true;
                    void bind();
                });
            }
            if (text !== watchedText) {
                watchedText?.unobserve(onCodeCame);
                watchedText = text;
                watchedText?.observe(onCodeCame);
            }
        };

        const bind = async () => {
            watchNode();
            let text = textOf();
            if (current && current.text === text) return;
            unbind();
            const inEditor = editor.getModel?.()?.getValue?.();
            if (typeof inEditor === "string" && inEditor !== "" && isEmpty(text?.toString() ?? "") && showsNoCode(inEditor)) {
                // A starter is not an edit: bound, y-monaco would write what
                // the editor shows into the node's code.
                awaitCode(text);
                return;
            }
            if (!text && canWrite) {
                // A node with no code in the doc takes what its editor shows,
                // the starter a palette or a template gave it: the code a save
                // of this canvas writes.
                const node = nodes.get(nodeId);
                if (node instanceof Y.Map && typeof inEditor === "string" && inEditor !== "") {
                    doc.transact(() => node.set(CONTENT, new Y.Text(inEditor)), CANVAS_ORIGIN);
                    text = textOf();
                }
            }
            if (!text) {
                awaitCode(null);
                return;
            }
            stopWaiting();
            const { MonacoBinding } = await import("y-monaco");
            const model = editor.getModel?.();
            const ytext = textOf();
            if (disposed || !model || !ytext || current) return;
            const typed = model.getValue();
            // Made before the editor's typing goes in, so Ctrl+Z undoes it.
            const manager = new Y.UndoManager(ytext, { trackedOrigins: new Set<unknown>([CANVAS_ORIGIN]) });
            const firstEdit = edited;
            edited = false;
            if (canWrite && typed !== ytext.toString() && (firstEdit || typed !== baselineRef.current)) {
                doc.transact(() => replaceText(ytext, typed), CANVAS_ORIGIN);
            }
            const made = new MonacoBinding(ytext, model, new Set([editor]), awareness);
            manager.addTrackedOrigin(made);
            // Code an agent wrote while the editor waited for code replaced
            // what it showed: its lines are marked as a change of the agent's.
            const landed = codeCame;
            codeCame = false;
            const writer = landed ? agentHoldOf(nodeId) : null;
            if (writer?.writes === "code" || writer?.writes === "spec") {
                markChangedLines(editor, changedLinesBetween(typed, ytext.toString()), agentCategoryKey(writer.category));
            }
            // Observed after y-monaco, so a change is in the editor when its
            // lines are marked. What this tab wrote is never an agent's.
            let shown = ytext.toString();
            const onLanded = (event: Y.YTextEvent) => {
                const before = shown;
                shown = ytext.toString();
                if (event.transaction.local) return;
                const hold = agentHoldOf(nodeId);
                if (hold?.writes !== "code" && hold?.writes !== "spec") return;
                markChangedLines(editor, changedLinesBetween(before, shown), agentCategoryKey(hold.category));
            };
            ytext.observe(onLanded);
            // The marks go when the agent lets go of the node, at the latest:
            // what a tab shows once the agent is done is the node as it is.
            const unheld = subscribeAgentHolds(() => {
                if (!agentHoldOf(nodeId)) dropLineMarks(editor);
            });
            const bound = markBound(doc, nodeId);
            const release = () => {
                ytext.unobserve(onLanded);
                unheld();
                dropLineMarks(editor);
                bound();
            };
            current = { binding: made, undo: manager, text: ytext, release };
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
            stopWaiting();
            focus?.dispose?.();
            blur?.dispose?.();
            const state = awareness.getLocalState() as { editing?: string | null } | null;
            if (state?.editing === nodeId) setEditing(awareness, null);
            unbind();
        };
    }, [editor, monaco, nodeId, provider, canWrite, baselineRef, isEmpty, starter]);
}
