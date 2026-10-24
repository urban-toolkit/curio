/**
 * An editor's hovers in the one Curio tooltip (components/tooltip).
 *
 * Monaco draws its own hover inside the node, so the canvas's zoom scales it
 * and the card clips it; and its option to draw it outside places it wrong
 * under a zoom, adding unscaled offsets. So both editors turn it off
 * (`hover: { enabled: false }`), and this hook shows what Monaco showed, in
 * the Curio tooltip:
 *
 * - the messages of the markers at that place (the credential warning, a
 *   JSON error), first, as Monaco put them;
 * - a chip's preview of what it holds (ChipPreviewTip), the same as its tag's
 *   in the header, when the node gives a preview source (*previews*); else
 *   what `referenceMarks` says the chip stands for;
 * - in a JavaScript node, the type information TypeScript's worker gives for
 *   the word under the pointer, read when the tooltip is about to show.
 *
 * A pointer that rests sends no new move, so what the editor does meanwhile
 * must not lose the tooltip. It is placed from where Monaco draws what it
 * describes (a chip's name, a word), read each time it is placed, else from
 * the hovered span's box: Monaco draws a line again, with a new span under
 * the pointer, when its decorations or tokens change. It hides when the text
 * scrolls, and not when Monaco reports a scroll that only changes the size it
 * can scroll (its lines measured again after it draws them).
 *
 * The scope, the language and the source are read as the pointer moves, so a
 * read coming back, which changes the scope, leaves an open tooltip open.
 *
 * Monaco corrects its mouse positions for the canvas's zoom itself. Monaco's
 * own chord for its hover, Cmd/Ctrl+K Cmd/Ctrl+I, shows the same for what is
 * at the caret, in the editor that has the focus: an action of that editor,
 * as Run this node is (runNodeMonacoAction.ts), which outranks Monaco's own.
 * It does nothing until the editor has mounted.
 */
import { createElement, useEffect, useRef } from "react";
import { tooltipStore, type TooltipContent } from "../tooltip/tooltipStore";
import type { TooltipBox } from "../tooltip/tooltipPlacement";
import { referenceMarks } from "./widgets/monacoCodeReferences";
import { ChipPreviewTip } from "./widgets/ChipPreview";
import type { ChipPreviewSource } from "./widgets/chipPreviewSource";
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

/** A part of one line, from one column up to another: what a tooltip describes. */
interface LinePart {
  lineNumber: number;
  startColumn: number;
  endColumn: number;
}

/** What shows for a place in the code: the key it shows by, what it says,
 * and the part of the line it describes when it is one (a chip's name, a word). */
interface Found {
  key: string;
  content: TooltipContent | (() => Promise<TooltipContent | null>);
  part: LinePart | null;
}

/** *range* as a part of one line, or null when it runs over several. */
function onOneLine(range: Span): LinePart | null {
  return range.startLineNumber === range.endLineNumber
    ? { lineNumber: range.startLineNumber, startColumn: range.startColumn, endColumn: range.endColumn }
    : null;
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
  previews?: ChipPreviewSource | null,
): void {
  const latest = useRef({ scope, language, previews });
  latest.current = { scope, language, previews };
  useEffect(() => {
    if (!editor || typeof editor.onMouseMove !== "function") return undefined;
    const id = `editor-${(editors += 1)}`;
    /** What this editor's tooltip, open or about to open, describes. */
    let current: string | null = null;
    /** The tooltip the chord opened, which goes when the caret moves. */
    let atCaret: string | null = null;
    /** The preview shown for a chip, kept while the pointer moves on that chip
     * so the open tooltip does not draw it again at each move. */
    let shownPreview: { key: string; signature: string; source: ChipPreviewSource; content: TooltipContent } | null = null;
    const model = () => editor.getModel?.();

    const letGo = () => {
      if (current) tooltipStore.leave(current);
      current = null;
    };

    /** What the editor says at *position*: the markers' messages and a chip's text. */
    const describe = (position: Position) => {
      const code: string = model()?.getValue?.() ?? "";
      const { scope, language } = latest.current;
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

    /** What shows for *position*, or null for nothing. */
    const contentAt = (position: Position): Found | null => {
      const { chip, markers } = describe(position);
      const messages = markers.map((marker) => marker.message);
      // A chip is Curio's own: what it holds, or what it stands for, with no
      // type information.
      if (chip) {
        const key = `${id}:chip:${chip.range.startLineNumber}:${chip.range.startColumn}`;
        // Its name, as the chip draws it, centered in the chip.
        const part = onOneLine(chip.nameRange ?? chip.range);
        const source = latest.current.previews;
        if (source) {
          const signature = JSON.stringify([chip.name, chip.problem, messages]);
          if (shownPreview?.key !== key || shownPreview.signature !== signature || shownPreview.source !== source) {
            const node = createElement(ChipPreviewTip, {
              source,
              inner: chip.name,
              problem: chip.problem,
              messages: messages.filter((message) => message.trim() !== ""),
            });
            shownPreview = { key, signature, source, content: { kind: "preview", node } };
          }
          return { key, content: shownPreview.content, part };
        }
        const text = joined([...messages, chip.hover]);
        return text ? { key, content: { kind: "text", text }, part } : null;
      }
      const language = latest.current.language;
      const word = language === "javascript" ? model()?.getWordAtPosition?.(position) : null;
      if (word) {
        // The markers' messages first, then the type information, as Monaco's hover put them.
        return {
          key: `${id}:word:${position.lineNumber}:${word.startColumn}`,
          content: async () => {
            const text = joined([...messages, await typeInformation(position)]);
            return text ? { kind: "text", text } : null;
          },
          part: { lineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn },
        };
      }
      const text = joined(messages);
      return text
        ? {
            key: `${id}:marker:${markers[0].startLineNumber}:${markers[0].startColumn}`,
            content: { kind: "text", text },
            part: null,
          }
        : null;
    };

    /** The box on screen of *position*, a width of none: Monaco's place for
     * it, scaled as the canvas shows the editor, as Monaco's own mouse
     * handling scales a position (editorDom.js). */
    const caretBox = (position: Position): TooltipBox | null => {
      const dom: HTMLElement | null = editor.getDomNode?.() ?? null;
      const at = editor.getScrolledVisiblePosition?.(position);
      if (!dom || !at || typeof at.left !== "number" || typeof at.top !== "number" || typeof at.height !== "number") {
        return null;
      }
      const box = dom.getBoundingClientRect();
      const scale = dom.offsetWidth > 0 ? box.width / dom.offsetWidth : 1;
      return { left: box.left + at.left * scale, top: box.top + at.top * scale, width: 0, height: at.height * scale };
    };

    /** The box on screen of *part* of a line, from Monaco's place for its two ends. */
    const partBox = (part: LinePart): TooltipBox | null => {
      const start = caretBox({ lineNumber: part.lineNumber, column: part.startColumn });
      const end = caretBox({ lineNumber: part.lineNumber, column: part.endColumn });
      if (!start || !end) return null;
      return { left: start.left, top: start.top, width: Math.max(0, end.left - start.left), height: start.height };
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
      const { part } = found;
      current = found.key;
      tooltipStore.rest({
        key: found.key,
        target: null,
        // Read each time it is placed. A chip's name or a word is where Monaco
        // draws it, through any redraw of its line; a marker's message goes by
        // the hovered span while it is on the page, else the character there.
        anchor: () =>
          (part ? partBox(part) : null) ??
          (element && element.isConnected ? element.getBoundingClientRect() : null) ??
          partBox({ lineNumber: position.lineNumber, startColumn: position.column, endColumn: position.column + 1 }),
        // A scroll of anything that holds the editor moves it from under the tooltip.
        anchorElement: editor.getDomNode?.() ?? element,
        side: "top",
        pointer: null,
        content: found.content,
      });
    });

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
    // Monaco takes a move whose element is not in the editor for a leave
    // (mouseHandler.js), and its hit test of that move first draws what it
    // holds to draw (view.js). So a move that lands as Monaco draws its line
    // again reports a leave: the move's element has just left the page, the
    // pointer rests on the line drawn in its place, and no move comes while
    // it rests. That leave keeps the tooltip coming.
    const stillOver = (event: any): boolean => {
      const browserEvent = event?.event?.browserEvent;
      const element = browserEvent?.target;
      const dom: HTMLElement | null = editor.getDomNode?.() ?? null;
      if (!dom || !(element instanceof Node) || element.isConnected) return false;
      const { clientX, clientY } = browserEvent;
      if (typeof document.elementFromPoint !== "function" || !Number.isFinite(clientX) || !Number.isFinite(clientY)) {
        return false;
      }
      const under = document.elementFromPoint(clientX, clientY);
      return under !== null && dom.contains(under);
    };
    const leave = editor.onMouseLeave?.((event: any) => {
      if (!stillOver(event)) letGo();
    });
    // A press, a scroll of the text or an edit leaves nothing where the
    // tooltip points. Monaco also reports a scroll when only the size it can
    // scroll changes, as it measures its lines' widths again after drawing
    // them: the text stays put, and the tooltip with it.
    const down = editor.onMouseDown?.(() => tooltipStore.hide());
    const scroll = editor.onDidScrollChange?.((event: any) => {
      if (event?.scrollTopChanged !== false || event?.scrollLeftChanged !== false) hideOurs();
    });
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
  }, [editor, monaco]);
}

export default useEditorTooltip;
