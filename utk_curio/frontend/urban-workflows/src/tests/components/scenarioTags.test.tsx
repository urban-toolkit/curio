/**
 * The tags a chart's or a map's scenarios are written with (#662), in the
 * header above a spec whose node receives an edge from a scenario box.
 *
 * - Scenarios, in a Vega-Lite spec: the boxes' swatches with their names, in
 *   the order the dataflow lists the boxes, then each input from no box in a
 *   grey of its own. The swatches are one chip, the scale of the scenarios'
 *   colors, `[!! scenario colors !!]`; then **text colors**,
 *   `[!! scenario text_colors !!]`, and **order**, `[!! scenario order !!]`.
 *   Then, in a Vega-Lite or an Autark spec, a chip per input,
 *   `input_0 ■ Baseline`, which drags `[!! scenario input_0 !!]`. Every color
 *   shown is the color its chip writes.
 * - An Autark spec's Scenarios holds the chips per input alone.
 * - A node fed from no box has no Scenarios category.
 * - Inputs, in a Vega-Lite spec with an input, one or several: an `inputs` tag
 *   after `input_0`, `input_1`, ... drags the chip of the dataset that stacks
 *   them, `[!! inputs !!]`. It opens to the dataset's fields: `scenario_name`,
 *   `scenario` and `__input__`, then the union of the inputs' columns, each with
 *   its dtype in its title. A field drags its chip, `[!! inputs.sunlight !!]`.
 *   No input tag and no field shows a swatch.
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { INPUT_REF_MIME, SCENARIO_REF_MIME } from "../../components/editing/widgets/monacoCodeReferences";
import { resolveReferences, type InputScope } from "../../utils/references/codeReferences";
import { chipsOf, draggedText, eachCategory, headerRow, openCategory } from "../_support/stripCategories";

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

// Wired Twice as tall first, but the dataflow lists Baseline first.
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51", rank: 1 };
const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f", rank: 0 };
const SURVEY = { name: "Roof survey", color: "#8a8f98" };

const inputs: InputScope[] = [
  {
    slot: 0, label: "Shade", dataType: "dataframe", columns: ["segment", "sunlight"],
    dtypes: { segment: "object", sunlight: "float64" }, scenario: TALL,
  },
  {
    slot: 1, label: "Shade", dataType: "dataframe", columns: ["segment", "sunlight", "shade"],
    dtypes: { segment: "object", sunlight: "float64", shade: "float64" }, scenario: BASE,
  },
  {
    slot: 2, label: "Roof survey", dataType: "geodataframe", columns: ["segment", "geometry"],
    dtypes: { segment: "object", geometry: "geometry" }, scenario: SURVEY,
  },
];

const free = (slot: number, name: string): InputScope => ({
  slot, label: name, dataType: "dataframe", columns: ["mode", "trips"], scenario: { name, color: "#8a8f98" },
});

const strip = (wired: InputScope[], more: Record<string, unknown> = {}) =>
  render(<ReferenceStrip widgets={[]} inputs={wired} language="json" grammar="vega-lite" onInsert={jest.fn()} {...more} />);

/** What the chip *inner* writes over *wired*, as a run writes it, read back as JSON. */
const written = (inner: string, wired: InputScope[]) =>
  JSON.parse(resolveReferences(`[!! ${inner} !!]`, { widgets: [], inputs: wired, shared: [] }, "json").code);

/** Each chip of an input in Scenarios: its circle, the name beside its swatch, and its swatch's color. */
const inputChipsOf = (chips: HTMLElement) =>
  Array.from(chips.querySelectorAll("[data-scenario-input]")).map((tag) => [
    tag.getAttribute("data-scenario-input"),
    tag.querySelector("[data-scenario-swatch]")?.getAttribute("data-scenario-swatch"),
    tag.getAttribute("data-color"),
  ]);

const openInputs = () => fireEvent.click(screen.getByLabelText("Show the fields of inputs"));

describe("Scenarios, in a Vega-Lite spec fed from boxes", () => {
  test("holds the swatches, text colors and order, then a chip per input, in that order", () => {
    const view = strip(inputs);
    expect(headerRow(view.container).map((entry) => entry.label)).toEqual(["Inputs 4", "Scenarios 6"]);
    const chips = openCategory(view.container, "scenarios");
    const order = Array.from(chips.children).map(
      (tag) => tag.getAttribute("data-scenario-chip") ?? (tag.hasAttribute("data-scenario-swatches") ? "swatches" : `input_${tag.getAttribute("data-scenario-input")}`),
    );
    expect(order).toEqual(["swatches", "text_colors", "order", "input_0", "input_1", "input_2"]);
    expect(chips.querySelector('[data-scenario-chip="text_colors"]')!.textContent).toBe("text colors");
    expect(chips.querySelector('[data-scenario-chip="order"]')!.textContent).toBe("order");
  });

  test("the swatches are the boxes in the dataflow's order, then an input from no box in grey: the scale their chip writes", () => {
    const view = strip(inputs);
    const chips = openCategory(view.container, "scenarios");
    const swatches = Array.from(chips.querySelectorAll("[data-scenario-swatches] [data-scenario-swatch]"));
    expect(swatches.map((s) => [s.getAttribute("data-scenario-swatch"), s.getAttribute("data-color")])).toEqual([
      ["Baseline", "#2a9d8f"],
      ["Twice as tall", "#e76f51"],
      ["Roof survey", "#8a8f98"],
    ]);
    expect(swatches.map((s) => s.textContent)).toEqual(["Baseline", "Twice as tall", "Roof survey"]);
    const scale = written("scenario colors", inputs);
    expect(swatches.map((s) => s.getAttribute("data-scenario-swatch"))).toEqual(scale.domain);
    expect(swatches.map((s) => s.getAttribute("data-color"))).toEqual(scale.range);
  });

  test("the swatches drag one chip, the scale of the scenarios' colors, and a click inserts it", () => {
    const onInsert = jest.fn();
    const view = strip(inputs, { onInsert });
    const swatches = openCategory(view.container, "scenarios").querySelector("[data-scenario-swatches]")!;
    expect(swatches.getAttribute("draggable")).toBe("true");
    const drag = dragData();
    fireEvent.dragStart(swatches, drag);
    expect(drag.store.get(SCENARIO_REF_MIME)).toBe("scenario colors");
    expect(drag.store.get("text/plain")).toBe("[!! scenario colors !!]");
    fireEvent.click(swatches);
    expect(onInsert).toHaveBeenCalledWith("scenario colors");
  });

  test("text colors and order drag their chips", () => {
    const onInsert = jest.fn();
    const view = strip(inputs, { onInsert });
    const chips = openCategory(view.container, "scenarios");
    expect(draggedText(chips.querySelector('[data-scenario-chip="order"]')!)).toBe("[!! scenario order !!]");
    fireEvent.click(chips.querySelector('[data-scenario-chip="text_colors"]')!);
    expect(onInsert).toHaveBeenCalledWith("scenario text_colors");
  });

  test("an input's chip names its circle and its scenario, and drags its color's chip", () => {
    const onInsert = jest.fn();
    const view = strip(inputs, { onInsert });
    const chips = openCategory(view.container, "scenarios");
    expect(inputChipsOf(chips)).toEqual([
      ["0", "Twice as tall", "#e76f51"],
      ["1", "Baseline", "#2a9d8f"],
      ["2", "Roof survey", "#8a8f98"],
    ]);
    const first = chips.querySelector('[data-scenario-input="0"]')!;
    expect(first.textContent).toBe("input_0Twice as tall");
    expect(first.getAttribute("data-tooltip")).toMatch(/^The color of Twice as tall, the scenario box input_0 comes from\. /);
    const drag = dragData();
    fireEvent.dragStart(first, drag);
    expect(drag.store.get(SCENARIO_REF_MIME)).toBe("scenario input_0");
    expect(drag.store.get("text/plain")).toBe("[!! scenario input_0 !!]");
    fireEvent.click(chips.querySelector('[data-scenario-input="2"]')!);
    expect(onInsert).toHaveBeenCalledWith("scenario input_2");
  });

  test("a screen reader reads each chip's words apart: an input's circle and its scenario, the swatches' names", () => {
    const view = strip(inputs);
    const chips = openCategory(view.container, "scenarios");
    expect(within(chips).getByRole("button", { name: "input_0, Twice as tall" }))
      .toBe(chips.querySelector('[data-scenario-input="0"]'));
    expect(within(chips).getByRole("button", { name: "input_2, Roof survey" }))
      .toBe(chips.querySelector('[data-scenario-input="2"]'));
    expect(within(chips).getByRole("button", { name: "colors: Baseline, Twice as tall, Roof survey" }))
      .toBe(chips.querySelector("[data-scenario-swatches]"));
  });

  test("two inputs from no box beside a boxed one show two greys, each the color its chip writes", () => {
    const wired = [free(0, "Survey A"), { ...free(1, "Shade"), scenario: BASE }, free(2, "Survey B")];
    const view = strip(wired);
    const chips = openCategory(view.container, "scenarios");
    const shown = inputChipsOf(chips);
    expect(shown.map(([slot]) => slot)).toEqual(["0", "1", "2"]);
    for (const [slot, , color] of shown) expect(color).toBe(written(`scenario input_${slot}`, wired));
    expect(shown[1][2]).toBe("#2a9d8f");
    expect(shown[0][2]).not.toBe(shown[2][2]);
    // And the swatches of the scale agree.
    const swatches = Array.from(chips.querySelectorAll("[data-scenario-swatches] [data-scenario-swatch]"))
      .map((s) => [s.getAttribute("data-scenario-swatch"), s.getAttribute("data-color")]);
    expect(swatches).toEqual([
      ["Baseline", "#2a9d8f"],
      ["Survey A", shown[0][2]],
      ["Survey B", shown[2][2]],
    ]);
  });
});

describe("Scenarios, in an Autark spec fed from boxes", () => {
  test("holds a chip per input alone, each the color its chip writes", () => {
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} language="json" onInsert={jest.fn()} />);
    expect(headerRow(view.container).map((entry) => entry.label)).toEqual(["Inputs 3", "Scenarios 3"]);
    const chips = openCategory(view.container, "scenarios");
    expect(chips.querySelector("[data-scenario-swatches]")).toBeNull();
    expect(chips.querySelector("[data-scenario-chip]")).toBeNull();
    const shown = inputChipsOf(chips);
    expect(shown.map(([slot, name]) => [slot, name])).toEqual([
      ["0", "Twice as tall"], ["1", "Baseline"], ["2", "Roof survey"],
    ]);
    for (const [slot, , color] of shown) expect(color).toBe(written(`scenario input_${slot}`, inputs));
    expect(draggedText(chips.querySelector('[data-scenario-input="1"]')!)).toBe("[!! scenario input_1 !!]");
  });
});

describe("a node fed from no box", () => {
  test("has no Scenarios category, in a Vega-Lite or an Autark spec", () => {
    const wired = [free(0, "Weekday"), free(1, "Weekend")];
    const chart = strip(wired);
    expect(headerRow(chart.container).map((entry) => entry.label)).toEqual(["Inputs 3"]);
    const map = render(<ReferenceStrip widgets={[]} inputs={wired} language="json" onInsert={jest.fn()} />);
    expect(headerRow(map.container).map((entry) => entry.label)).toEqual(["Inputs 2"]);
    // Each category opened in turn, no scenario chip shows in any.
    for (const view of [chart, map]) {
      eachCategory(view.container, (_category, chips) => {
        expect(chips.querySelector("[data-scenario-swatches], [data-scenario-input], [data-scenario-chip]")).toBeNull();
      });
    }
    expect(chipsOf(chart.container, "inputs")).not.toBeNull();
    expect(chipsOf(map.container, "inputs")).not.toBeNull();
    expect(document.querySelector("[data-scenario-swatches], [data-scenario-input], [data-scenario-chip]")).toBeNull();
  });
});

describe("the inputs tag, in Inputs", () => {
  test("drags the dataset's chip, and a click inserts it; its title names the chip", () => {
    const onInsert = jest.fn();
    const view = strip(inputs, { onInsert });
    const tag = openCategory(view.container, "inputs").querySelector("[data-inputs-tag]")!;
    expect(tag.getAttribute("draggable")).toBe("true");
    expect(tag.getAttribute("data-tooltip")).toContain("[!! inputs !!]");
    const drag = dragData();
    fireEvent.dragStart(tag, drag);
    expect(drag.store.get(INPUT_REF_MIME)).toBe("inputs");
    expect(drag.store.get("text/plain")).toBe("[!! inputs !!]");
    fireEvent.click(tag);
    expect(onInsert).toHaveBeenCalledWith("inputs");
  });

  test("sits after the input tags and opens to the stacked fields, Curio's three first, each with its dtype", () => {
    const onInsert = jest.fn();
    const view = strip(inputs, { onInsert });
    const chips = openCategory(view.container, "inputs");
    const tags = Array.from(chips.querySelectorAll("[data-input-tag], [data-inputs-tag]")).map((t) => t.textContent);
    expect(tags).toEqual(["input_0", "input_1", "input_2", "inputs"]);

    openInputs();
    const fields = Array.from(view.container.querySelectorAll("[data-inputs-fields] [data-inputs-field]"));
    // The union of the inputs' columns, a layer's geometry left out as the stacked rows leave it.
    expect(fields.map((f) => f.getAttribute("data-inputs-field"))).toEqual([
      "scenario_name", "scenario", "__input__", "segment", "sunlight", "shade",
    ]);
    const title = (name: string) => fields.find((f) => f.getAttribute("data-inputs-field") === name)!.getAttribute("data-tooltip");
    expect(title("sunlight")).toMatch(/^Field of inputs, float64\. /);
    expect(title("segment")).toMatch(/^Field of inputs, object\. /);
    expect(title("scenario_name")).toMatch(/^Field of inputs, text: /);
    expect(title("__input__")).toMatch(/^Field of inputs, number: /);

    const drag = dragData();
    fireEvent.dragStart(fields[4], drag);
    expect(drag.store.get(INPUT_REF_MIME)).toBe("inputs.sunlight");
    expect(drag.store.get("text/plain")).toBe("[!! inputs.sunlight !!]");
    fireEvent.click(fields[0]);
    expect(onInsert).toHaveBeenCalledWith("inputs.scenario_name");
  });

  test("its fields and the input tags show no swatch: the scenario chips are under Scenarios", () => {
    const view = strip(inputs);
    const chips = openCategory(view.container, "inputs");
    openInputs();
    expect(chips.querySelector("[data-scenario-swatches], [data-scenario-chip], [data-scenario-input]")).toBeNull();
    expect(chips.querySelector("[data-scenario-swatch]")).toBeNull();
  });

  test("opening Inputs asks for the columns of each input not read yet", () => {
    const onLoadColumns = jest.fn();
    const unread: InputScope[] = [inputs[0], { slot: 1, label: "Shade", scenario: BASE }];
    const view = render(
      <ReferenceStrip widgets={[]} inputs={unread} language="json" grammar="vega-lite"
        onInsert={jest.fn()} onLoadColumns={onLoadColumns} />,
    );
    expect(onLoadColumns).not.toHaveBeenCalled();
    openCategory(view.container, "inputs");
    // Asked for as Inputs opens, before the fields of inputs are.
    expect(onLoadColumns).toHaveBeenCalledWith(1);
    expect(onLoadColumns).not.toHaveBeenCalledWith(0);
    openInputs();
    expect(onLoadColumns).not.toHaveBeenCalledWith(0);
  });

  test("a Vega-Lite node with one input has it, since a spec reading inputs stacks one input too", () => {
    const onInsert = jest.fn();
    const one = strip([inputs[0]], { onInsert });
    expect(headerRow(one.container).map((entry) => entry.label)).toEqual(["Inputs 2", "Scenarios 4"]);
    const tag = openCategory(one.container, "inputs").querySelector("[data-inputs-tag]")!;
    const drag = dragData();
    fireEvent.dragStart(tag, drag);
    expect(drag.store.get("text/plain")).toBe("[!! inputs !!]");
    fireEvent.click(tag);
    expect(onInsert).toHaveBeenCalledWith("inputs");
    openInputs();
    const fields = Array.from(one.container.querySelectorAll("[data-inputs-fields] [data-inputs-field]"));
    expect(fields.map((f) => f.getAttribute("data-inputs-field"))).toEqual([
      "scenario_name", "scenario", "__input__", "segment", "sunlight",
    ]);
  });

  test("an Autark spec and code have none", () => {
    const map = render(<ReferenceStrip widgets={[]} inputs={inputs} language="json" onInsert={jest.fn()} />);
    openCategory(map.container, "inputs");
    expect(map.container.querySelector("[data-inputs-tag]")).toBeNull();
    map.unmount();
    const code = render(<ReferenceStrip widgets={[]} inputs={inputs} language="python" onInsert={jest.fn()} />);
    openCategory(code.container, "inputs");
    expect(code.container.querySelector("[data-inputs-tag]")).toBeNull();
    expect(headerRow(code.container).map((entry) => entry.label)).toEqual(["Inputs 3"]);
  });
});
