// How a node's code or spec editor looks, on the canvas and in a notebook cell
// alike: a plain gray input box, as a notebook's is (Node.css), with no line
// numbers, gutter, folding, line highlight or overview ruler. A dashboard tile
// keeps Monaco's own look. CodeEditor and GrammarEditor both use this; how tall
// the editor is in a cell is useNotebookEditorHeight's.

/** Monaco's options for a node's editor, spread over the editor's own. */
export const NODE_EDITOR_OPTIONS = {
    lineNumbers: "off" as const,
    glyphMargin: false,
    folding: false,
    lineDecorationsWidth: 10,
    lineNumbersMinChars: 0,
    renderLineHighlight: "none" as const,
    overviewRulerLanes: 0,
    overviewRulerBorder: false,
    hideCursorInOverviewRuler: true,
    padding: { top: 6, bottom: 6 },
};
const NO_OPTIONS: Partial<typeof NODE_EDITOR_OPTIONS> = {};

export function nodeEditorLook(dashboardOn: boolean): {
    /** The class of the element holding the editor: the gray box. */
    wrapperClassName: string | undefined;
    /** Monaco options to spread over the editor's own. */
    editorOptions: Partial<typeof NODE_EDITOR_OPTIONS>;
} {
    return dashboardOn
        ? { wrapperClassName: undefined, editorOptions: NO_OPTIONS }
        : { wrapperClassName: "curio-node-input", editorOptions: NODE_EDITOR_OPTIONS };
}
