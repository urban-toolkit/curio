import { useEffect, useRef } from "react";

// The slice of a Monaco editor instance this hook drives. Structural (rather
// than monaco-editor's own types) so tests can pass a plain object and the
// hook stays agnostic of the @monaco-editor/react loader.
export interface MonacoEditorLike {
    getModel(): {
        getFullModelRange(): unknown;
        validatePosition?(position: unknown): unknown;
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

// Replace the editor's whole content while keeping the user's undo history
// and cursor. `setValue` would wipe the undo stack and park the cursor at the
// document start; `executeEdits` alone parks it at the end — so edit, then
// restore the previous position clamped into the new content.
function setEditorContent(editor: MonacoEditorLike, value: string) {
    if (editor.getValue() === value) return;
    const model = editor.getModel();
    if (!model || !editor.executeEdits) {
        editor.setValue(value);
        return;
    }
    const prevPosition = editor.getPosition?.() ?? null;
    editor.pushUndoStop?.();
    editor.executeEdits("curio.external-content", [
        { range: model.getFullModelRange(), text: value, forceMoveMarkers: true },
    ]);
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
 *   (collaboration's applied proposals).
 *
 * `baselineRef` tracks the as-loaded / last-externally-applied content, the
 * same baseline the collaboration blur-diff proposals compare against.
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
