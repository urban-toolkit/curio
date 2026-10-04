/**
 * Widget references inside a Monaco editor (#662): inserting one where a tag
 * is dropped or clicked, drawing each one as a chip whose hover shows the
 * value, and, in a JSON editor, hiding the syntax errors a reference causes
 * (`[!! name !!]` is not JSON until it is resolved).
 *
 * The pure helpers are what the tests exercise; `useWidgetReferences` wires
 * them to a mounted editor and does nothing until there is one.
 */
import { useEffect } from "react";
import "./widgetReferences.css";
import {
  chipDecorations,
  chipSpans,
  chipToDelete,
  snapPosition,
  type ChipMark,
  type ChipSpan,
} from "./referenceChips";
import { effectiveValue, type WidgetDef } from "../../../utils/widgets/widgetModel";
import {
  findWidgetReferences,
  referenceProblem,
  widgetLiteral,
  type WidgetLanguage,
} from "../../../utils/widgets/widgetSubstitution";

/** What a dragged tag carries: the widget's name. Its text/plain twin is the
 * reference itself, so a drop anywhere that takes text gets the reference. */
export const WIDGET_REF_MIME = "application/x-curio-widget";

export function referenceText(name: string): string {
  return `[!! ${name} !!]`;
}

export interface LineRange {
  startLineNumber: number;
  startColumn: number;
  endLineNumber: number;
  endColumn: number;
}

/** A code offset as Monaco's 1-based line and column. */
export function offsetToPosition(code: string, offset: number): { lineNumber: number; column: number } {
  let line = 1;
  let lastBreak = -1;
  for (let i = 0; i < offset && i < code.length; i += 1) {
    if (code.charCodeAt(i) === 10) {
      line += 1;
      lastBreak = i;
    }
  }
  return { lineNumber: line, column: offset - lastBreak };
}

export interface ReferenceMark extends ChipMark {
  name: string;
}

const toRange = (
  start: { lineNumber: number; column: number },
  end: { lineNumber: number; column: number },
): LineRange => ({
  startLineNumber: start.lineNumber,
  startColumn: start.column,
  endLineNumber: end.lineNumber,
  endColumn: end.column,
});

/** Every reference in *code*, where it and its name are, and what its chip says. */
export function referenceMarks(code: string, widgets: WidgetDef[], language: WidgetLanguage): ReferenceMark[] {
  return findWidgetReferences(code).map((ref) => {
    const start = offsetToPosition(code, ref.start);
    const end = offsetToPosition(code, ref.end);
    const written = code.slice(ref.start, ref.end);
    const problem = referenceProblem(written, ref.inner, widgets);
    const widget = widgets.find((w) => w.name === ref.inner);
    const hover =
      problem ?? `${ref.inner} = ${widgetLiteral(effectiveValue(widget as WidgetDef), language)}`;
    // The name starts after "[!!" and the spaces that follow it.
    let nameStart = ref.start + 3;
    while (nameStart < ref.end && /\s/.test(code[nameStart])) nameStart += 1;
    const nameStartPos = offsetToPosition(code, nameStart);
    const nameEndPos = offsetToPosition(code, nameStart + ref.inner.length);
    return {
      range: toRange(start, end),
      nameRange:
        start.lineNumber === end.lineNumber && ref.inner.length > 0 ? toRange(nameStartPos, nameEndPos) : null,
      name: ref.inner,
      problem,
      hover,
    };
  });
}

const before = (l1: number, c1: number, l2: number, c2: number) => l1 < l2 || (l1 === l2 && c1 < c2);

/** Whether *a* and *b* share a character, or *a* starts right where *b* ends. */
export function touchesRange(a: LineRange, b: LineRange): boolean {
  if (before(a.endLineNumber, a.endColumn, b.startLineNumber, b.startColumn)) return false;
  if (before(b.endLineNumber, b.endColumn, a.startLineNumber, a.startColumn)) return false;
  return true;
}

/** The markers no reference accounts for. */
export function markersOutsideReferences<M extends LineRange>(markers: M[], refs: LineRange[]): M[] {
  return markers.filter((m) => !refs.some((r) => touchesRange(m, r)));
}

/** Insert *name*'s reference at *position*, or at the cursor. */
export function insertReference(
  editor: any,
  name: string,
  position?: { lineNumber: number; column: number } | null,
): boolean {
  const pos = position ?? editor?.getPosition?.();
  if (!editor || !pos) return false;
  editor.executeEdits("curio-widget-tag", [
    {
      range: {
        startLineNumber: pos.lineNumber,
        startColumn: pos.column,
        endLineNumber: pos.lineNumber,
        endColumn: pos.column,
      },
      text: referenceText(name),
      forceMoveMarkers: true,
    },
  ]);
  editor.focus?.();
  return true;
}

/** Whether *event* drags a widget tag. */
export function isWidgetDrag(event: { dataTransfer?: DataTransfer | null }): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes(WIDGET_REF_MIME);
}

/** Insert the dragged tag's reference where *event* drops it. */
export function dropReference(editor: any, event: DragEvent): boolean {
  const name = event.dataTransfer?.getData(WIDGET_REF_MIME);
  if (!name) return false;
  const target = editor?.getTargetAtClientPoint?.(event.clientX, event.clientY);
  return insertReference(editor, name, target?.position ?? null);
}

export function useWidgetReferences(
  editor: any,
  monaco: any,
  widgets: WidgetDef[],
  language: WidgetLanguage,
  options: { hideJsonMarkers?: boolean } = {},
): void {
  const hideJsonMarkers = options.hideJsonMarkers === true;

  useEffect(() => {
    const collection = editor?.createDecorationsCollection?.([]);
    if (!collection) return;
    let spans: ChipSpan[] = [];
    const update = () => {
      const code = editor.getModel?.()?.getValue?.() ?? "";
      const marks = referenceMarks(code, widgets, language);
      collection.set(chipDecorations(marks));
      spans = chipSpans(marks);
    };
    update();
    const contentSub = editor.onDidChangeModelContent?.(update);

    // The caret never rests inside a chip: one arrow key steps over it.
    let previous: { lineNumber: number; column: number } | null = editor.getPosition?.() ?? null;
    const cursorSub = editor.onDidChangeCursorPosition?.((event: any) => {
      const snapped = snapPosition(spans, event.position, previous);
      previous = snapped ?? event.position;
      if (!snapped) return;
      const selection = editor.getSelection?.();
      if (selection && !selection.isEmpty?.()) {
        editor.setSelection({
          selectionStartLineNumber: selection.selectionStartLineNumber,
          selectionStartColumn: selection.selectionStartColumn,
          positionLineNumber: snapped.lineNumber,
          positionColumn: snapped.column,
        });
      } else {
        editor.setPosition(snapped);
      }
    });

    // Backspace after a chip, or Delete before it, removes the whole reference.
    const keySub = editor.onKeyDown?.((event: any) => {
      const key = event.browserEvent?.key;
      if (key !== "Backspace" && key !== "Delete") return;
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      const selection = editor.getSelection?.();
      const position = editor.getPosition?.();
      if (!position || (selection && !selection.isEmpty?.())) return;
      const chip = chipToDelete(spans, position, key);
      if (!chip) return;
      event.preventDefault?.();
      event.stopPropagation?.();
      editor.pushUndoStop?.();
      editor.executeEdits("curio-widget-ref", [
        {
          range: {
            startLineNumber: chip.lineNumber,
            startColumn: chip.startColumn,
            endLineNumber: chip.lineNumber,
            endColumn: chip.endColumn,
          },
          text: "",
        },
      ]);
      editor.pushUndoStop?.();
    });

    return () => {
      contentSub?.dispose?.();
      cursorSub?.dispose?.();
      keySub?.dispose?.();
      collection.clear?.();
    };
  }, [editor, widgets, language]);

  useEffect(() => {
    const node: HTMLElement | null = editor?.getDomNode?.() ?? null;
    if (!node) return;
    // Capture phase, so the drop is ours before Monaco's own text drop or the
    // canvas's drop handler sees it.
    const over = (event: DragEvent) => {
      if (!isWidgetDrag(event)) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const drop = (event: DragEvent) => {
      if (!isWidgetDrag(event)) return;
      event.preventDefault();
      event.stopPropagation();
      dropReference(editor, event);
    };
    node.addEventListener("dragover", over, true);
    node.addEventListener("drop", drop, true);
    return () => {
      node.removeEventListener("dragover", over, true);
      node.removeEventListener("drop", drop, true);
    };
  }, [editor]);

  useEffect(() => {
    if (!hideJsonMarkers || !editor || typeof monaco?.editor?.onDidChangeMarkers !== "function") return;
    const model = editor.getModel?.();
    if (!model) return;
    const filter = () => {
      const refs = referenceMarks(model.getValue(), widgets, language).map((m) => m.range);
      if (refs.length === 0) return;
      const markers = monaco.editor.getModelMarkers({ resource: model.uri, owner: "json" });
      const kept = markersOutsideReferences(markers, refs);
      if (kept.length !== markers.length) monaco.editor.setModelMarkers(model, "json", kept);
    };
    const sub = monaco.editor.onDidChangeMarkers((uris: any[]) => {
      if (uris.some((u) => String(u) === String(model.uri))) filter();
    });
    filter();
    return () => sub?.dispose?.();
  }, [editor, monaco, widgets, language, hideJsonMarkers]);
}
