/**
 * The header above a node's code (#662): under Inputs, a tag per input, which
 * opens to every one of its columns, with no filter box; under Widgets, the
 * widget tags. Each tag drags or inserts its reference once its category is
 * open.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { INPUT_REF_MIME, WIDGET_REF_MIME } from "../../components/editing/widgets/monacoCodeReferences";
import type { InputScope } from "../../utils/references/codeReferences";
import { openCategory } from "../_support/stripCategories";

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

const inputs: InputScope[] = [
  { slot: 0, label: "Roads", columns: ["length", "lanes"], dtypes: { length: "float64" } },
  { slot: 1, label: "Parcels" },
  { slot: 2, label: "Trees", columns: null },
];

describe("input tags", () => {
  test("one tag per input, dragging its reference", () => {
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} onInsert={jest.fn()} />);
    openCategory(view.container, "inputs");
    const tags = view.container.querySelectorAll("[data-input-tag]");
    expect(Array.from(tags).map((t) => t.textContent)).toEqual(["input_0", "input_1", "input_2"]);
    expect(tags[0].getAttribute("title")).toMatch(/^From Roads\./);

    const drag = dragData();
    fireEvent.dragStart(tags[1], drag);
    expect(drag.store.get(INPUT_REF_MIME)).toBe("input_1");
    expect(drag.store.get("text/plain")).toBe("[!! input_1 !!]");
    expect(drag.store.has(WIDGET_REF_MIME)).toBe(false);
  });

  test("a click inserts the reference at the cursor", () => {
    const onInsert = jest.fn();
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} onInsert={onInsert} />);
    openCategory(view.container, "inputs");
    fireEvent.click(view.container.querySelector('[data-input-tag="0"]')!);
    expect(onInsert).toHaveBeenCalledWith("input_0");
  });

  test("opening an input lists its columns, which drag column references", () => {
    const onInsert = jest.fn();
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} onInsert={onInsert} />);
    openCategory(view.container, "inputs");
    fireEvent.click(screen.getByLabelText("Show the columns of input_0"));
    const columns = view.container.querySelectorAll('[data-input-columns="0"] [data-column-tag]');
    expect(Array.from(columns).map((c) => c.textContent)).toEqual(["length", "lanes"]);
    expect(columns[0].getAttribute("title")).toMatch(/float64/);

    const drag = dragData();
    fireEvent.dragStart(columns[0], drag);
    expect(drag.store.get(INPUT_REF_MIME)).toBe("input_0.length");
    fireEvent.click(columns[1]);
    expect(onInsert).toHaveBeenCalledWith("input_0.lanes");
  });

  test("columns not read yet are asked for; an input with nothing yet says to run its node", () => {
    const onLoadColumns = jest.fn();
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} onInsert={jest.fn()} onLoadColumns={onLoadColumns} />);
    openCategory(view.container, "inputs");
    fireEvent.click(screen.getByLabelText("Show the columns of input_1"));
    expect(onLoadColumns).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByLabelText("Show the columns of input_2"));
    expect(screen.getByText("Run the node that feeds this input to see its columns.")).toBeTruthy();
    expect(onLoadColumns).not.toHaveBeenCalledWith(2);
  });

  test("every column is listed, with no filter box, however many an input or its layers hold", () => {
    const columns = Array.from({ length: 20 }, (_, i) => `col_${i}`);
    const layered: InputScope = {
      slot: 1,
      label: "OSM",
      columns: [],
      layers: ["roads", "parks", "water"].map((name) => ({ name: `table_osm_${name}`, columns: columns.slice(0, 6) })),
    };
    const view = render(<ReferenceStrip widgets={[]} inputs={[{ slot: 0, columns }, layered]} onInsert={jest.fn()} />);
    openCategory(view.container, "inputs");
    fireEvent.click(screen.getByLabelText("Show the columns of input_0"));
    fireEvent.click(screen.getByLabelText("Show the columns of input_1"));
    expect(screen.queryAllByLabelText(/^Filter the columns of/)).toHaveLength(0);
    expect(screen.queryAllByPlaceholderText("Filter columns")).toHaveLength(0);
    expect(view.container.querySelector('input[type="search"]')).toBeNull();
    const shown = Array.from(view.container.querySelectorAll('[data-input-columns="0"] [data-column-tag]')).map((c) => c.textContent);
    expect(shown).toEqual(columns);
    expect(view.container.querySelectorAll('[data-input-columns="1"] [data-column-tag]')).toHaveLength(18);
  });
});

describe("an input carrying several layers", () => {
  const layered: InputScope[] = [{
    slot: 0,
    label: "OSM",
    columns: [],
    layers: [
      { name: "table_osm_roads", columns: ["highway"], dtypes: { highway: "str" } },
      { name: "table_osm_buildings", columns: ["height"] },
    ],
  }];

  test("it opens to a tag per layer, each with its columns, in code as in a spec", () => {
    const onInsert = jest.fn();
    const view = render(<ReferenceStrip widgets={[]} inputs={layered} onInsert={onInsert} />);
    openCategory(view.container, "inputs");
    fireEvent.click(screen.getByLabelText("Show the columns of input_0"));
    const layers = view.container.querySelectorAll("[data-layer-tag]");
    expect(Array.from(layers).map((t) => t.textContent)).toEqual(["table_osm_roads", "table_osm_buildings"]);

    const drag = dragData();
    fireEvent.dragStart(layers[0], drag);
    expect(drag.store.get(INPUT_REF_MIME)).toBe("input_0:table_osm_roads");
    expect(drag.store.get("text/plain")).toBe("[!! input_0:table_osm_roads !!]");

    const column = view.container.querySelector('[data-column-layer="table_osm_buildings"][data-column-tag="height"]')!;
    fireEvent.click(column);
    expect(onInsert).toHaveBeenCalledWith("input_0:table_osm_buildings.height");
    expect(view.container.querySelector('[data-column-tag="highway"]')!.getAttribute("title"))
      .toMatch(/^Column of layer table_osm_roads of input_0, str\. /);
  });

  test("a click on a layer tag inserts the layer chip; the input's tag stays the whole input", () => {
    const onInsert = jest.fn();
    const view = render(<ReferenceStrip widgets={[]} inputs={layered} onInsert={onInsert} />);
    openCategory(view.container, "inputs");
    fireEvent.click(screen.getByLabelText("Show the columns of input_0"));
    fireEvent.click(view.container.querySelector('[data-layer-tag="table_osm_buildings"]')!);
    expect(onInsert).toHaveBeenLastCalledWith("input_0:table_osm_buildings");
    fireEvent.click(view.container.querySelector('[data-input-tag="0"]')!);
    expect(onInsert).toHaveBeenLastCalledWith("input_0");
    expect(screen.queryByText(/This input carries the layers/)).toBeNull();
  });
});

describe("widget tags beside the inputs", () => {
  test("widget tags keep their strip and attributes", () => {
    const view = render(
      <ReferenceStrip
        widgets={[{ name: "factor", type: "number", default: 1 }]}
        inputs={inputs}
        onInsert={jest.fn()}
      />,
    );
    openCategory(view.container, "widgets");
    const tag = view.container.querySelector('[data-widget-strip] [data-widget-tag="factor"]')!;
    const drag = dragData();
    fireEvent.dragStart(tag, drag);
    expect(drag.store.get(WIDGET_REF_MIME)).toBe("factor");
  });

  test("nothing at all without inputs or widgets", () => {
    const view = render(<ReferenceStrip widgets={[]} inputs={[]} onInsert={jest.fn()} />);
    expect(view.container.innerHTML).toBe("");
  });
});
