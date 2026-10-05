/**
 * Selection tags in a node's Widgets tab (#662): a view's current selection is
 * added as a tag, offered for a view whose rows have a stable id column and
 * refused for one without; the strip above the code drags its reference, and a
 * run writes the selected rows' ids in its place.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import WidgetsEditor from "../../components/editing/WidgetsEditor";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { SELECTION_REF_MIME, WIDGET_REF_MIME } from "../../components/editing/widgets/monacoCodeReferences";
import { VisInteractionType } from "../../constants";
import { objectRows } from "../../utils/selectionMatch";
import { SELECTION_ID_CAP, type SelectionTag } from "../../utils/references/selectionTags";
import {
  provideViewRows,
  recordViewSelection,
  resetViewSelections,
} from "../../utils/references/viewSelections";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

const ROWS = [
  { osm_id: 101, height: 10 },
  { osm_id: 102, height: 30 },
  { osm_id: 103, height: 50 },
];
const CHART = { id: "chart-1", label: "Heights" };
const brush = (bounds: Record<string, unknown>) => ({
  brush: { type: VisInteractionType.INTERVAL, data: bounds, priority: 1 },
});

function holdRows(nodeId: string, rows: Record<string, unknown>[]) {
  return provideViewRows(nodeId, () => (rows.length ? { rows: objectRows(rows), columns: Object.keys(rows[0]) } : null));
}

const props = {
  sendReplacedCode: jest.fn(),
  nodeId: "n1",
  widgets: [] as WidgetDef[],
  onWidgetsChange: jest.fn(),
  language: "python" as const,
  onResolveError: jest.fn(),
  userCode: "",
  markersDirty: false,
};

afterEach(() => resetViewSelections());

describe("the Selections part of a node's Widgets tab", () => {
  test("is not there in a dataflow without a view, so the tab looks as it did", () => {
    const view = render(<WidgetsEditor {...props} />);
    expect(view.container.querySelector("[data-selections-panel]")).toBeNull();
  });

  test("offers a tag for a view whose rows have an osm_id, holding the ids its selection picks", async () => {
    holdRows(CHART.id, ROWS);
    recordViewSelection(CHART.id, brush({ height: [20, 60] }));
    const onSelectionsChange = jest.fn();
    render(<WidgetsEditor {...props} views={[CHART]} nodeIds={new Set([CHART.id])} onSelectionsChange={onSelectionsChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Add selection" }));
    const column = (await screen.findByLabelText("Selection id column")) as HTMLSelectElement;
    expect(column.value).toBe("osm_id");
    expect((screen.getByLabelText("Selection tag name") as HTMLInputElement).value).toBe("heights");
    const add = screen.getByRole("button", { name: "Add selection tag" });
    expect(add).not.toBeDisabled();
    fireEvent.click(add);
    await waitFor(() => expect(onSelectionsChange).toHaveBeenCalled());
    expect(onSelectionsChange).toHaveBeenCalledWith([
      { name: "heights", node: CHART.id, column: "osm_id", ids: [102, 103] },
    ]);
  });

  test("refuses a view whose rows no column tells apart, saying why", async () => {
    holdRows(CHART.id, [{ kind: "tree" }, { kind: "tree" }]);
    render(<WidgetsEditor {...props} views={[CHART]} nodeIds={new Set([CHART.id])} />);
    fireEvent.click(screen.getByRole("button", { name: "Add selection" }));
    const problem = await screen.findByText(/have no column that tells them apart, such as osm_id or building_id/);
    expect(problem.textContent).toContain("The rows of Heights");
    expect(screen.queryByLabelText("Selection id column")).toBeNull();
    expect(screen.getByRole("button", { name: "Add selection tag" })).toBeDisabled();
  });

  test("asks to run a view whose rows are not known yet", async () => {
    render(<WidgetsEditor {...props} views={[CHART]} nodeIds={new Set([CHART.id])} />);
    fireEvent.click(screen.getByRole("button", { name: "Add selection" }));
    expect(await screen.findByText("Run Heights first: its rows are not known yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add selection tag" })).toBeDisabled();
  });

  test("a selection over the cap is held as its count, with a message that says so", async () => {
    const many = Array.from({ length: SELECTION_ID_CAP + 1 }, (_, i) => ({ osm_id: i, v: 1 }));
    holdRows(CHART.id, many);
    recordViewSelection(CHART.id, brush({ v: [0, 2] }));
    const onSelectionsChange = jest.fn();
    const view = render(
      <WidgetsEditor {...props} views={[CHART]} nodeIds={new Set([CHART.id])} onSelectionsChange={onSelectionsChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add selection" }));
    await screen.findByLabelText("Selection id column");
    fireEvent.click(screen.getByRole("button", { name: "Add selection tag" }));
    await waitFor(() => expect(onSelectionsChange).toHaveBeenCalled());
    const [tags] = onSelectionsChange.mock.calls[0] as [SelectionTag[]];
    expect(tags).toEqual([{ name: "heights", node: CHART.id, column: "osm_id", count: SELECTION_ID_CAP + 1 }]);

    view.rerender(<WidgetsEditor {...props} views={[CHART]} nodeIds={new Set([CHART.id])} selections={tags} />);
    expect(view.container.querySelector('[data-selection-state="heights"]')?.textContent).toBe(
      `The selection holds ${SELECTION_ID_CAP + 1} ids, more than the ${SELECTION_ID_CAP} a selection tag takes. `
        + "Select fewer rows in its view.",
    );
  });

  test("lists each tag with how many ids it holds, and deletes one", () => {
    const tags: SelectionTag[] = [
      { name: "heights", node: CHART.id, column: "osm_id", ids: [102, 103] },
      { name: "none_yet", node: CHART.id, column: "osm_id", ids: [] },
      { name: "gone", node: "deleted-view", column: "osm_id", ids: [1] },
    ];
    const onSelectionsChange = jest.fn();
    const view = render(
      <WidgetsEditor
        {...props}
        views={[CHART]}
        nodeIds={new Set([CHART.id])}
        selections={tags}
        onSelectionsChange={onSelectionsChange}
      />,
    );
    const state = (name: string) => view.container.querySelector(`[data-selection-state="${name}"]`)?.textContent;
    expect(state("heights")).toBe("2 selected");
    expect(state("none_yet")).toBe("Nothing selected");
    expect(state("gone")).toBe("Its view was deleted.");
    expect(view.container.querySelector('[data-selection-row="heights"] [data-selection-tag="heights"]')?.textContent).toBe(
      "selection heights",
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete selection tag gone" }));
    expect(onSelectionsChange).toHaveBeenCalledWith(tags.slice(0, 2));
  });

  test("a run writes the selected rows' ids in place of the reference", () => {
    const sendReplacedCode = jest.fn();
    const onResolveError = jest.fn();
    const tags: SelectionTag[] = [{ name: "heights", node: CHART.id, column: "osm_id", ids: [102, 103] }];
    const code = "picked = [!! selection heights !!]\nreturn arg[arg['osm_id'].isin(picked)]";
    const make = (markersDirty: boolean) => (
      <WidgetsEditor
        {...props}
        sendReplacedCode={sendReplacedCode}
        onResolveError={onResolveError}
        userCode={code}
        markersDirty={markersDirty}
        selections={tags}
        views={[CHART]}
        nodeIds={new Set([CHART.id])}
      />
    );
    const view = render(make(false));
    act(() => view.rerender(make(true)));
    expect(onResolveError).not.toHaveBeenCalled();
    expect(sendReplacedCode).toHaveBeenCalledWith("picked = [102, 103]\nreturn arg[arg['osm_id'].isin(picked)]");
  });
});

describe("the strip above a node's code", () => {
  const tag: SelectionTag = { name: "heights", node: CHART.id, column: "osm_id", ids: [102] };

  test("offers the node's selection tags under Selections", () => {
    const view = render(<ReferenceStrip widgets={[]} selections={[tag]} onInsert={jest.fn()} />);
    expect(view.container.querySelector("[data-selection-strip]")?.textContent).toBe("Selections");
    expect(view.container.querySelector('[data-selection-tag="heights"]')?.textContent).toBe("selection heights");
  });

  test("a selection tag drags its reference, as a selection and not a widget", () => {
    const store = new Map<string, string>();
    const view = render(<ReferenceStrip widgets={[]} selections={[tag]} onInsert={jest.fn()} />);
    fireEvent.dragStart(view.container.querySelector('[data-selection-tag="heights"]')!, {
      dataTransfer: { setData: (type: string, value: string) => void store.set(type, value), effectAllowed: "" },
    });
    expect(store.get(SELECTION_REF_MIME)).toBe("selection heights");
    expect(store.get("text/plain")).toBe("[!! selection heights !!]");
    expect(store.has(WIDGET_REF_MIME)).toBe(false);
  });
});
