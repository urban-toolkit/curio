/**
 * An editor's hovers in the one Curio tooltip (components/tooltip).
 *
 * Monaco draws its own hover inside the node, so the canvas's zoom scales it
 * and the card clips it; and its option to draw it outside places it wrong
 * under a zoom, adding unscaled offsets. So both editors turn it off
 * (`hover: { enabled: false }`), and this hook shows what Monaco showed, in
 * the Curio tooltip, placed from the hovered span's box on screen:
 *
 * - the messages of the markers at that place (the credential warning, a
 *   JSON error), first, as Monaco put them;
 * - a chip's text, what `referenceMarks` says it stands for;
 * - in a JavaScript node, the type information TypeScript's worker gives for
 *   the word under the pointer, read when the tooltip is about to show.
 *
 * Monaco corrects its mouse positions for the canvas's zoom itself. Monaco's
 * own chord for its hover, Cmd/Ctrl+K Cmd/Ctrl+I, shows the same for what is
 * at the caret, in the editor that has the focus: an action of that editor,
 * as Run this node is (runNodeMonacoAction.ts), which outranks Monaco's own.
 * It does nothing until the editor has mounted.
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

/** The action Cmd/Ctrl+K Cmd/Ctrl+I runs: the Curio tooltip for what is at the caret. */
export const SHOW_TOOLTIP_ACTION_ID = "curio.showTooltip";
export const SHOW_TOOLTIP_ACTION_LABEL = "Show the tooltip at the caret";

/** The lines that are not blank, joined one per line. */
const joined = (lines: Array<string | null | undefined>) =>
  lines.filter((line): line is string => typeof line === "string" && line.trim() !== "").join("\n");

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

    /** What the editor says at *position*: the markers' messages and a chip's text. */
    const describe = (position: Position) => {
      const code: string = model()?.getValue?.() ?? "";
      const chip = referenceMarks(code, scope, language).find((mark) => within(mark.range, position)) ?? null;
      const markers: Marker[] = (
        (monaco?.editor?.getModelMarkers?.({ resource: model()?.uri }) ?? []) as Marker[]
      ).filter((marker) => within(marker, position));
      return { chip, markers };
    };

    /** TypeScript's type information at *position*, as Monaco's hover showed it, or null. */
    const typeInformation = async (position: Position): Promise<string | null> => {
      const typescript = monaco?.typescript ?? monaco?.languages?.typescript;
      const m = model();
      if (typeof typescript?.getJavaScriptWorker !== "function" || !m) return null;
      const getWorker = await typescript.getJavaScriptWorker();
      const worker = await getWorker(m.uri);
      const info = await worker?.getQuickInfoAtPosition?.(m.uri.toString(), m.getOffsetAt(position));
      if (!info) return null;
      const join = (parts: { text: string }[] | undefined) => (parts ?? []).map((part) => part.text).join("");
      const text = [join(info.displayParts), join(info.documentation)].filter((part) => part.trim() !== "").join("\n\n");
      return text || null;
    };

    /** What shows for *position*, under the key it shows by, or null for nothing. */
    const contentAt = (position: Position): { key: string; content: TooltipContent | (() => Promise<TooltipContent | null>) } | null => {
      const { chip, markers } = describe(position);
      const messages = markers.map((marker) => marker.message);
      // A chip is Curio's own: what it stands for, with no type information.
      if (chip) {
        const text = joined([...messages, chip.hover]);
        return text
          ? { key: `${id}:chip:${chip.range.startLineNumber}:${chip.range.startColumn}`, content: { kind: "text", text } }
          : null;
      }
      const word = language === "javascript" ? model()?.getWordAtPosition?.(position) : null;
      if (word) {
        // The markers' messages first, then the type information, as Monaco's hover put them.
        return {
          key: `${id}:word:${position.lineNumber}:${word.startColumn}`,
          content: async () => {
            const text = joined([...messages, await typeInformation(position)]);
            return text ? { kind: "text", text } : null;
          },
        };
      }
      const text = joined(messages);
      return text
        ? { key: `${id}:marker:${markers[0].startLineNumber}:${markers[0].startColumn}`, content: { kind: "text", text } }
        : null;
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
        anchorElement: element ?? editor.getDomNode?.() ?? null,
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

    // Monaco's own chord for its hover shows the Curio tooltip for the caret,
    // in this editor only: an action of the editor runs where it has the focus.
    const keyMod = monaco?.KeyMod;
    const keyCode = monaco?.KeyCode;
    const action =
      typeof keyMod?.chord === "function" && typeof keyCode?.KeyK === "number" && typeof editor.addAction === "function"
        ? editor.addAction({
            id: SHOW_TOOLTIP_ACTION_ID,
            label: SHOW_TOOLTIP_ACTION_LABEL,
            keybindings: [keyMod.chord(keyMod.CtrlCmd | keyCode.KeyK, keyMod.CtrlCmd | keyCode.KeyI)],
            run: () => {
              const position: Position | null = editor.getPosition?.() ?? null;
              const found = position ? contentAt(position) : null;
              if (!position || !found) return;
              atCaret = `${found.key}:caret`;
              tooltipStore.show(
                {
                  key: atCaret,
                  target: null,
                  anchor: () => caretBox(position),
                  anchorElement: editor.getDomNode?.() ?? null,
                  side: "top",
                  pointer: null,
                  content: found.content,
                },
                "focus",
              );
            },
          })
        : null;

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
      for (const subscription of [move, leave, down, scroll, edit, caret, action]) subscription?.dispose?.();
      letGo();
      hideOurs();
    };
  }, [editor, monaco, scope, language]);
}

export default useEditorTooltip;
