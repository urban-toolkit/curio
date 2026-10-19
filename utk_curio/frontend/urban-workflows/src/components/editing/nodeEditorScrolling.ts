// How a node's code or spec editor scrolls, on the canvas, in a notebook cell
// and on a dashboard tile alike: as a Jupyter cell does. The code is never
// wrapped and no line break is added to it, so a long line scrolls sideways.
// Whenever the code runs past one of the editor's sides, that side's bar shows
// at rest, and an editor whose code fits shows none. The bar is the thin
// scrollbar of Curio's panels (styles/scrollbars.module.css), whose class the
// editor carries. CodeEditor and GrammarEditor both use this; how the editor
// looks otherwise is nodeEditorLook's.

import scrollbars from "../../styles/scrollbars.module.css";

/** The thin scrollbar's width in px: the `width` of its `::-webkit-scrollbar`
 *  rule. Monaco takes the size of its bars as a number; thinScrollbar.test.ts
 *  keeps the two equal. */
export const SCROLLBAR_PX = 6;

/** Monaco's options for a node's editor, spread over the editor's own. */
export const NODE_EDITOR_SCROLLING = {
    // Monaco's default, kept on purpose: a long line scrolls sideways.
    wordWrap: "off" as const,
    // Monaco draws its bars as elements of its own, not the browser's. On the
    // editor, the thin scrollbar's class gives Monaco's slider the bar's
    // colours and the thumb's shape.
    extraEditorClassName: scrollbars.thinScrollbar,
    scrollbar: {
        // A bar shows at rest whenever the code runs past its side, and not
        // when the code fits. Monaco's default, "auto", showed one only while
        // the pointer was over the editor or it scrolled, then faded it out.
        vertical: "visible" as const,
        horizontal: "visible" as const,
        verticalScrollbarSize: SCROLLBAR_PX,
        horizontalScrollbarSize: SCROLLBAR_PX,
        verticalSliderSize: SCROLLBAR_PX,
        horizontalSliderSize: SCROLLBAR_PX,
        // A wheel the editor cannot use goes on to the page, so the notebook
        // view scrolls past the editor's ends. On the canvas the wrapper's
        // `nowheel` keeps it from zooming, as before. Monaco reads this option
        // only when the editor is created, so it is not tied to the view.
        alwaysConsumeMouseWheel: false,
    },
};
