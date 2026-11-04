/**
 * What an agent changed in a node, marked for a moment as it lands, in the
 * agent's tint: the lines of its code or spec (decorations of the node's code
 * editor, `useYMonacoBinding`) and the rows of its widgets (`NodeEditor`).
 *
 * A mark is the editor's alone: a decoration with a class and no hover, which
 * never reaches the editor's text, so y-monaco never sends it to the doc. The
 * class is `AGENT_MARK_CLASS` with the tint's (`NodeEditor.css`).
 */
import type { AgentPaletteKey } from "../menus/nodes/agentsPalette/agentCategoryStyle";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

/** How long an agent's change stays marked after it lands. */
export const AGENT_MARK_MS = 1500;

/** The class every mark has; `--<tint>` beside it gives its color. */
export const AGENT_MARK_CLASS = "curio-agent-change";

/** The classes of a mark in *tint*. */
export function agentMarkClass(tint: AgentPaletteKey): string {
    return `${AGENT_MARK_CLASS} ${AGENT_MARK_CLASS}--${tint}`;
}

/** Lines `start` to `end` of a text, counted from 1, both included. */
export interface LineSpan {
    start: number;
    end: number;
}

/** Past this many line pairs, the lines between the two texts' common start
 *  and end are all marked, with no finer comparison. */
const LINE_PAIRS_COMPARED = 250_000;

/** Which lines of *after* are kept from *before*, in order: a longest common
 *  subsequence of the two. */
function keptLines(before: string[], after: string[]): boolean[] {
    const kept = after.map(() => false);
    if (before.length === 0 || after.length * before.length > LINE_PAIRS_COMPARED) return kept;
    const width = after.length + 1;
    const longest = new Uint32Array((before.length + 1) * width);
    for (let i = before.length - 1; i >= 0; i -= 1) {
        for (let j = after.length - 1; j >= 0; j -= 1) {
            longest[i * width + j] = before[i] === after[j]
                ? longest[(i + 1) * width + j + 1] + 1
                : Math.max(longest[(i + 1) * width + j], longest[i * width + j + 1]);
        }
    }
    let i = 0;
    let j = 0;
    while (i < before.length && j < after.length) {
        if (before[i] === after[j]) {
            kept[j] = true;
            i += 1;
            j += 1;
        } else if (longest[(i + 1) * width + j] >= longest[i * width + j + 1]) {
            i += 1;
        } else {
            j += 1;
        }
    }
    return kept;
}

/**
 * The lines of *after* that a change from *before* wrote: each line it added
 * or rewrote, and, where it only removed lines, the line where they were.
 */
export function changedLinesBetween(before: string, after: string): LineSpan[] {
    if (before === after) return [];
    const old = before.split("\n");
    const now = after.split("\n");
    let head = 0;
    while (head < old.length && head < now.length && old[head] === now[head]) head += 1;
    let oldEnd = old.length;
    let nowEnd = now.length;
    while (oldEnd > head && nowEnd > head && old[oldEnd - 1] === now[nowEnd - 1]) {
        oldEnd -= 1;
        nowEnd -= 1;
    }
    const kept = keptLines(old.slice(head, oldEnd), now.slice(head, nowEnd));
    const spans: LineSpan[] = [];
    kept.forEach((isKept, k) => {
        if (isKept) return;
        const line = head + k + 1;
        const last = spans[spans.length - 1];
        if (last && last.end === line - 1) last.end = line;
        else spans.push({ start: line, end: line });
    });
    if (spans.length > 0) return spans;
    const line = Math.min(head + 1, now.length);
    return [{ start: line, end: line }];
}

/** Each editor's marks, and when they go. */
const marksOf = new WeakMap<object, { collection: any; timer: ReturnType<typeof setTimeout> | null }>();

/** Drop *editor*'s marks now. */
export function dropLineMarks(editor: any): void {
    const marks = editor ? marksOf.get(editor) : undefined;
    if (!marks) return;
    if (marks.timer !== null) clearTimeout(marks.timer);
    marks.timer = null;
    try {
        marks.collection.clear();
    } catch {
        /* the editor is gone, and its decorations with it */
    }
}

/** Mark *lines* in *editor*, in *tint*, for `AGENT_MARK_MS`. A later change
 *  marks its own lines in their place. */
export function markChangedLines(editor: any, lines: ReadonlyArray<LineSpan>, tint: AgentPaletteKey): void {
    if (!editor || lines.length === 0) return;
    let marks = marksOf.get(editor);
    if (!marks) {
        const collection = editor.createDecorationsCollection?.([]);
        if (!collection) return;
        marks = { collection, timer: null };
        marksOf.set(editor, marks);
    }
    const className = agentMarkClass(tint);
    marks.collection.set(lines.map(({ start, end }) => ({
        range: { startLineNumber: start, startColumn: 1, endLineNumber: end, endColumn: 1 },
        options: { isWholeLine: true, className },
    })));
    if (marks.timer !== null) clearTimeout(marks.timer);
    marks.timer = setTimeout(() => dropLineMarks(editor), AGENT_MARK_MS);
}

/** The widgets an agent changed, by name, marked in its tint. */
export interface WidgetMarks {
    names: ReadonlySet<string>;
    tint: AgentPaletteKey;
}

/** The names of the widgets of *after* that *before* did not hold as they
 *  are: a value or a definition changed, or a widget added. */
export function changedWidgets(before: ReadonlyArray<WidgetDef>, after: ReadonlyArray<WidgetDef>): Set<string> {
    const was = new Map(before.map((widget) => [widget.name, JSON.stringify(widget)]));
    return new Set(after.filter((widget) => was.get(widget.name) !== JSON.stringify(widget)).map((widget) => widget.name));
}
