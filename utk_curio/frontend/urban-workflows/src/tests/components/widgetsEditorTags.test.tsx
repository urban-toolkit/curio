/**
 * The Widgets tab (#662): widgets are added and set here, shown as tags, and a
 * run resolves the code's `[!! name !!]` references with their values, or ends
 * with a message naming what does not resolve.
 */
import React from "react";
import * as fs from "fs";
import * as path from "path";
import { fireEvent, render, screen } from "@testing-library/react";
import WidgetsEditor from "../../components/editing/WidgetsEditor";
import { normalizeWidgets, type WidgetDef } from "../../utils/widgets/widgetModel";

function renderEditor(overrides: Partial<React.ComponentProps<typeof WidgetsEditor>> = {}) {
  const props: React.ComponentProps<typeof WidgetsEditor> = {
    userCode: "",
    sendReplacedCode: jest.fn(),
    nodeId: "n1",
    markersDirty: 0,
    widgets: [],
    onWidgetsChange: jest.fn(),
    language: "python",
    onResolveError: jest.fn(),
    ...overrides,
  };
  const view = render(<WidgetsEditor {...props} />);
  return { props, view };
}

const factor: WidgetDef = { name: "factor", type: "number", label: "Height factor", default: 1 };

describe("declaring widgets", () => {
  test("a widget is added from the form", () => {
    const { props } = renderEditor();
    expect(screen.getByText(/No widgets yet/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    fireEvent.change(screen.getByLabelText("Widget name"), { target: { value: "season" } });
    fireEvent.change(screen.getByLabelText("Widget type"), { target: { value: "text" } });
    fireEvent.change(screen.getByLabelText("Widget default"), { target: { value: "summer" } });
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));

    expect(props.onWidgetsChange).toHaveBeenCalledWith([{ name: "season", type: "text", default: "summer" }]);
  });

  test("a name the node already has cannot be added", () => {
    renderEditor({ widgets: [factor] });
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    fireEvent.change(screen.getByLabelText("Widget name"), { target: { value: "factor" } });
    expect(screen.getByText(/already has a widget named factor/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Add widget" }) as HTMLButtonElement).disabled).toBe(true);
  });

  test("each widget shows its tag, and setting it records the value", () => {
    const { props, view } = renderEditor({ widgets: [factor] });
    expect(view.container.querySelector('[data-widget-tag="factor"]')).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Height factor"), { target: { value: "2" } });
    expect(props.onWidgetsChange).toHaveBeenLastCalledWith([{ ...factor, value: 2 }]);
  });

  test("an invalid entry is not recorded", () => {
    const { props } = renderEditor({ widgets: [factor] });
    fireEvent.change(screen.getByLabelText("Height factor"), { target: { value: "" } });
    expect(props.onWidgetsChange).not.toHaveBeenCalled();
    expect(screen.getByText("Enter a number.")).toBeTruthy();
  });

  test("a widget is deleted", () => {
    const { props } = renderEditor({ widgets: [factor] });
    fireEvent.click(screen.getByRole("button", { name: "Delete widget factor" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([]);
  });

  test("controls of the node's own sit under its widgets' rows, and only when it has some", () => {
    const fileName: WidgetDef = { name: "file_name", type: "text", label: "File name", default: "" };
    const download = <button type="button">Download trees.csv</button>;
    const { view } = renderEditor({ widgets: [fileName, factor], controls: download });

    const panel = view.container.querySelector<HTMLElement>("[data-widgets-panel]")!;
    const own = panel.querySelector<HTMLElement>("[data-node-controls]");
    expect(own?.textContent).toBe("Download trees.csv");
    // After the last widget's row, before Add widget.
    const order = Array.from(panel.children);
    const lastRow = panel.querySelector('[data-widget-row="factor"]')!;
    expect(order.indexOf(own!)).toBe(order.indexOf(lastRow) + 1);
    expect(order.indexOf(screen.getByRole("button", { name: "Add widget" }))).toBe(order.indexOf(own!) + 1);

    view.rerender(<WidgetsEditor {...{ userCode: "", sendReplacedCode: jest.fn(), nodeId: "n1", markersDirty: 0,
      widgets: [fileName], onWidgetsChange: jest.fn(), language: "python", onResolveError: jest.fn() }} />);
    expect(view.container.querySelector("[data-node-controls]")).toBeNull();
  });

  test("an edit that keeps the type keeps the value set", () => {
    const { props } = renderEditor({ widgets: [{ ...factor, value: 3 }] });
    fireEvent.click(screen.getByRole("button", { name: "Edit widget factor" }));
    fireEvent.change(screen.getByLabelText("Widget label"), { target: { value: "Factor" } });
    fireEvent.click(screen.getByRole("button", { name: "Save widget" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([
      { name: "factor", type: "number", label: "Factor", default: 1, value: 3 },
    ]);
  });
});

describe("a run", () => {
  test("hands on the code with every reference replaced", () => {
    const { props, view } = renderEditor({
      userCode: "return [!! factor !!] * 2",
      widgets: [{ ...factor, value: 3 }],
    });
    view.rerender(<WidgetsEditor {...props} markersDirty={1} />);
    expect(props.sendReplacedCode).toHaveBeenCalledWith("return 3 * 2");
    expect(props.onResolveError).not.toHaveBeenCalled();
  });

  test("a value changed since the last run is the one used", () => {
    const { props, view } = renderEditor({ userCode: "return [!! factor !!]", widgets: [factor] });
    view.rerender(
      <WidgetsEditor {...props} widgets={[{ ...factor, value: 5 }]} markersDirty={1} />,
    );
    expect(props.sendReplacedCode).toHaveBeenCalledWith("return 5");
  });

  test("an old marker or an unknown name ends the run with a message, and is listed", () => {
    const { props, view } = renderEditor({
      userCode: "a = [!! factor$INPUT_VALUE$1 !!]\nb = [!! missing !!]",
      widgets: [factor],
    });
    expect(screen.getByText(/is an old widget marker/)).toBeTruthy();
    expect(screen.getByText(/no widget named missing/)).toBeTruthy();

    view.rerender(<WidgetsEditor {...props} markersDirty={1} />);
    expect(props.sendReplacedCode).not.toHaveBeenCalled();
    expect(props.onResolveError).toHaveBeenCalledWith(
      expect.stringMatching(/old widget marker[\s\S]*no widget named missing/),
    );
  });

  test("an empty Data is not listed, its own control says what to drop, and a run still ends with it", () => {
    const data: WidgetDef = { name: "data", type: "dataset", label: "Data", default: "" };
    const { props, view } = renderEditor({ userCode: "data = curio_load_data([!! data !!])\nreturn data", widgets: [data] });
    expect(screen.queryByLabelText("References that do not resolve")).toBeNull();

    view.rerender(<WidgetsEditor {...props} markersDirty={1} />);
    expect(props.sendReplacedCode).not.toHaveBeenCalled();
    expect(props.onResolveError).toHaveBeenCalledWith(
      expect.stringContaining("[!! data !!]: drop a file or a Data Catalog dataset on Data first."),
    );
  });

  test("mounting resolves nothing; only a change of the count does", () => {
    const { props } = renderEditor({ userCode: "return [!! factor !!]", widgets: [factor] });
    expect(props.sendReplacedCode).not.toHaveBeenCalled();
  });
});

describe("a Scout chart dropped before an input is wired", () => {
  /** Scout's Bars, as the repository ships it: its spec and its widgets. Read
   *  when asked, so a checkout without it fails test by test. */
  function bars(): { spec: string; widgets: unknown } {
    const scout = path.join(path.resolve(__dirname, "../../../../../.."), "packages", "curio.scout@1");
    const manifest = JSON.parse(fs.readFileSync(path.join(scout, "manifest.json"), "utf-8"));
    const template = manifest.templates.find((t: { id: string }) => t.id === "bars");
    return { spec: fs.readFileSync(path.join(scout, template.source), "utf-8"), widgets: template.widgets };
  }

  test("lists the dataset's chip among the references that do not resolve, until an input is wired", () => {
    const { spec, widgets } = bars();
    const { props, view } = renderEditor({
      userCode: spec, widgets: normalizeWidgets(widgets), language: "json", grammar: "vega-lite",
    });
    const list = screen.getByLabelText("References that do not resolve");
    expect(Array.from(list.querySelectorAll("li")).map((item) => item.textContent)).toEqual([
      "[!! inputs !!]: this node has no input to stack. Connect one to an input circle.",
    ]);

    const box = { scenario: "s-base", name: "Baseline", color: "#2a9d8f", rank: 0 };
    view.rerender(<WidgetsEditor {...props} inputs={[{ slot: 0, scenario: box }]} />);
    expect(screen.queryByLabelText("References that do not resolve")).toBeNull();
  });
});

describe("a widget saved under the name the stacked inputs are read by", () => {
  const saved: WidgetDef = { name: "inputs", type: "number", label: "Inputs", default: 3 };

  test("stays listed, its edit cannot be saved, and it can be deleted", () => {
    const { props } = renderEditor({ widgets: [saved] });
    expect(screen.getByText("Inputs")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Edit widget inputs" }));
    expect(screen.getByText("inputs names the node's stacked inputs. Pick another name.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save widget" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete widget inputs" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([]);
  });
});
