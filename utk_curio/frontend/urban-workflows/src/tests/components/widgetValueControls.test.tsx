/**
 * A node's widgets as controls that set their values (#662, #1117), the rows a
 * pinned node's dashboard tile shows, and the Widgets tab of a template that
 * shows only its controls: a label and a control each, then the node's own
 * controls. A value reaches the node once its control settles, or at once when
 * it is left; a value set from outside while one settles replaces it; on a
 * dashboard a read-only kind stays disabled.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { VALUE_SETTLE_MS, WidgetValueControls } from "../../components/editing/widgets/WidgetValueControls";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

const factor: WidgetDef = { name: "factor", type: "number", label: "Factor", default: 2 };
const season: WidgetDef = {
  name: "season", type: "choice", label: "Season", default: "summer",
  options: { choices: ["spring", "summer", "winter"], display: "radio" },
};
const note: WidgetDef = { name: "note", type: "text", label: "Note", default: "" };

const numberInput = (label: string) => screen.getByLabelText(label, { selector: "input" }) as HTMLInputElement;

afterEach(() => {
  jest.useRealTimers();
});

describe("a tile's controls", () => {
  test("show a label and a control for each widget", () => {
    const { container } = render(<WidgetValueControls widgets={[factor, season]} onCommit={jest.fn()} />);

    const rows = Array.from(container.querySelectorAll("[data-widget-row]")).map((row) => row.getAttribute("data-widget-row"));
    expect(rows).toEqual(["factor", "season"]);
    expect(screen.getByText("Factor")).toBeTruthy();
    expect(screen.getByText("Season")).toBeTruthy();
    expect(numberInput("Factor").value).toBe("2");
    expect((screen.getByRole("radio", { name: "summer" }) as HTMLInputElement).checked).toBe(true);
  });

  test("a value reaches the node once, when its control settles", () => {
    jest.useFakeTimers();
    const onCommit = jest.fn();
    render(<WidgetValueControls widgets={[factor]} onCommit={onCommit} />);

    fireEvent.change(numberInput("Factor"), { target: { value: "5" } });
    fireEvent.change(numberInput("Factor"), { target: { value: "6" } });
    act(() => { jest.advanceTimersByTime(VALUE_SETTLE_MS - 1); });
    expect(onCommit).not.toHaveBeenCalled();

    act(() => { jest.advanceTimersByTime(1); });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("factor", 6);
  });

  test("leaving a control sends its value at once", () => {
    const onCommit = jest.fn();
    render(<WidgetValueControls widgets={[season]} onCommit={onCommit} />);
    const winter = screen.getByRole("radio", { name: "winter" });

    fireEvent.click(winter);
    fireEvent.blur(winter);

    expect(onCommit).toHaveBeenCalledWith("season", "winter");
  });

  test("a value the node already holds is not sent again", () => {
    const onCommit = jest.fn();
    render(<WidgetValueControls widgets={[factor]} onCommit={onCommit} />);

    fireEvent.change(numberInput("Factor"), { target: { value: "2" } });
    fireEvent.blur(numberInput("Factor"));

    expect(onCommit).not.toHaveBeenCalled();
  });

  test("a value still settling is sent when the controls go", () => {
    const onCommit = jest.fn();
    const { unmount } = render(<WidgetValueControls widgets={[factor]} onCommit={onCommit} />);

    fireEvent.change(numberInput("Factor"), { target: { value: "7" } });
    unmount();

    expect(onCommit).toHaveBeenCalledWith("factor", 7);
  });

  test("a value set from outside while one settles replaces it", () => {
    jest.useFakeTimers();
    const onCommit = jest.fn();
    const { rerender } = render(<WidgetValueControls widgets={[factor]} onCommit={onCommit} />);

    fireEvent.change(numberInput("Factor"), { target: { value: "5" } });
    rerender(<WidgetValueControls widgets={[{ ...factor, value: 9 }]} onCommit={onCommit} />);
    act(() => { jest.advanceTimersByTime(VALUE_SETTLE_MS); });

    expect(onCommit).not.toHaveBeenCalled();
    expect(numberInput("Factor").value).toBe("9");
  });

  test("on a dashboard a text widget stays read-only, as the dashboard's contract says", () => {
    render(<WidgetValueControls widgets={[note, season]} onCommit={jest.fn()} dashboard />);

    expect(numberInput("Note").disabled).toBe(true);
    expect((screen.getByRole("radio", { name: "winter" }) as HTMLInputElement).disabled).toBe(false);
  });

  test("anywhere else every kind is changeable", () => {
    render(<WidgetValueControls widgets={[note]} onCommit={jest.fn()} />);

    expect(numberInput("Note").disabled).toBe(false);
  });

  test("controls of the node's own sit under its widgets' rows, and only when it has some", () => {
    const fileName: WidgetDef = { name: "file_name", type: "text", label: "File name", default: "" };
    const download = <button type="button">Download trees.csv</button>;
    const { container, rerender } = render(
      <WidgetValueControls widgets={[fileName, factor]} onCommit={jest.fn()} controls={download} />,
    );

    const panel = container.querySelector<HTMLElement>("[data-widget-controls]")!;
    const own = panel.querySelector<HTMLElement>("[data-node-controls]");
    expect(own?.textContent).toBe("Download trees.csv");
    // After the last widget's row, the panel's last part.
    const order = Array.from(panel.children);
    const lastRow = panel.querySelector('[data-widget-row="factor"]')!;
    expect(order.indexOf(own!)).toBe(order.indexOf(lastRow) + 1);
    expect(order.indexOf(own!)).toBe(order.length - 1);

    rerender(<WidgetValueControls widgets={[fileName]} onCommit={jest.fn()} />);
    expect(container.querySelector("[data-node-controls]")).toBeNull();
  });

  test("above an output they keep their own height; else they fill their pane", () => {
    const { container, rerender } = render(<WidgetValueControls widgets={[factor]} onCommit={jest.fn()} aboveOutput />);
    expect(container.firstElementChild?.className).toContain("panelAboveOutput");

    rerender(<WidgetValueControls widgets={[factor]} onCommit={jest.fn()} />);
    expect(container.firstElementChild?.className).not.toContain("panelAboveOutput");
  });
});
