// In a notebook cell an editor is as tall as its lines, as a Jupyter cell is,
// so short code leaves no empty box and long code does not push the output off
// the page: at least three lines, at most a cap, past which it scrolls inside.
// On the canvas the editor still fills its node. CodeEditor and GrammarEditor
// both use this.
import { useCallback, useEffect, useRef, useState } from "react";
import type CSS from "csstype";
import { useNotebookViewContext } from "../../providers/flow/notebookViewContext";

export const NOTEBOOK_CODE_EDITOR_MAX = 400;
export const NOTEBOOK_SPEC_EDITOR_MAX = 240;
const MIN_LINES = 3;
/** Monaco's line height at the editors' 13px, until the editor says. */
const DEFAULT_LINE_HEIGHT = 19;

/** The editor's height in a cell: its content's, at least three lines, at most *max*. */
export function clampNotebookEditorHeight(contentHeight: number, lineHeight: number, max: number): number {
    return Math.round(Math.min(max, Math.max(MIN_LINES * lineHeight, contentHeight)));
}

interface ContentSizedEditor {
    getContentHeight(): number;
    getOption?(option: unknown): unknown;
    onDidContentSizeChange(listener: (e: { contentHeight: number }) => void): { dispose(): void };
}

/**
 * `attach` goes in the editor's `onMount`; `wrapperStyle` on the element that
 * holds the editor. Monaco reports its content height whenever a line comes or
 * goes, and its automatic layout follows the wrapper's new size.
 */
export function useNotebookEditorHeight(max: number): {
    attach: (editor: ContentSizedEditor, monaco?: any) => void;
    wrapperStyle: CSS.Properties | undefined;
    /** The editor is in a notebook cell. */
    inCell: boolean;
} {
    const { on } = useNotebookViewContext();
    const [content, setContent] = useState<{ height: number; lineHeight: number }>({
        height: 0,
        lineHeight: DEFAULT_LINE_HEIGHT,
    });
    const subscriptionRef = useRef<{ dispose(): void } | null>(null);

    const attach = useCallback((editor: ContentSizedEditor, monaco?: any) => {
        // A stand-in editor (a test's) may not report its content size.
        if (typeof editor?.getContentHeight !== "function" || typeof editor.onDidContentSizeChange !== "function") return;
        let lineHeight = DEFAULT_LINE_HEIGHT;
        try {
            const option = monaco?.editor?.EditorOption?.lineHeight;
            const read = option !== undefined ? Number(editor.getOption?.(option)) : NaN;
            if (Number.isFinite(read) && read > 0) lineHeight = read;
        } catch {
            /* an editor without options keeps the default */
        }
        setContent({ height: editor.getContentHeight(), lineHeight });
        subscriptionRef.current?.dispose();
        subscriptionRef.current = editor.onDidContentSizeChange((e) => {
            setContent((prev) => (prev.height === e.contentHeight ? prev : { ...prev, height: e.contentHeight }));
        });
    }, []);

    useEffect(() => () => {
        subscriptionRef.current?.dispose();
        subscriptionRef.current = null;
    }, []);

    const wrapperStyle = on
        ? { height: `${clampNotebookEditorHeight(content.height, content.lineHeight, max)}px`, flex: "none" }
        : undefined;
    return { attach, wrapperStyle, inCell: on };
}
