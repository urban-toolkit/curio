/**
 * An editor's hovers in the one Curio tooltip (components/tooltip).
 *
 * Monaco draws its own hover inside the node, so the canvas's zoom scales it
 * and the card clips it; and its option to draw it outside places it wrong
 * under a zoom, adding unscaled offsets. So both editors turn it off
 * (`hover: { enabled: false }`), and this hook shows what Monaco showed, in
 * the Curio tooltip, placed from the hovered span's box on screen:
 *
 * - a chip's text, what `referenceMarks` says it stands for;
 * - the messages of the markers at that place (the credential warning, a
 *   JSON error);
 * - in a JavaScript node, the type information TypeScript's worker gives for
 *   the word under the pointer, read when the tooltip is about to show.
 *
 * Monaco corrects its mouse positions for the canvas's zoom itself. Monaco's
 * own chord for its hover, Cmd/Ctrl+K Cmd/Ctrl+I, shows the same for what is
 * at the caret. It does nothing until the editor has mounted.
 */
import { useEffect } from "react";
import { tooltipStore, type TooltipContent } from "../tooltip/tooltipStore";
import type { TooltipBox } from "../tooltip/tooltipPlacement";
import { referenceMarks } from "./widgets/monacoCodeReferences";
import type { CodeLanguage, ReferenceScope } from "../../utils/references/codeReferences";

/** Monaco's `editor.MouseTargetType.CONTENT_TEXT`: the pointer on text. */
const CONTENT_TEXT = 6;

type Position = { lineNumber: number; column: number };

interface Span {
  startLineNumber: number;
  startColumn: number;
  endLineNumber: number;
  endColumn: number;
}

/** A Monaco marker: a span of the code and what is wrong there. */
interface Marker extends Span {
  message: string;
}

/** Whether *position* falls in *span*, its ends included. */
function within(span: Span, position: Position): boolean {
  const after =
    position.lineNumber > span.startLineNumber ||
    (position.lineNumber === span.startLineNumber && position.column >= span.startColumn);
  const before =
    position.lineNumber < span.endLineNumber ||
    (position.lineNumber === span.endLineNumber && position.column <= span.endColumn);
  return after && before;
}

/** Each editor's tooltips are told apart by a number of its own. */
let editors = 0;

export function useEditorTooltip(
  editor: any,
  monaco: any,
  scope: ReferenceScope,
  language: CodeLanguage,
): void {
  useEffect(() => {
    if (!editor || typeof editor.onMouseMove !== "function") return undefined;
    const id = `editor-${(editors += 1)}`;
    /** What this editor's tooltip, open or about to open, describes. */
    let current: string | null = null;
    /** The tooltip the chord opened, which goes when the caret moves. */
    let atCaret: string | null = null;
    const model = () => editor.getModel?.();

    const letGo = () => {
      if (current) tooltipStore.leave(current);
      current = null;
    };

    /** What the editor says at *position*: a chip's text and the markers' messages. */
    const describe = (position: Position) => {
      const code: string = model()?.getValue?.() ?? "";
      const chip = referenceMarks(code, scope, language).find((mark) => within(mark.range, position)) ?? null;
      const markers: Marker[] = (
        (monaco?.editor?.getModelMarkers?.({ resource: model()?.uri }) ?? []) as Marker[]
      ).filter((marker) => within(marker, position));
      const lines = [chip?.hover, ...markers.map((marker) => marker.message)].filter(
        (line): line is string => typeof line === "string" && line.trim() !== "",
      );
      const key = chip
        ? `${id}:chip:${chip.range.startLineNumber}:${chip.range.startColumn}`
        : markers.length > 0
          ? `${id}:marker:${markers[0].startLineNumber}:${markers[0].startColumn}`
          : null;
      return { key, lines };
    };

    /** TypeScript's type information at *position*, as Monaco's hover showed it. */
    const typeInformation = async (position: Position): Promise<TooltipContent | null> => {
      const typescript = monaco?.typescript ?? monaco?.languages?.typescript;
      const m = model();
      if (typeof typescript?.getJavaScriptWorker !== "function" || !m) return null;
      const getWorker = await typescript.getJavaScriptWorker();
      const worker = await getWorker(m.uri);
      const info = await worker?.getQuickInfoAtPosition?.(m.uri.toString(), m.getOffsetAt(position));
      if (!info) return null;
      const join = (parts: { text: string }[] | undefined) => (parts ?? []).map((part) => part.text).join("");
      const text = [join(info.displayParts), join(info.documentation)].filter((part) => part.trim() !== "").join("\n\n");
      return text ? { kind: "text", text } : null;
    };

    /** What shows for *position*, under the key it shows by, or null for nothing. */
    const contentAt = (position: Position): { key: string; content: TooltipContent | (() => Promise<TooltipContent | null>) } | null => {
      const { key, lines } = describe(position);
      if (key && lines.length > 0) return { key, content: { kind: "text", text: lines.join("\n") } };
      if (language !== "javascript") return null;
      const word = model()?.getWordAtPosition?.(position);
      if (!word) return null;
      return { key: `${id}:word:${position.lineNumber}:${word.startColumn}`, content: () => typeInformation(position) };
    };

    const contentText = monaco?.editor?.MouseTargetType?.CONTENT_TEXT ?? CONTENT_TEXT;
    const move = editor.onMouseMove((event: any) => {
      const target = event?.target;
      const position: Position | null = target?.position ?? null;
      if (!position || target.type !== contentText) {
        letGo();
        return;
      }
      const found = contentAt(position);
      if (!found) {
        letGo();
        return;
      }
      const element: Element | null = target.element ?? null;
      current = found.key;
      tooltipStore.rest({
        key: found.key,
        target: null,
        anchor: () => (element && element.isConnected ? element.getBoundingClientRect() : null),
        side: "top",
        pointer: null,
        content: found.content,
      });
    });

    /** The caret's box on screen: Monaco's place for it, scaled as the canvas shows the editor. */
    const caretBox = (position: Position): TooltipBox | null => {
      const dom: HTMLElement | null = editor.getDomNode?.() ?? null;
      const at = editor.getScrolledVisiblePosition?.(position);
      if (!dom || !at || typeof at.left !== "number") return null;
      const box = dom.getBoundingClientRect();
      const scale = dom.offsetWidth > 0 ? box.width / dom.offsetWidth : 1;
      return { left: box.left + at.left * scale, top: box.top + at.top * scale, width: 0, height: at.height * scale };
    };

    // Monaco's own chord for its hover shows the Curio tooltip for the caret.
    const keyMod = monaco?.KeyMod;
    const keyCode = monaco?.KeyCode;
    if (keyMod && keyCode && typeof editor.addCommand === "function") {
      editor.addCommand(keyMod.chord(keyMod.CtrlCmd | keyCode.KeyK, keyMod.CtrlCmd | keyCode.KeyI), () => {
        const position: Position | null = editor.getPosition?.() ?? null;
        const found = position ? contentAt(position) : null;
        if (!position || !found) return;
        atCaret = `${found.key}:caret`;
        tooltipStore.show(
          { key: atCaret, target: null, anchor: () => caretBox(position), side: "top", pointer: null, content: found.content },
          "focus",
        );
      });
    }

    const hideOurs = () => {
      const shown = tooltipStore.getState().shown?.request.key;
      if (typeof shown === "string" && shown.startsWith(`${id}:`)) tooltipStore.hide();
    };
    const leave = editor.onMouseLeave?.(() => letGo());
    // A press, a scroll or an edit leaves nothing where the tooltip points.
    const down = editor.onMouseDown?.(() => tooltipStore.hide());
    const scroll = editor.onDidScrollChange?.(() => hideOurs());
    const edit = editor.onDidChangeModelContent?.(() => hideOurs());
    const caret = editor.onDidChangeCursorPosition?.(() => {
      if (atCaret && tooltipStore.getState().shown?.request.key === atCaret) tooltipStore.hide();
      atCaret = null;
    });

    return () => {
      for (const subscription of [move, leave, down, scroll, edit, caret]) subscription?.dispose?.();
      letGo();
      hideOurs();
    };
  }, [editor, monaco, scope, language]);
}

export default useEditorTooltip;
