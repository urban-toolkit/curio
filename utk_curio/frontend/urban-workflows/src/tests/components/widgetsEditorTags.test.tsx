/**
 * The Widgets tab (#662): widgets are added and set here, shown as tags, and a
 * run resolves the code's `[!! name !!]` references with their values, or ends
 * with a message naming what does not resolve.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import WidgetsEditor from "../../components/editing/WidgetsEditor";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

function renderEditor(overrides: Partial<React.ComponentProps<typeof WidgetsEditor>> = {}) {
  const props: React.ComponentProps<typeof WidgetsEditor> = {
    userCode: "",
    sendReplacedCode: jest.fn(),
    nodeId: "n1",
    markersDirty: false,
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
    view.rerender(<WidgetsEditor {...props} markersDirty={true} />);
    expect(props.sendReplacedCode).toHaveBeenCalledWith("return 3 * 2");
    expect(props.onResolveError).not.toHaveBeenCalled();
  });

  test("a value changed since the last run is the one used", () => {
    const { props, view } = renderEditor({ userCode: "return [!! factor !!]", widgets: [factor] });
    view.rerender(
      <WidgetsEditor {...props} widgets={[{ ...factor, value: 5 }]} markersDirty={true} />,
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

    view.rerender(<WidgetsEditor {...props} markersDirty={true} />);
    expect(props.sendReplacedCode).not.toHaveBeenCalled();
    expect(props.onResolveError).toHaveBeenCalledWith(
      expect.stringMatching(/old widget marker[\s\S]*no widget named missing/),
    );
  });

  test("mounting resolves nothing; only a toggle does", () => {
    const { props } = renderEditor({ userCode: "return [!! factor !!]", widgets: [factor] });
    expect(props.sendReplacedCode).not.toHaveBeenCalled();
  });
});
