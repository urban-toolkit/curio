/**
 * Shared tags (#662): every Parameter node's widget is offered under Shared,
 * in the strip above every code or grammar editor and in every node's Widgets
 * tab. A tag drags (or, clicked, inserts) `[!! @name !!]`, and a run writes
 * the Parameter node's value in its place.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import WidgetsEditor from "../../components/editing/WidgetsEditor";
import {
  SHARED_REF_MIME,
  WIDGET_REF_MIME,
  dropReference,
  isReferenceDrag,
} from "../../components/editing/widgets/monacoCodeReferences";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

function dragData() {
  const store = new Map<string, string>();
  return {
    store,
    dataTransfer: {
      setData: (type: string, value: string) => void store.set(type, value),
      effectAllowed: "",
    },
  };
}

const season: WidgetDef = { name: "season", type: "text", label: "Season", default: "summer", value: "winter" };
const factor: WidgetDef = { name: "factor", type: "number", default: 2 };

describe("the strip above a node's code", () => {
  test("offers each shared tag under Shared, though the node has no widgets or inputs", () => {
    const view = render(<ReferenceStrip widgets={[]} shared={[season, factor]} onInsert={jest.fn()} />);
    expect(view.container.querySelector("[data-shared-strip]")?.textContent).toBe("Shared");
    const tags = Array.from(view.container.querySelectorAll("[data-shared-tag]")).map((t) => t.textContent);
    expect(tags).toEqual(["@season", "@factor"]);
  });

  test("a shared tag drags its reference, as a shared tag and not a widget's", () => {
    const view = render(<ReferenceStrip widgets={[factor]} shared={[season]} onInsert={jest.fn()} />);
    const drag = dragData();
    fireEvent.dragStart(view.container.querySelector('[data-shared-tag="season"]')!, drag);
    expect(drag.store.get(SHARED_REF_MIME)).toBe("@season");
    expect(drag.store.get("text/plain")).toBe("[!! @season !!]");
    expect(drag.store.has(WIDGET_REF_MIME)).toBe(false);
  });

  test("a click inserts the reference at the cursor", () => {
    const onInsert = jest.fn();
    const view = render(<ReferenceStrip widgets={[]} shared={[season]} onInsert={onInsert} />);
    fireEvent.click(view.container.querySelector('[data-shared-tag="season"]')!);
    expect(onInsert).toHaveBeenCalledWith("@season");
  });

  test("two Parameter nodes with one name are one tag", () => {
    const view = render(<ReferenceStrip widgets={[]} shared={[factor, { ...factor, default: 3 }]} onInsert={jest.fn()} />);
    expect(view.container.querySelectorAll("[data-shared-tag]")).toHaveLength(1);
  });

  test("a shared tag dropped on the editor inserts its reference where it lands", () => {
    const executeEdits = jest.fn();
    const editor = {
      getTargetAtClientPoint: () => ({ position: { lineNumber: 2, column: 5 } }),
      executeEdits,
      focus: jest.fn(),
    };
    const types = [SHARED_REF_MIME, "text/plain"];
    const event = {
      clientX: 1,
      clientY: 2,
      dataTransfer: { types, getData: (t: string) => (t === SHARED_REF_MIME ? "@season" : "") },
    } as unknown as DragEvent;
    expect(isReferenceDrag(event)).toBe(true);
    expect(dropReference(editor, event)).toBe(true);
    expect(executeEdits.mock.calls[0][1][0]).toEqual(
      expect.objectContaining({
        text: "[!! @season !!]",
        range: { startLineNumber: 2, startColumn: 5, endLineNumber: 2, endColumn: 5 },
      }),
    );
  });
});

describe("a node's Widgets tab", () => {
  const props = {
    sendReplacedCode: jest.fn(),
    nodeId: "n1",
    widgets: [] as WidgetDef[],
    onWidgetsChange: jest.fn(),
    language: "python" as const,
    onResolveError: jest.fn(),
  };

  test("lists the shared tags under Shared, each with its Parameter node's value", () => {
    const view = render(<WidgetsEditor {...props} userCode="" markersDirty={false} shared={[season, factor]} />);
    const rows = view.container.querySelectorAll("[data-shared-panel] [data-shared-row]");
    expect(Array.from(rows).map((r) => r.getAttribute("data-shared-row"))).toEqual(["season", "factor"]);
    expect(rows[0].textContent).toContain("Season");
    expect(rows[0].textContent).toContain('"winter"');
    expect(rows[0].querySelector('[data-shared-tag="season"]')).not.toBeNull();
    expect(screen.queryByText("Shared")).not.toBeNull();
  });

  test("has no Shared list in a dataflow without Parameter nodes", () => {
    const view = render(<WidgetsEditor {...props} userCode="" markersDirty={false} />);
    expect(view.container.querySelector("[data-shared-panel]")).toBeNull();
  });

  test("a run writes the Parameter node's value in place of its reference", () => {
    const sendReplacedCode = jest.fn();
    const onResolveError = jest.fn();
    const code = "s = [!! @season !!]\nk = [!! @factor !!] * 10";
    const view = render(
      <WidgetsEditor
        {...props}
        sendReplacedCode={sendReplacedCode}
        onResolveError={onResolveError}
        userCode={code}
        markersDirty={false}
        shared={[season, factor]}
      />,
    );
    view.rerender(
      <WidgetsEditor
        {...props}
        sendReplacedCode={sendReplacedCode}
        onResolveError={onResolveError}
        userCode={code}
        markersDirty={true}
        shared={[season, factor]}
      />,
    );
    expect(onResolveError).not.toHaveBeenCalled();
    expect(sendReplacedCode).toHaveBeenCalledWith('s = "winter"\nk = 2 * 10');
  });

  test("a run fails, naming the reference, when no Parameter node holds it", () => {
    const sendReplacedCode = jest.fn();
    const onResolveError = jest.fn();
    const view = render(
      <WidgetsEditor
        {...props}
        sendReplacedCode={sendReplacedCode}
        onResolveError={onResolveError}
        userCode="s = [!! @season !!]"
        markersDirty={false}
      />,
    );
    view.rerender(
      <WidgetsEditor
        {...props}
        sendReplacedCode={sendReplacedCode}
        onResolveError={onResolveError}
        userCode="s = [!! @season !!]"
        markersDirty={true}
      />,
    );
    expect(sendReplacedCode).not.toHaveBeenCalled();
    expect(onResolveError).toHaveBeenCalledWith(
      "[!! @season !!]: no Parameter node is named season. Add one, or drag a tag from Shared.",
    );
  });
});
