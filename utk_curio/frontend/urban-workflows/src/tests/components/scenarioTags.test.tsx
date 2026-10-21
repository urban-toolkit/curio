/**
 * The tags a chart's or a map's scenarios are written with (#662).
 *
 * - On a Vega-Lite node with an input, one or several, an `inputs` tag sits
 *   beside `input_0`, `input_1`, ... and drags the chip of the dataset that
 *   stacks them, `[!! inputs !!]`. It opens to the dataset's fields:
 *   `scenario_name`, `scenario` and `__input__`, then the union of the inputs'
 *   columns, each with its dtype in its title. A field drags its chip,
 *   `[!! inputs.sunlight !!]`, which writes its name.
 * - Its `scenario_name` field shows a swatch per scenario box, in the order the
 *   dataflow lists the boxes, then each input from no box in a grey of its own;
 *   with no input from a box, the names alone. The swatches
 *   are one chip, the scale of the scenarios' colors, `[!! scenario colors !!]`;
 *   two small tags beside them drag the names in that order,
 *   `[!! scenario order !!]`, and the colors in the shades a text mark reads
 *   in, `[!! scenario text_colors !!]`.
 * - An input whose feeding node is in a box shows that box's swatch on its tag,
 *   in a Vega-Lite or an Autark spec, which drags `[!! scenario input_1 !!]`,
 *   that box's color.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { INPUT_REF_MIME } from "../../components/editing/widgets/monacoCodeReferences";
import type { InputScope } from "../../utils/references/codeReferences";

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

const chartStrip = (onInsert = jest.fn(), more: Record<string, unknown> = {}) =>
  render(<ReferenceStrip widgets={[]} inputs={inputs} language="json" grammar="vega-lite" onInsert={onInsert} {...more} />);

const openInputs = () => fireEvent.click(screen.getByLabelText("Show the fields of inputs"));

describe("the inputs tag of a Vega-Lite node", () => {
  test("drags the dataset's chip, and a click inserts it; its title names the chip", () => {
    const onInsert = jest.fn();
    const view = chartStrip(onInsert);
    const tag = view.container.querySelector("[data-inputs-tag]")!;
    expect(tag.getAttribute("draggable")).toBe("true");
    expect(tag.getAttribute("title")).toContain("[!! inputs !!]");
    const drag = dragData();
    fireEvent.dragStart(tag, drag);
    expect(drag.store.get(INPUT_REF_MIME)).toBe("inputs");
    expect(drag.store.get("text/plain")).toBe("[!! inputs !!]");
    fireEvent.click(tag);
    expect(onInsert).toHaveBeenCalledWith("inputs");
  });

  test("sits beside the input tags and opens to the stacked fields, Curio's three first, each with its dtype", () => {
    const onInsert = jest.fn();
    const view = chartStrip(onInsert);
    const tags = Array.from(view.container.querySelectorAll("[data-input-tag], [data-inputs-tag]")).map((t) => t.textContent);
    expect(tags).toEqual(["input_0", "input_1", "input_2", "inputs"]);

    openInputs();
    const fields = Array.from(view.container.querySelectorAll("[data-inputs-fields] [data-inputs-field]"));
    // The union of the inputs' columns, a layer's geometry left out as the stacked rows leave it.
    expect(fields.map((f) => f.getAttribute("data-inputs-field"))).toEqual([
      "scenario_name", "scenario", "__input__", "segment", "sunlight", "shade",
    ]);
    const title = (name: string) => fields.find((f) => f.getAttribute("data-inputs-field") === name)!.getAttribute("title");
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

  test("scenario_name shows a swatch per box in the dataflow's order, an input from no box last in grey", () => {
    const view = chartStrip();
    openInputs();
    const swatches = Array.from(view.container.querySelectorAll("[data-scenario-swatches] [data-scenario-swatch]"));
    expect(swatches.map((s) => [s.getAttribute("data-scenario-swatch"), s.getAttribute("data-color")])).toEqual([
      ["Baseline", "#2a9d8f"],
      ["Twice as tall", "#e76f51"],
      ["Roof survey", "#8a8f98"],
    ]);
    expect(swatches.map((s) => s.textContent)).toEqual(["Baseline", "Twice as tall", "Roof survey"]);
    // On the scenario_name field, before the next field.
    const order = Array.from(view.container.querySelectorAll("[data-inputs-field], [data-scenario-swatches]"))
      .map((e) => e.getAttribute("data-inputs-field") ?? "swatches");
    expect(order.slice(0, 3)).toEqual(["scenario_name", "swatches", "scenario"]);
  });

  test("the swatches drag one chip, the scale of the scenarios' colors, and a click inserts it", () => {
    const onInsert = jest.fn();
    const view = chartStrip(onInsert);
    openInputs();
    const swatches = view.container.querySelector("[data-scenario-swatches]")!;
    expect(swatches.getAttribute("draggable")).toBe("true");
    const drag = dragData();
    fireEvent.dragStart(swatches, drag);
    expect(drag.store.get("text/plain")).toBe("[!! scenario colors !!]");
    fireEvent.click(swatches);
    expect(onInsert).toHaveBeenCalledWith("scenario colors");
  });

  test("two small tags beside them drag the names in order and the colors' text shades", () => {
    const onInsert = jest.fn();
    const view = chartStrip(onInsert);
    openInputs();
    const orderTag = view.container.querySelector('[data-scenario-chip="order"]')!;
    const shadesTag = view.container.querySelector('[data-scenario-chip="text_colors"]')!;
    const drag = dragData();
    fireEvent.dragStart(orderTag, drag);
    expect(drag.store.get("text/plain")).toBe("[!! scenario order !!]");
    fireEvent.click(shadesTag);
    expect(onInsert).toHaveBeenCalledWith("scenario text_colors");
  });

  test("opening it asks for the columns of each input not read yet", () => {
    const onLoadColumns = jest.fn();
    const unread: InputScope[] = [inputs[0], { slot: 1, label: "Shade", scenario: BASE }];
    render(
      <ReferenceStrip widgets={[]} inputs={unread} language="json" grammar="vega-lite"
        onInsert={jest.fn()} onLoadColumns={onLoadColumns} />,
    );
    openInputs();
    expect(onLoadColumns).toHaveBeenCalledWith(1);
    expect(onLoadColumns).not.toHaveBeenCalledWith(0);
  });
});

describe("the swatches of inputs from no box", () => {
  const free = (slot: number, name: string): InputScope => ({
    slot, label: name, dataType: "dataframe", columns: ["mode", "trips"], scenario: { name, color: "#8a8f98" },
  });
  const swatchesOf = (container: HTMLElement) =>
    Array.from(container.querySelectorAll("[data-scenario-swatches] [data-scenario-swatch]"))
      .map((s) => [s.getAttribute("data-scenario-swatch"), s.getAttribute("data-color")]);

  test("two inputs from no box beside a box each show a grey of their own, in circle order", () => {
    const wired = [free(0, "Survey A"), { ...free(1, "Shade"), scenario: BASE }, free(2, "Survey B")];
    const view = render(<ReferenceStrip widgets={[]} inputs={wired} language="json" grammar="vega-lite" onInsert={jest.fn()} />);
    openInputs();
    expect(swatchesOf(view.container)).toEqual([
      ["Baseline", "#2a9d8f"],
      ["Survey A", "#8a8f98"],
      ["Survey B", "#5b6068"],
    ]);
  });

  test("with no input from a box, the names show alone, since the chip writes them alone for the chart's own palette", () => {
    const view = render(
      <ReferenceStrip widgets={[]} inputs={[free(0, "Weekday"), free(1, "Weekend")]} language="json" grammar="vega-lite" onInsert={jest.fn()} />,
    );
    openInputs();
    expect(swatchesOf(view.container)).toEqual([["Weekday", null], ["Weekend", null]]);
    expect(view.container.querySelector("[data-scenario-swatches]")!.getAttribute("title")).toMatch(/palette/);
  });
});

describe("a swatch on an input's tag", () => {
  test("an input from a box shows its box's swatch, which drags the chip of its color; one from no box shows none", () => {
    const onInsert = jest.fn();
    const view = chartStrip(onInsert);
    const swatch = (slot: number) => view.container.querySelector(`[data-input-swatch="${slot}"]`);
    expect([swatch(0)?.getAttribute("data-color"), swatch(1)?.getAttribute("data-color"), swatch(2)]).toEqual([
      "#e76f51", "#2a9d8f", null,
    ]);
    expect(swatch(0)!.getAttribute("title")).toMatch(/^The color of Twice as tall, the scenario box input_0 comes from\. /);
    const drag = dragData();
    fireEvent.dragStart(swatch(0)!, drag);
    expect(drag.store.get("text/plain")).toBe("[!! scenario input_0 !!]");
    fireEvent.click(swatch(1)!);
    expect(onInsert).toHaveBeenCalledWith("scenario input_1");
  });

  test("an Autark map's inputs show their boxes' swatches too, and no inputs tag", () => {
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} language="json" onInsert={jest.fn()} />);
    expect(view.container.querySelector('[data-input-swatch="0"]')).not.toBeNull();
    expect(view.container.querySelector("[data-inputs-tag]")).toBeNull();
  });
});

describe("the inputs tag with one input, and where there is none", () => {
  test("a Vega-Lite node with one input has it, since a spec reading inputs stacks one input too", () => {
    const onInsert = jest.fn();
    const one = render(
      <ReferenceStrip widgets={[]} inputs={[inputs[0]]} language="json" grammar="vega-lite" onInsert={onInsert} />,
    );
    const tag = one.container.querySelector("[data-inputs-tag]")!;
    expect(tag).not.toBeNull();
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

  test("code, which reads no scenario chip and shows no swatch, has none", () => {
    const code = render(<ReferenceStrip widgets={[]} inputs={inputs} language="python" onInsert={jest.fn()} />);
    expect(code.container.querySelector("[data-inputs-tag]")).toBeNull();
    expect(code.container.querySelector("[data-input-swatch]")).toBeNull();
  });
});
