/**
 * References inside a Monaco editor (#662): inserting one where a tag is
 * dropped or clicked, drawing each one as a chip whose hover says what it
 * stands for, and, in a JSON editor, hiding the syntax errors a reference
 * causes (`[!! name !!]` is not JSON until it is resolved).
 *
 * Widget tags and input tags drag with their own types, so each can be told
 * apart, and both insert their reference the same way.
 *
 * The pure helpers are what the tests exercise; `useCodeReferences` wires
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
import { effectiveValue, type WidgetDef, type WidgetValue } from "../../../utils/widgets/widgetModel";
import { anyFromABox } from "../../../utils/scenarios/scenarioColors";
import {
  findReferences,
  inputName,
  parseReference,
  referenceContexts,
  referenceProblem,
  referenceText,
  resolveReferences,
  stackedFields,
  widgetLiteral,
  type CodeLanguage,
  type ReferenceScope,
} from "../../../utils/references/codeReferences";

/** What a dragged widget tag carries: the widget's name. Its text/plain twin is
 * the reference itself, so a drop anywhere that takes text gets the reference. */
export const WIDGET_REF_MIME = "application/x-curio-widget";
/** What a dragged input or column tag carries: what stands inside its
 * reference, such as `input_1` or `input_1.height`. */
export const INPUT_REF_MIME = "application/x-curio-input";
/** What a dragged selection tag carries: what stands inside its reference,
 * such as `selection picked`. */
export const SELECTION_REF_MIME = "application/x-curio-selection";
/** What a dragged scenario tag under Scenarios carries (the swatches, text
 * colors, order, an input's tag): what stands inside its chip, such as
 * `scenario colors`. */
export const SCENARIO_REF_MIME = "application/x-curio-scenario";

const REFERENCE_MIMES = [WIDGET_REF_MIME, INPUT_REF_MIME, SELECTION_REF_MIME, SCENARIO_REF_MIME];

/** The most ids a selection chip's hover lists. */
const HOVER_IDS = 5;

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
  /** What stands inside the reference. */
  name: string;
  kind: "widget" | "input" | "selection" | "scenario" | "dataset" | "stacked";
}

/** *names* as a list in words: `a`, `a and b`, `a, b and c`. */
export function inWords(names: string[]): string {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
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

/** What a reference's chip says when nothing is wrong with it. */
function hoverFor(inner: string, scope: ReferenceScope, language: CodeLanguage): string {
  const parsed = parseReference(inner);
  if (parsed.kind === "widget") {
    const widget = scope.widgets.find((w) => w.name === inner) as WidgetDef;
    return `${inner} = ${widgetLiteral(effectiveValue(widget), language)}`;
  }
  if (parsed.kind === "selection") {
    const tag = (scope.selections ?? []).find((t) => t.name === parsed.name);
    const ids = tag?.ids ?? [];
    const shown = widgetLiteral(ids.slice(0, HOVER_IDS) as WidgetValue, language);
    const listed = ids.length > HOVER_IDS ? `${shown.slice(0, -1)}, ...]` : shown;
    return `${inner} = ${listed}, ${ids.length} ${tag?.column} values selected in its view`;
  }
  if (parsed.kind === "dataset") {
    const circles = [...scope.inputs].sort((a, b) => a.slot - b.slot).map((input) => inputName(input.slot));
    return `the dataset inputs: the rows of ${inWords(circles)}, stacked in circle order`;
  }
  if (parsed.kind === "stacked") {
    const dtype = stackedFields(scope.inputs).dtypes[parsed.column];
    return `field ${parsed.column} of inputs, every input's rows stacked` + (dtype ? ` (${dtype})` : "");
  }
  if (parsed.kind === "scenario") {
    // What the chip writes, as a run writes it.
    const value = resolveReferences(referenceText(inner), scope, "json").code;
    // A node fed from no box has no Scenarios in its header; its chips still
    // write the inputs' nodes' names, which the grammar's palette colors.
    if (!anyFromABox(scope.inputs.flatMap((input) => (input.scenario ? [input.scenario] : [])))) {
      const writes =
        parsed.chip === "input"
          ? `the gray the scale gives input_${parsed.slot}`
          : parsed.chip === "order"
            ? "the names of the nodes its inputs come from"
            : "the names alone, in the grammar's own colors";
      return `${inner} = ${value}: no input of this node comes from a scenario box, so it writes ${writes}`;
    }
    if (parsed.chip !== "input") return `${inner} = ${value}, from the boxes this node's inputs come from`;
    const label = scope.inputs.find((i) => i.slot === parsed.slot)?.scenario;
    return label?.scenario != null
      ? `${inner} = ${value}, the color of ${label.name}, the box input_${parsed.slot} comes from`
      : `${inner} = ${value}: input_${parsed.slot} comes from no scenario box`;
  }
  const input = scope.inputs.find((i) => i.slot === parsed.slot);
  const from = input?.label ? `, from ${input.label}` : "";
  if (parsed.layer !== undefined) {
    const layer = input?.layers?.find((l) => l.name === parsed.layer);
    if (parsed.column === undefined) return `layer ${parsed.layer} of input_${parsed.slot}${from}`;
    const dtype = layer?.dtypes?.[parsed.column];
    return `column ${parsed.column} of layer ${parsed.layer}, input_${parsed.slot}${from}` + (dtype ? ` (${dtype})` : "");
  }
  if (parsed.column !== undefined) {
    const dtype = input?.dtypes?.[parsed.column];
    return `column ${parsed.column} of input_${parsed.slot}${from}` + (dtype ? ` (${dtype})` : "");
  }
  return `input_${parsed.slot}${from}` + (input?.dataType ? ` (${input.dataType})` : "");
}

/** Every reference in *code*, where it and its name are, and what its chip says. */
export function referenceMarks(code: string, scope: ReferenceScope, language: CodeLanguage): ReferenceMark[] {
  const refs = findReferences(code);
  const contexts = referenceContexts(code, refs, language);
  return refs.map((ref, index) => {
    const start = offsetToPosition(code, ref.start);
    const end = offsetToPosition(code, ref.end);
    const written = code.slice(ref.start, ref.end);
    const problem = referenceProblem(written, ref.inner, scope, contexts[index], language);
    // The name starts after "[!!" and the spaces that follow it.
    let nameStart = ref.start + 3;
    while (nameStart < ref.end && /\s/.test(code[nameStart])) nameStart += 1;
    const nameStartPos = offsetToPosition(code, nameStart);
    const nameEndPos = offsetToPosition(code, nameStart + ref.inner.length);
    const kind = parseReference(ref.inner).kind;
    return {
      range: toRange(start, end),
      nameRange:
        start.lineNumber === end.lineNumber && ref.inner.length > 0 ? toRange(nameStartPos, nameEndPos) : null,
      name: ref.inner,
      kind,
      problem,
      hover: problem ?? hoverFor(ref.inner, scope, language),
      // An input or column chip is drawn like a widget's, in green, and so are
      // the dataset inputs and its fields; a selection in peach; a scenario
      // chip in lilac.
      kindClass: kind === "widget" ? null : chipClass({ kind, problem }),
    };
  });
}

const KIND_CLASSES: Record<ReferenceMark["kind"], string> = {
  widget: "curio-widget-ref",
  input: "curio-input-ref",
  selection: "curio-selection-ref",
  scenario: "curio-scenario-ref",
  dataset: "curio-input-ref",
  stacked: "curio-input-ref",
};

/** The class that names *mark*'s kind: widget chips keep the classes #670 gave
 * them, and input chips carry theirs beside the box's (`referenceChips.ts`). */
export function chipClass(mark: Pick<ReferenceMark, "kind" | "problem">): string {
  const base = KIND_CLASSES[mark.kind];
  return mark.problem ? `${base}-problem` : base;
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

/** Whether *offset* in the JSON *text* falls inside a string. */
export function insideJsonString(text: string, offset: number): boolean {
  let inside = false;
  for (let i = 0; i < offset && i < text.length; i += 1) {
    if (inside && text[i] === "\\") {
      i += 1;
      continue;
    }
    if (text[i] === '"') inside = !inside;
  }
  return inside;
}

/**
 * Whether the chip *inner* writes one text a spec reads as a string: an
 * input's scenario color (`scenario input_1`), the dataset inputs (`inputs`)
 * or a field of it (`inputs.sunlight`). Inserted where JSON wants a value,
 * outside any string, it goes in quoted, so the spec stays JSON before its
 * chips are resolved: what a saved spec holds, and what a reader of its shape
 * parses (utils/autkSpecKind). A scale, a list of names or a widget's value is
 * no text, and goes in as it is.
 */
function writesOneText(inner: string): boolean {
  const parsed = parseReference(inner);
  return (parsed.kind === "scenario" && parsed.chip === "input") || parsed.kind === "dataset" || parsed.kind === "stacked";
}

/** Insert a reference to *inner* at *position*, or at the cursor. */
export function insertReference(
  editor: any,
  inner: string,
  position?: { lineNumber: number; column: number } | null,
): boolean {
  const pos = position ?? editor?.getPosition?.();
  if (!editor || !pos) return false;
  const model = editor.getModel?.();
  const text = model?.getValue?.();
  const offset = typeof text === "string" ? model?.getOffsetAt?.(pos) : undefined;
  const quoted = writesOneText(inner) && typeof offset === "number" && !insideJsonString(text, offset);
  editor.executeEdits("curio-widget-tag", [
    {
      range: {
        startLineNumber: pos.lineNumber,
        startColumn: pos.column,
        endLineNumber: pos.lineNumber,
        endColumn: pos.column,
      },
      text: quoted ? `"${referenceText(inner)}"` : referenceText(inner),
      forceMoveMarkers: true,
    },
  ]);
  editor.focus?.();
  return true;
}

/** What a drag carries for a reference, or null when it carries none. */
function draggedReference(event: { dataTransfer?: DataTransfer | null }): string | null {
  const types = Array.from(event.dataTransfer?.types ?? []);
  const mime = REFERENCE_MIMES.find((m) => types.includes(m));
  return mime ? event.dataTransfer?.getData(mime) || null : null;
}

/** Whether *event* drags a widget, input, column, selection or scenario tag. */
export function isReferenceDrag(event: { dataTransfer?: DataTransfer | null }): boolean {
  const types = Array.from(event.dataTransfer?.types ?? []);
  return REFERENCE_MIMES.some((m) => types.includes(m));
}

/** Insert the dragged tag's reference where *event* drops it. */
export function dropReference(editor: any, event: DragEvent): boolean {
  const inner = draggedReference(event);
  if (!inner) return false;
  const target = editor?.getTargetAtClientPoint?.(event.clientX, event.clientY);
  return insertReference(editor, inner, target?.position ?? null);
}

export function useCodeReferences(
  editor: any,
  monaco: any,
  scope: ReferenceScope,
  language: CodeLanguage,
  options: { hideJsonMarkers?: boolean } = {},
): void {
  const hideJsonMarkers = options.hideJsonMarkers === true;

  useEffect(() => {
    const collection = editor?.createDecorationsCollection?.([]);
    if (!collection) return;
    let spans: ChipSpan[] = [];
    const update = () => {
      const code = editor.getModel?.()?.getValue?.() ?? "";
      const marks = referenceMarks(code, scope, language);
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
  }, [editor, scope, language]);

  useEffect(() => {
    const node: HTMLElement | null = editor?.getDomNode?.() ?? null;
    if (!node) return;
    // Capture phase, so the drop is ours before Monaco's own text drop or the
    // canvas's drop handler sees it.
    const over = (event: DragEvent) => {
      if (!isReferenceDrag(event)) return;
      event.preventDefault();
      event.stopPropagation();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const drop = (event: DragEvent) => {
      if (!isReferenceDrag(event)) return;
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
      const refs = referenceMarks(model.getValue(), scope, language).map((m) => m.range);
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
  }, [editor, monaco, scope, language, hideJsonMarkers]);
}
