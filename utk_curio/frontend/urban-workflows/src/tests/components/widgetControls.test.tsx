/**
 * The controls Curio lacked for SCOUT's widgets (#662): slider, radio, checkbox
 * group, multi-select, date and time, and location. Each records the value
 * its kind holds, and only a valid one; the Widgets tab's form declares them.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";

const mockSearchPlaces = jest.fn();
jest.mock("../../services/discoveryCatalog", () => {
  const actual = jest.requireActual("../../services/discoveryCatalog");
  return {
    ...actual,
    discoveryCatalogApi: {
      ...actual.discoveryCatalogApi,
      searchPlaces: (...args: unknown[]) => mockSearchPlaces(...args),
    },
  };
});

import WidgetControl from "../../components/editing/widgets/WidgetControl";
import WidgetsEditor from "../../components/editing/WidgetsEditor";
import { placePoint } from "../../components/editing/widgets/LocationControl";
import type { WidgetDef, WidgetValue } from "../../utils/widgets/widgetModel";

function renderControl(widget: WidgetDef, value: WidgetValue = widget.default) {
  const onChange = jest.fn();
  const view = render(<WidgetControl widget={widget} value={value} onChange={onChange} />);
  return { onChange, view };
}

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

const CHICAGO = {
  name: "Chicago",
  label: "Chicago, Illinois, United States",
  box: [-87.94, 41.64, -87.52, 42.02],
  kind: "city",
  boundary: true,
};

beforeEach(() => mockSearchPlaces.mockReset());

describe("slider and number bounds", () => {
  const rain: WidgetDef = {
    name: "rain",
    type: "slider",
    label: "Rain",
    default: 5,
    options: { min: 0, max: 50, step: 0.5, units: "mm" },
  };

  test("a slider spans its bounds, shows its value with units, and records a number", () => {
    const { onChange, view } = renderControl(rain);
    const slider = screen.getByLabelText("Rain") as HTMLInputElement;
    expect([slider.type, slider.min, slider.max, slider.step]).toEqual(["range", "0", "50", "0.5"]);
    expect(view.container.querySelector("output")?.textContent).toBe("5 mm");

    fireEvent.change(slider, { target: { value: "12.5" } });
    expect(onChange).toHaveBeenCalledWith(12.5);
  });

  test("a number outside its bounds is not recorded", () => {
    const k: WidgetDef = { name: "k", type: "number", label: "K", default: 1, options: { min: 1, max: 3, units: "routes" } };
    const { onChange } = renderControl(k);
    expect(screen.getByText("routes")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("K"), { target: { value: "4" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("Enter a number from 1 to 3.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("K"), { target: { value: "2" } });
    expect(onChange).toHaveBeenCalledWith(2);
  });
});

describe("choices", () => {
  const season: WidgetDef = {
    name: "season",
    type: "choice",
    label: "Season",
    default: "summer",
    options: { choices: ["summer", "winter"], display: "radio" },
  };

  test("a choice shown as radio buttons records the one clicked", () => {
    const { onChange } = renderControl(season);
    const group = screen.getByRole("radiogroup", { name: "Season" });
    expect((within(group).getByLabelText("summer") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(group).getByLabelText("winter"));
    expect(onChange).toHaveBeenCalledWith("winter");
  });

  test("two radio controls for widgets of the same name do not share a group", () => {
    render(
      <>
        <WidgetControl widget={season} value="summer" onChange={jest.fn()} ariaLabel="First" />
        <WidgetControl widget={season} value="winter" onChange={jest.fn()} ariaLabel="Second" />
      </>,
    );
    const first = within(screen.getByRole("radiogroup", { name: "First" })).getByLabelText("summer") as HTMLInputElement;
    const second = within(screen.getByRole("radiogroup", { name: "Second" })).getByLabelText("summer") as HTMLInputElement;
    expect(first.name).not.toBe(second.name);
    expect((within(screen.getByRole("radiogroup", { name: "Second" })).getByLabelText("winter") as HTMLInputElement).checked).toBe(true);
  });

  test("a checkbox group records the checked choices in the choices' order", () => {
    const classes: WidgetDef = {
      name: "classes",
      type: "checkbox-group",
      label: "Classes",
      default: ["forest"],
      options: { choices: ["water", "forest", "grass"] },
    };
    const { onChange } = renderControl(classes);
    const group = screen.getByRole("group", { name: "Classes" });
    fireEvent.click(within(group).getByLabelText("water"));
    expect(onChange).toHaveBeenLastCalledWith(["water", "forest"]);
    fireEvent.click(within(group).getByLabelText("forest"));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  test("a multi-select adds from its list and removes a chip, in the choices' order", () => {
    const modes: WidgetDef = {
      name: "modes",
      type: "multi-select",
      label: "Modes",
      default: ["bike"],
      options: { choices: ["walk", "bike", "drive"] },
    };
    const { onChange } = renderControl(modes);
    const add = screen.getByLabelText("Modes") as HTMLSelectElement;
    expect([...add.options].map((o) => o.value)).toEqual(["", "walk", "drive"]);
    fireEvent.change(add, { target: { value: "walk" } });
    expect(onChange).toHaveBeenLastCalledWith(["walk", "bike"]);
    fireEvent.click(screen.getByRole("button", { name: "Remove bike" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  test("a multi-select with every choice taken has nothing to add", () => {
    renderControl({ name: "m", type: "multi-select", label: "M", default: ["a"], options: { choices: ["a"] } });
    expect((screen.getByLabelText("M") as HTMLSelectElement).disabled).toBe(true);
  });
});

describe("date and time", () => {
  const when: WidgetDef = { name: "when", type: "datetime", label: "When", default: "2026-06-21T12:00:00" };

  test("a browser's value without seconds is recorded with them", () => {
    const { onChange } = renderControl(when);
    const input = screen.getByLabelText("When") as HTMLInputElement;
    expect(input.type).toBe("datetime-local");
    fireEvent.change(input, { target: { value: "2026-12-21T08:30" } });
    expect(onChange).toHaveBeenCalledWith("2026-12-21T08:30:00");
  });

  test("a cleared field is not recorded", () => {
    const { onChange } = renderControl(when);
    fireEvent.change(screen.getByLabelText("When"), { target: { value: "" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText("Enter a date and time.")).toBeTruthy();
  });
});

describe("location", () => {
  const origin: WidgetDef = { name: "origin", type: "location", label: "Origin", default: { lat: 0, lon: 0 } };

  test("typed coordinates are recorded as {lat, lon}", () => {
    const { onChange } = renderControl(origin);
    fireEvent.change(screen.getByLabelText("Origin latitude"), { target: { value: "41.8781" } });
    expect(onChange).toHaveBeenLastCalledWith({ lat: 41.8781, lon: 0 });
    fireEvent.change(screen.getByLabelText("Origin longitude"), { target: { value: "-87.6298" } });
    expect(onChange).toHaveBeenLastCalledWith({ lat: 41.8781, lon: -87.6298 });
  });

  test("a latitude off the globe is not recorded", () => {
    const { onChange } = renderControl(origin);
    fireEvent.change(screen.getByLabelText("Origin latitude"), { target: { value: "91" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/latitude from -90 to 90/)).toBeTruthy();
  });

  test("a place is searched only when asked, and picking it records the center of its box", async () => {
    mockSearchPlaces.mockResolvedValue({ places: [CHICAGO] });
    const { onChange } = renderControl(origin);
    const field = screen.getByLabelText("Origin: search a place");
    fireEvent.change(field, { target: { value: "Chicago" } });
    expect(mockSearchPlaces).not.toHaveBeenCalled();

    fireEvent.keyDown(field, { key: "Enter" });
    expect(mockSearchPlaces).toHaveBeenCalledWith("Chicago", expect.anything());
    fireEvent.click(await screen.findByRole("option", { name: CHICAGO.label }));
    expect(onChange).toHaveBeenLastCalledWith({ lat: 41.83, lon: -87.73 });
    expect(screen.getByText(CHICAGO.label)).toBeTruthy();
    expect(screen.getByText(/OpenStreetMap contributors/)).toBeTruthy();
  });

  test("a place's point is its box's center, to six decimals", () => {
    expect(placePoint([-87.94, 41.64, -87.52, 42.02])).toEqual({ lat: 41.83, lon: -87.73 });
    expect(placePoint([0, 0, 1 / 3, 1 / 3])).toEqual({ lat: 0.166667, lon: 0.166667 });
  });

  test("a run writes the location as a Python dict", () => {
    const { props, view } = renderEditor({
      userCode: "origin = [!! origin !!]",
      widgets: [{ ...origin, value: { lat: 41.8781, lon: -87.6298 } }],
    });
    view.rerender(<WidgetsEditor {...props} markersDirty={true} />);
    expect(props.sendReplacedCode).toHaveBeenCalledWith('origin = {"lat": 41.8781, "lon": -87.6298}');
  });
});

describe("declaring the new widgets", () => {
  const openForm = (name: string, type: string) => {
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    fireEvent.change(screen.getByLabelText("Widget name"), { target: { value: name } });
    fireEvent.change(screen.getByLabelText("Widget type"), { target: { value: type } });
  };

  test("a slider starts at 0 to 100 and is saved with its bounds, step and units", () => {
    const { props } = renderEditor();
    openForm("rain", "slider");
    expect((screen.getByLabelText("Widget minimum") as HTMLInputElement).value).toBe("0");
    expect((screen.getByLabelText("Widget maximum") as HTMLInputElement).value).toBe("100");
    fireEvent.change(screen.getByLabelText("Widget maximum"), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("Widget step"), { target: { value: "0.5" } });
    fireEvent.change(screen.getByLabelText("Widget units"), { target: { value: "mm" } });
    fireEvent.change(screen.getByLabelText("Widget default"), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([
      { name: "rain", type: "slider", default: 12.5, options: { min: 0, max: 50, step: 0.5, units: "mm" } },
    ]);
  });

  test("a slider without a maximum cannot be added", () => {
    renderEditor();
    openForm("rain", "slider");
    fireEvent.change(screen.getByLabelText("Widget maximum"), { target: { value: "" } });
    expect(screen.getByText("A slider needs a minimum and a maximum.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Add widget" }) as HTMLButtonElement).disabled).toBe(true);
  });

  test("a new bound pulls a slider's default inside it", () => {
    const { props } = renderEditor();
    openForm("rain", "slider");
    fireEvent.change(screen.getByLabelText("Widget minimum"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([
      { name: "rain", type: "slider", default: 10, options: { min: 10, max: 100 } },
    ]);
  });

  test("a choice can be shown as radio buttons", () => {
    const { props } = renderEditor();
    openForm("season", "choice");
    fireEvent.change(screen.getByLabelText("Widget choices"), { target: { value: "summer, winter" } });
    fireEvent.change(screen.getByLabelText("Widget display"), { target: { value: "radio" } });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Widget default" })).getByLabelText("winter"));
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([
      { name: "season", type: "choice", default: "winter", options: { choices: ["summer", "winter"], display: "radio" } },
    ]);
  });

  test("a checkbox group's default keeps only choices that remain", () => {
    const { props } = renderEditor();
    openForm("classes", "checkbox-group");
    fireEvent.change(screen.getByLabelText("Widget choices"), { target: { value: "water, forest, grass" } });
    const group = () => screen.getByRole("group", { name: "Widget default" });
    fireEvent.click(within(group()).getByLabelText("forest"));
    fireEvent.click(within(group()).getByLabelText("grass"));
    fireEvent.change(screen.getByLabelText("Widget choices"), { target: { value: "water, grass" } });
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([
      { name: "classes", type: "checkbox-group", default: ["grass"], options: { choices: ["water", "grass"] } },
    ]);
  });

  test("a date-time widget starts at a valid minute", () => {
    const { props } = renderEditor();
    openForm("when", "datetime");
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    const [saved] = (props.onWidgetsChange as jest.Mock).mock.calls[0][0];
    expect(saved).toEqual({ name: "when", type: "datetime", default: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00$/) });
  });

  test("a location widget is added with the coordinates typed as its default", () => {
    const { props } = renderEditor();
    openForm("origin", "location");
    fireEvent.change(screen.getByLabelText("Widget default latitude"), { target: { value: "41.8781" } });
    fireEvent.change(screen.getByLabelText("Widget default longitude"), { target: { value: "-87.6298" } });
    fireEvent.click(screen.getByRole("button", { name: "Add widget" }));
    expect(props.onWidgetsChange).toHaveBeenCalledWith([
      { name: "origin", type: "location", default: { lat: 41.8781, lon: -87.6298 } },
    ]);
  });
});
