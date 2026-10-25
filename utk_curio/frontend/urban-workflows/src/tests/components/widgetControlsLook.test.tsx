/**
 * The widget controls in Material UI's look, as komar41 drew them in #914:
 * each control is Material UI's own component, in the widget theme's small
 * size (widgetTheme.ts). The location keeps its own place search.
 */
import React from "react";
import { render } from "@testing-library/react";
import WidgetControl from "../../components/editing/widgets/WidgetControl";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

/** Whether the control drawn for *widget* holds an element matching *selector*. */
function draws(widget: WidgetDef, selector: string): boolean {
  const view = render(<WidgetControl widget={widget} value={widget.default} onChange={jest.fn()} />);
  const found = view.container.querySelector(selector) !== null;
  view.unmount();
  return found;
}

test("each widget control is Material UI's component, in the widget theme's small size", () => {
  const drawn = {
    number: draws(
      { name: "k", type: "number", label: "K", default: 1, options: { min: 1, max: 3, units: "routes" } },
      ".MuiInputBase-sizeSmall.MuiInputBase-adornedEnd input[type='number']",
    ),
    slider: draws(
      { name: "rain", type: "slider", label: "Rain", default: 5, options: { min: 0, max: 50 } },
      ".MuiSlider-sizeSmall input[type='range']",
    ),
    text: draws(
      { name: "place", type: "text", label: "Place", default: "Chicago" },
      ".MuiInputBase-sizeSmall input[type='text']",
    ),
    dropdown: draws(
      { name: "season", type: "choice", label: "Season", default: "summer", options: { choices: ["summer", "winter"] } },
      ".MuiInputBase-sizeSmall select.MuiNativeSelect-select",
    ),
    radio: draws(
      {
        name: "season",
        type: "choice",
        label: "Season",
        default: "summer",
        options: { choices: ["summer", "winter"], display: "radio" },
      },
      ".MuiRadioGroup-root .MuiRadio-sizeSmall input[type='radio']",
    ),
    checkboxGroup: draws(
      { name: "classes", type: "checkbox-group", label: "Classes", default: ["forest"], options: { choices: ["water", "forest"] } },
      ".MuiFormGroup-root .MuiCheckbox-sizeSmall input[type='checkbox']",
    ),
    multiSelect: draws(
      { name: "modes", type: "multi-select", label: "Modes", default: ["bike"], options: { choices: ["walk", "bike"] } },
      ".MuiChip-sizeSmall.MuiChip-deletable",
    ),
    datetime: draws(
      { name: "when", type: "datetime", label: "When", default: "2026-06-21T12:00:00" },
      ".MuiInputBase-sizeSmall input[type='datetime-local']",
    ),
    date: draws(
      { name: "day", type: "date", label: "Day", default: "2026-06-21" },
      ".MuiInputBase-sizeSmall input[type='date']",
    ),
    checkbox: draws(
      { name: "wet", type: "checkbox", label: "Wet", default: true },
      ".MuiCheckbox-sizeSmall input[type='checkbox']",
    ),
    numberList: draws(
      { name: "heights", type: "number-list", label: "Heights", default: [1, 2] },
      ".MuiInputBase-sizeSmall input[type='text']",
    ),
    range: draws(
      { name: "span", type: "range", label: "Span", default: [0, 10] },
      ".MuiInputBase-sizeSmall input[type='number']",
    ),
    file: draws(
      { name: "table", type: "file", label: "Table", default: "" },
      ".MuiButton-sizeSmall input[type='file']",
    ),
  };
  expect(drawn).toEqual({
    number: true,
    slider: true,
    text: true,
    dropdown: true,
    radio: true,
    checkboxGroup: true,
    multiSelect: true,
    datetime: true,
    date: true,
    checkbox: true,
    numberList: true,
    range: true,
    file: true,
  });
});
