/**
 * How a widget reference looks and edits in a Monaco editor (#662): as one
 * chip with the widget's name, like the widget's tag.
 *
 * The code keeps `[!! name !!]`. Its brackets stay in the text but are not
 * drawn, so the chip is a rounded box around the name. The caret steps over a
 * reference in one move, and Backspace after it or Delete before it removes
 * the whole reference. A reference with a problem (an unknown name, an old
 * marker) is drawn whole, in a red box, so what is wrong can be read and fixed.
 *
 * Every decoration says it affects letter spacing. That takes the line off
 * Monaco's fixed-width fast path, so the caret and selections are placed from
 * the drawn text, where the brackets take no room and the chip has padding.
 *
 * Pure: marks in, decorations, positions and ranges out.
 * `monacoCodeReferences.ts` applies them to a mounted editor.
 */

export interface ChipRange {
  startLineNumber: number;
  startColumn: number;
  endLineNumber: number;
  endColumn: number;
}

export interface ChipMark {
  /** The whole `[!! ... !!]`. */
  range: ChipRange;
  /** The name between the brackets, when the reference sits on one line. */
  nameRange: ChipRange | null;
  problem: string | null;
  hover: string;
  /** A class naming the reference's kind, drawn on the box beside its own
   * (an input chip's `curio-input-ref`, which turns the box green). */
  kindClass?: string | null;
}

/** One reference drawn as a chip: on one line, from *startColumn* to *endColumn*. */
export interface ChipSpan {
  lineNumber: number;
  startColumn: number;
  endColumn: number;
}

export const CHIP_CLASS = "curio-widget-ref";
export const CHIP_PROBLEM_CLASS = "curio-widget-ref-problem";
export const CHIP_HIDDEN_CLASS = "curio-widget-ref-hidden";
export const CHIP_FIRST_CLASS = "curio-widget-ref-first";
export const CHIP_LAST_CLASS = "curio-widget-ref-last";

/** Whether *mark* is drawn as a name-only chip. */
const isChip = (mark: ChipMark): boolean =>
  mark.problem === null &&
  mark.nameRange !== null &&
  mark.range.startLineNumber === mark.range.endLineNumber &&
  mark.nameRange.endColumn > mark.nameRange.startColumn;

const onLine = (lineNumber: number, startColumn: number, endColumn: number): ChipRange => ({
  startLineNumber: lineNumber,
  startColumn,
  endLineNumber: lineNumber,
  endColumn,
});

const inline = (className: string, hover?: string) => ({
  inlineClassName: className,
  inlineClassNameAffectsLetterSpacing: true,
  ...(hover !== undefined ? { hoverMessage: { value: hover } } : {}),
});

/**
 * The decorations that draw *marks*. A box is one class over its text plus a
 * class on its first and last character, so it reads as one box however many
 * spans Monaco splits the text into.
 */
export function chipDecorations(marks: ChipMark[]): { range: ChipRange; options: Record<string, unknown> }[] {
  const out: { range: ChipRange; options: Record<string, unknown> }[] = [];
  for (const mark of marks) {
    const box = isChip(mark) ? (mark.nameRange as ChipRange) : mark.range;
    const base = mark.problem === null ? CHIP_CLASS : CHIP_PROBLEM_CLASS;
    const kind = mark.kindClass ? `${base} ${mark.kindClass}` : base;
    if (isChip(mark)) {
      const line = mark.range.startLineNumber;
      out.push({ range: onLine(line, mark.range.startColumn, box.startColumn), options: inline(CHIP_HIDDEN_CLASS) });
      out.push({ range: onLine(line, box.endColumn, mark.range.endColumn), options: inline(CHIP_HIDDEN_CLASS) });
    }
    out.push({ range: box, options: inline(kind, mark.hover) });
    out.push({
      range: onLine(box.startLineNumber, box.startColumn, box.startColumn + 1),
      options: inline(CHIP_FIRST_CLASS),
    });
    out.push({
      range: onLine(box.endLineNumber, box.endColumn - 1, box.endColumn),
      options: inline(CHIP_LAST_CLASS),
    });
  }
  return out;
}

/** The references the caret steps over and Backspace removes whole. */
export function chipSpans(marks: ChipMark[]): ChipSpan[] {
  return marks.filter(isChip).map((m) => ({
    lineNumber: m.range.startLineNumber,
    startColumn: m.range.startColumn,
    endColumn: m.range.endColumn,
  }));
}

type Position = { lineNumber: number; column: number };

/**
 * Where the caret goes when it lands at *position*, inside a chip, or null
 * when it may stay. Coming from a chip's edge, it crosses to the other edge,
 * so one arrow key steps over the chip; from anywhere else (a click, a line
 * above), it goes to the nearer edge.
 */
export function snapPosition(spans: ChipSpan[], position: Position, previous: Position | null): Position | null {
  const span = spans.find(
    (s) => s.lineNumber === position.lineNumber && position.column > s.startColumn && position.column < s.endColumn,
  );
  if (!span) return null;
  const start = { lineNumber: span.lineNumber, column: span.startColumn };
  const end = { lineNumber: span.lineNumber, column: span.endColumn };
  if (previous && previous.lineNumber === span.lineNumber) {
    if (previous.column <= span.startColumn) return end;
    if (previous.column >= span.endColumn) return start;
  }
  return position.column - span.startColumn <= span.endColumn - position.column ? start : end;
}

/** The chip a Backspace or Delete at *position* removes whole, or null. */
export function chipToDelete(spans: ChipSpan[], position: Position, key: "Backspace" | "Delete"): ChipSpan | null {
  return (
    spans.find(
      (s) =>
        s.lineNumber === position.lineNumber &&
        (key === "Backspace" ? s.endColumn === position.column : s.startColumn === position.column),
    ) ?? null
  );
}
