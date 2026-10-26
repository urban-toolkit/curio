/**
 * A node's Widgets tab on a dashboard's tile (#1117): a viewer changes the
 * values, which run as a viewer's run, and nothing else. A read-only kind
 * (`contracts/dashboardRuns.json`) keeps its value, and there are no edits,
 * deletes or new widgets: the widgets are the dataflow's author's.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import WidgetsEditor from "../../components/editing/WidgetsEditor";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

const factor: WidgetDef = { name: "factor", type: "number", label: "Factor", default: 2 };
const note: WidgetDef = { name: "note", type: "text", label: "Note", default: "" };
const day: WidgetDef = { name: "day", type: "date", label: "Day", default: "2027-12-21" };

function renderTab(
    valuesOnly: boolean,
    { widgets = [factor, note], userCode = "return [!! factor !!]" }: { widgets?: WidgetDef[]; userCode?: string } = {},
) {
    const onWidgetsChange = jest.fn();
    const onValueChange = jest.fn();
    render(
        <WidgetsEditor
            userCode={userCode}
            sendReplacedCode={jest.fn()}
            nodeId="n1"
            markersDirty={0}
            widgets={widgets}
            onWidgetsChange={onWidgetsChange}
            onValueChange={onValueChange}
            language="python"
            onResolveError={jest.fn()}
            valuesOnly={valuesOnly}
        />,
    );
    return { onWidgetsChange, onValueChange };
}

describe("on a dashboard's tile", () => {
    test("a viewer changes a value, and the change asks for a run", () => {
        const { onWidgetsChange, onValueChange } = renderTab(true);
        const control = screen.getByLabelText("Factor", { selector: "input" }) as HTMLInputElement;
        expect(control.disabled).toBe(false);

        fireEvent.change(control, { target: { value: "5" } });
        fireEvent.blur(control);

        expect(onWidgetsChange).toHaveBeenCalledWith([{ ...factor, value: 5 }, note]);
        expect(onValueChange).toHaveBeenCalled();
    });

    test("a viewer picks a date, and the change asks for a run", () => {
        const { onWidgetsChange, onValueChange } = renderTab(true, {
            widgets: [factor, day], userCode: "return [!! factor !!], [!! day !!]",
        });
        const control = screen.getByLabelText("Day", { selector: "input" }) as HTMLInputElement;
        expect(control.type).toBe("date");
        expect(control.disabled).toBe(false);

        fireEvent.change(control, { target: { value: "2027-06-21" } });
        fireEvent.blur(control);

        expect(onWidgetsChange).toHaveBeenCalledWith([factor, { ...day, value: "2027-06-21" }]);
        expect(onValueChange).toHaveBeenCalled();
    });

    test("a read-only kind keeps its value, and nothing edits, deletes or adds a widget", () => {
        renderTab(true);
        expect((screen.getByLabelText("Note", { selector: "input" }) as HTMLInputElement).disabled).toBe(true);
        expect(screen.queryByRole("button", { name: "Edit widget factor" })).toBeNull();
        expect(screen.queryByRole("button", { name: "Delete widget factor" })).toBeNull();
        expect(screen.queryByRole("button", { name: "Add widget" })).toBeNull();
    });
});

describe("on the canvas", () => {
    test("every value, edit and new widget is the author's to change, as before", () => {
        renderTab(false);
        expect((screen.getByLabelText("Note", { selector: "input" }) as HTMLInputElement).disabled).toBe(false);
        expect(screen.getByRole("button", { name: "Edit widget factor" })).toBeTruthy();
        expect(screen.getByRole("button", { name: "Delete widget factor" })).toBeTruthy();
        expect(screen.getByRole("button", { name: "Add widget" })).toBeTruthy();
    });
});
