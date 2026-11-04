import { useEffect, useRef } from "react";

import { changedStretch } from "../utils/textStretch";

// The slice of a Monaco editor instance this hook drives. Structural (rather
// than monaco-editor's own types) so tests can pass a plain object and the
// hook stays agnostic of the @monaco-editor/react loader.
export interface MonacoEditorLike {
    getModel(): {
        getFullModelRange(): unknown;
        validatePosition?(position: unknown): unknown;
        getPositionAt?(offset: number): { lineNumber: number; column: number };
    } | null;
    getValue(): string;
    setValue(value: string): void;
    getPosition?(): unknown | null;
    setPosition?(position: unknown): void;
    executeEdits?(
        source: string,
        edits: Array<{ range: unknown; text: string; forceMoveMarkers?: boolean }>,
    ): boolean;
    pushUndoStop?(): void;
}

// Make the editor's content *value* while keeping the user's undo history and
// cursor. `setValue` would wipe the undo stack and park the cursor at the
// document start; `executeEdits` parks it at the end of what it wrote, so
// edit, then restore the previous position clamped into the new content. The
// edit rewrites only the stretch where the two differ (`changedStretch`): a
// node's code bound to the dataflow's doc takes it as that stretch alone, so
// someone else's typing elsewhere in it stays. A read-only editor (a
// dashboard tile's) refuses every edit, so it gets the content whole: it has
// no undo history to keep.
function setEditorContent(editor: MonacoEditorLike, value: string) {
    const old = editor.getValue();
    if (old === value) return;
    const model = editor.getModel();
    if (!model || !editor.executeEdits) {
        editor.setValue(value);
        return;
    }
    const prevPosition = editor.getPosition?.() ?? null;
    editor.pushUndoStop?.();
    let edit = { range: model.getFullModelRange(), text: value, forceMoveMarkers: true };
    if (typeof model.getPositionAt === "function") {
        const { start, endOld, endNew } = changedStretch(old, value);
        const from = model.getPositionAt(start);
        const to = model.getPositionAt(endOld);
        edit = {
            range: {
                startLineNumber: from.lineNumber,
                startColumn: from.column,
                endLineNumber: to.lineNumber,
                endColumn: to.column,
            },
            text: value.slice(start, endNew),
            forceMoveMarkers: true,
        };
    }
    const edited = editor.executeEdits("curio.external-content", [edit]);
    if (edited === false) {
        editor.setValue(value);
        return;
    }
    editor.pushUndoStop?.();
    if (prevPosition && editor.setPosition) {
        editor.setPosition(
            model.validatePosition ? model.validatePosition(prevPosition) : prevPosition,
        );
    }
}

/**
 * Owns the "external content update" contract for a node's Monaco editor
 * (dev/70). The editor is uncontrolled while the user types — Monaco's model
 * is the source of truth and React only mirrors it via onChange. Content is
 * written INTO the editor only through this hook:
 *
 * - `externalValue` (the node's `defaultValue` chain: initial load, dataset
 *   drop, LLM apply, provenance navigation) is applied only when it is a
 *   defined string that differs from the baseline. `undefined`, or a flip
 *   back to the already-applied value — the oscillation that used to reset
 *   the Autark editor — never touches the editor.
 * - `applyValue` is the imperative channel for other external writers
 *   (a run's code put back from the provenance drawer).
 *
 * `baselineRef` tracks the as-loaded / last-externally-applied content: an
 * editor whose content differs from it holds the user's typing.
 */
export function useMonacoExternalValue({
    externalValue,
    initialContent = "",
    onExternalApply,
}: {
    externalValue: string | undefined;
    /** What the editor model starts as before any content lands ("" / "{}"). */
    initialContent?: string;
    /** Sync React-side mirrors (state, widget markers) after a prop-driven apply. */
    onExternalApply: (value: string) => void;
}) {
    const editorRef = useRef<MonacoEditorLike | null>(null);
    const baselineRef = useRef<string>(initialContent);
    // Latest callback without re-running the externalValue effect.
    const onExternalApplyRef = useRef(onExternalApply);
    onExternalApplyRef.current = onExternalApply;

    // Write `value` into the editor (cursor- and undo-preserving) and move the
    // baseline. Shared by the prop-driven path below and imperative callers.
    const applyValue = (value: string) => {
        baselineRef.current = value;
        const editor = editorRef.current;
        if (editor) setEditorContent(editor, value);
    };

    // Wire the editor instance in onMount. The external value can land before
    // Monaco finishes mounting (its loader is async), so sync the model to any
    // baseline it missed.
    const attachEditor = (editor: MonacoEditorLike) => {
        editorRef.current = editor;
        if (editor.getValue() !== baselineRef.current) {
            setEditorContent(editor, baselineRef.current);
        }
    };

    useEffect(() => {
        if (typeof externalValue !== "string") return;
        if (externalValue === baselineRef.current) return;
        applyValue(externalValue);
        onExternalApplyRef.current(externalValue);
    }, [externalValue]);

    return { baselineRef, applyValue, attachEditor };
}
