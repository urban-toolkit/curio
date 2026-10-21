/**
 * The Inputs of a node's header, one input per line (#662). In the owner's
 * review of the header, opening `input_0`'s columns pushed `inputs` to the end
 * of the header, below the columns, where it read as one of them, and the bare
 * arrow that opens a list did not read as a button. On the mockups the owner
 * picked one input per line, with no filter:
 *
 * - Inputs opens to a line per input (`data-input-line`), in circle order,
 *   then, in a Vega-Lite spec, the line of `inputs` (`data-inputs-line`), the
 *   dataset that stacks them. Code and an Autark spec have no `inputs` line.
 * - A line holds an expander, the input's tag, and what the input holds
 *   (`data-input-about`): "from Existing: 5 columns", after the box the input
 *   comes from, else after the type of the node that feeds it; its layers, or
 *   a tuple's values; "input_0 and input_1, stacked: 8 fields" for `inputs`.
 *   Until an input's columns are read its line says only where it comes from.
 *   Opening Inputs reads them, so the counts show at a glance.
 * - An expander is a button with `aria-expanded`, a name and a title, and its
 *   chevron points right closed and down open. A category's chevron points
 *   down closed and up open (`data-chevron`).
 * - An open list comes right under its own line, before the next line, so
 *   `inputs` keeps a line of its own. Several can be open at once, and each
 *   stays open for its node while the dataflow is open, as the categories do.
 * - A layered input's list is a line per layer (`data-layer-line`): its layer
 *   tag, then that layer's columns. A tuple's list says how to read its values
 *   in code.
 *
 * jsdom has no layout: where the lines and the lists land on screen is checked
 * by the e2e tests test_input_lines_e2e.py and test_input_lines_autark_e2e.py.
 */
import React from "react";
import { act, fireEvent, render, within } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { closeEveryCategory } from "../../components/editing/widgets/stripCategories";
import type { InputScope } from "../../utils/references/codeReferences";
import { categoryButton, chipsOf, headerRow, openCategory, type StripCategory } from "../_support/stripCategories";

const EXISTING = { scenario: "s-existing", name: "Existing", color: "#2a9d8f", rank: 0 };
const TOWERS = { scenario: "s-towers", name: "Towers removed", color: "#e76f51", rank: 1 };
const STATS = ["mean", "median", "min", "max", "count"];

/** A table of shadow statistics from the box *box*, as Chicago Loop's chart gets it. */
const stats = (slot: number, box = EXISTING): InputScope => ({
  slot,
  label: "Python Computation",
  dataType: "dataframe",
  columns: STATS,
  dtypes: { mean: "float64", median: "float64", min: "float64", max: "float64", count: "int64" },
  scenario: box,
});

/** The ZIP codes, from a node in no box: its scenario label carries the node's
 * own title, and its label the type of the node. */
const zips = (slot: number): InputScope => ({
  slot,
  label: "Data Loading",
  dataType: "geodataframe",
  columns: ["zip"],
  dtypes: { zip: "object" },
  scenario: { name: "ZIP codes", color: "#8a8f98" },
});

const chart = (inputs: InputScope[], more: Record<string, unknown> = {}) => (
  <ReferenceStrip widgets={[]} inputs={inputs} language="json" grammar="vega-lite" onInsert={jest.fn()} {...more} />
);

/** Each line under Inputs, in the order the page holds them, with what it says its input holds. */
const linesOf = (chips: Element) =>
  Array.from(chips.querySelectorAll("[data-input-line], [data-inputs-line]")).map((line) => [
    line.hasAttribute("data-inputs-line") ? "inputs" : `input_${line.getAttribute("data-input-line")}`,
    line.querySelector("[data-input-about]")?.textContent ?? null,
  ]);

/** What one line holds, in its order: its expander, its tag, and what its input holds. */
const partsOf = (line: Element) =>
  Array.from(line.querySelectorAll("button, [data-input-tag], [data-inputs-tag], [data-input-about]")).map((el) =>
    el.tagName === "BUTTON" ? "expander" : el.hasAttribute("data-input-about") ? "about" : `tag ${el.textContent}`,
  );

/** Each line and each open list under Inputs, in the order the page holds them. */
const inOrder = (chips: Element) =>
  Array.from(
    chips.querySelectorAll("[data-input-line], [data-inputs-line], [data-input-columns], [data-inputs-fields]"),
  ).map((el) => {
    if (el.hasAttribute("data-input-columns")) return `list of input_${el.getAttribute("data-input-columns")}`;
    if (el.hasAttribute("data-inputs-fields")) return "list of inputs";
    if (el.hasAttribute("data-inputs-line")) return "line of inputs";
    return `line of input_${el.getAttribute("data-input-line")}`;
  });

/** Where the chevron drawn in *el* points: right, down or up. */
const chevronOf = (el: Element) => el.querySelector("svg[data-chevron]")?.getAttribute("data-chevron");

describe("each input is a line of its own", () => {
  test("a line per input in circle order, each its expander, its tag and what it holds, then the line of inputs", () => {
    const view = render(chart([stats(0), stats(1, TOWERS), zips(2)]));
    const chips = openCategory(view.container, "inputs");
    // An input from a box is named after its box; one from no box, after the
    // type of the node that feeds it.
    expect(linesOf(chips)).toEqual([
      ["input_0", "from Existing: 5 columns"],
      ["input_1", "from Towers removed: 5 columns"],
      ["input_2", "from Data Loading: 1 column"],
      ["inputs", "input_0, input_1 and input_2, stacked: 9 fields"],
    ]);
    const lines = Array.from(chips.querySelectorAll("[data-input-line], [data-inputs-line]"));
    expect(lines.map(partsOf)).toEqual([
      ["expander", "tag input_0", "about"],
      ["expander", "tag input_1", "about"],
      ["expander", "tag input_2", "about"],
      ["expander", "tag inputs", "about"],
    ]);
  });

  test("the line of inputs names the inputs it stacks, and counts its fields", () => {
    for (const [wired, about] of [
      [[stats(0)], "input_0, stacked: 8 fields"],
      [[stats(0), stats(1, TOWERS)], "input_0 and input_1, stacked: 8 fields"],
    ] as const) {
      const view = render(chart([...wired]));
      expect(linesOf(openCategory(view.container, "inputs")).at(-1)).toEqual(["inputs", about]);
      view.unmount();
    }
  });

  test("code and an Autark spec have a line per input and no line of inputs", () => {
    // A spec of no grammar named here is an Autark spec.
    for (const language of ["python", "javascript", "json"] as const) {
      const view = render(
        <ReferenceStrip widgets={[]} inputs={[stats(0), stats(1, TOWERS)]} language={language} onInsert={jest.fn()} />,
      );
      const chips = openCategory(view.container, "inputs");
      expect(linesOf(chips)).toEqual([
        ["input_0", "from Existing: 5 columns"],
        ["input_1", "from Towers removed: 5 columns"],
      ]);
      expect(chips.querySelector("[data-inputs-line], [data-inputs-tag]")).toBeNull();
      view.unmount();
    }
  });
});

describe("each expander is a chevron button", () => {
  test("a line's: a button with aria-expanded, a name and a title, its chevron right closed and down open", () => {
    const view = render(chart([stats(0), stats(1, TOWERS)]));
    const chips = openCategory(view.container, "inputs");
    for (const [line, what] of [
      ['[data-input-line="0"]', "the columns of input_0"],
      ['[data-input-line="1"]', "the columns of input_1"],
      ["[data-inputs-line]", "the fields of inputs"],
    ] as const) {
      const button = within(chips).getByRole("button", { name: `Show ${what}` });
      expect(button.closest(line)).not.toBeNull();
      expect([
        button.tagName, button.getAttribute("type"), button.getAttribute("aria-expanded"),
        button.getAttribute("title"), chevronOf(button),
      ]).toEqual(["BUTTON", "button", "false", `Show ${what}`, "right"]);

      fireEvent.click(button);
      const open = within(chips).getByRole("button", { name: `Hide ${what}` });
      expect(open).toBe(button);
      expect([open.getAttribute("aria-expanded"), open.getAttribute("title"), chevronOf(open)]).toEqual([
        "true", `Hide ${what}`, "down",
      ]);
    }
  });

  test("a category's points down closed and up open", () => {
    const view = render(
      chart([stats(0), stats(1, TOWERS)], {
        widgets: [{ name: "y", type: "text", default: "mean" }],
        shared: [{ name: "season", type: "text", default: "summer" }],
      }),
    );
    const row = headerRow(view.container);
    expect(row.map((entry) => entry.category)).toEqual(["inputs", "scenarios", "widgets", "shared"]);
    for (const entry of row) {
      const button = categoryButton(view.container, entry.category as StripCategory)!;
      expect([button.getAttribute("aria-expanded"), chevronOf(button)]).toEqual(["false", "down"]);
      fireEvent.click(button);
      expect([button.getAttribute("aria-expanded"), chevronOf(button)]).toEqual(["true", "up"]);
    }
  });
});

describe("an open list comes right under its own line", () => {
  test("input_0's, before the next line, and inputs keeps a line of its own after it", () => {
    const view = render(chart([stats(0), stats(1, TOWERS)]));
    const chips = openCategory(view.container, "inputs");
    fireEvent.click(within(chips).getByRole("button", { name: "Show the columns of input_0" }));
    expect(inOrder(chips)).toEqual(["line of input_0", "list of input_0", "line of input_1", "line of inputs"]);

    // Under its line, not in it, and holding input_0's columns alone.
    const list = chips.querySelector('[data-input-columns="0"]')!;
    const lines = Array.from(chips.querySelectorAll("[data-input-line], [data-inputs-line]"));
    expect(lines.filter((line) => line.contains(list))).toEqual([]);
    expect(list.querySelector("[data-input-line], [data-inputs-line], [data-input-tag], [data-inputs-tag]")).toBeNull();
    expect(Array.from(list.querySelectorAll("[data-column-tag]")).map((tag) => tag.textContent)).toEqual(STATS);
    // The inputs tag is still on a line of its own, after the list.
    const inputsTag = chips.querySelector("[data-inputs-tag]")!;
    expect(inputsTag.closest("[data-inputs-line]")).not.toBeNull();
    expect(list.compareDocumentPosition(inputsTag) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Closed, the list is gone and the lines are as they were.
    fireEvent.click(within(chips).getByRole("button", { name: "Hide the columns of input_0" }));
    expect(inOrder(chips)).toEqual(["line of input_0", "line of input_1", "line of inputs"]);
  });

  test("several open at once, each under its own line, whatever order they opened in", () => {
    const view = render(chart([stats(0), stats(1, TOWERS)]));
    const chips = openCategory(view.container, "inputs");
    for (const name of ["Show the fields of inputs", "Show the columns of input_1", "Show the columns of input_0"]) {
      fireEvent.click(within(chips).getByRole("button", { name }));
    }
    expect(inOrder(chips)).toEqual([
      "line of input_0", "list of input_0", "line of input_1", "list of input_1", "line of inputs", "list of inputs",
    ]);
    const tagsIn = (list: string, tag: string) =>
      Array.from(chips.querySelector(list)!.querySelectorAll(tag)).map((el) => el.textContent);
    expect(tagsIn('[data-input-columns="1"]', "[data-column-tag]")).toEqual(STATS);
    expect(tagsIn("[data-inputs-fields]", "[data-inputs-field]")).toEqual([
      "scenario_name", "scenario", "__input__", ...STATS,
    ]);
  });
});

describe("a layered input", () => {
  test("lists a line per layer, in order, each its layer tag and then only its own columns", () => {
    const osm: InputScope = {
      slot: 0,
      label: "Autark",
      columns: [],
      layers: [
        { name: "table_osm_roads", columns: ["osm_id", "highway", "name"], dtypes: { highway: "str" } },
        { name: "table_osm_buildings", columns: ["osm_id", "height"] },
        { name: "table_osm_water", columns: [] },
      ],
    };
    const view = render(<ReferenceStrip widgets={[]} inputs={[osm]} language="json" onInsert={jest.fn()} />);
    const chips = openCategory(view.container, "inputs");
    expect(linesOf(chips)).toEqual([["input_0", "from Autark: 3 layers"]]);

    fireEvent.click(within(chips).getByRole("button", { name: "Show the columns of input_0" }));
    const list = chips.querySelector('[data-input-columns="0"]')!;
    const layerLines = Array.from(list.querySelectorAll("[data-layer-line]"));
    expect(layerLines.map((line) => line.getAttribute("data-layer-line"))).toEqual([
      "table_osm_roads", "table_osm_buildings", "table_osm_water",
    ]);
    // Each line holds its layer's tag first, then that layer's columns, each
    // naming its layer.
    const tagsOf = (line: Element) =>
      Array.from(line.querySelectorAll("[data-layer-tag], [data-column-tag]")).map((tag) =>
        tag.hasAttribute("data-layer-tag")
          ? `layer ${tag.textContent}`
          : `${tag.getAttribute("data-column-layer")}.${tag.textContent}`,
      );
    expect(layerLines.map(tagsOf)).toEqual([
      ["layer table_osm_roads", "table_osm_roads.osm_id", "table_osm_roads.highway", "table_osm_roads.name"],
      ["layer table_osm_buildings", "table_osm_buildings.osm_id", "table_osm_buildings.height"],
      ["layer table_osm_water"],
    ]);
    // No tag of the list is outside a layer's line.
    const loose = Array.from(list.querySelectorAll("[data-layer-tag], [data-column-tag]"))
      .filter((tag) => !tag.closest("[data-layer-line]"));
    expect(loose).toEqual([]);
  });
});

describe("a tuple", () => {
  test("says on its line it holds 2 values, and its list how to read them in code", () => {
    const stations: InputScope = {
      slot: 0, label: "Data Loading", dataType: "geodataframe", columns: ["sensor", "name", "lat", "lon"],
    };
    // Summarize's `return means, peaks`: two tables with no names, so no
    // layers, read as one tuple. Its read counts its values (`tuple`).
    const summary = {
      slot: 1, label: "Python Computation", dataType: "outputs", columns: [], dtypes: {}, layers: [], tuple: 2,
    } as InputScope;
    const view = render(<ReferenceStrip widgets={[]} inputs={[stations, summary]} language="python" onInsert={jest.fn()} />);
    const chips = openCategory(view.container, "inputs");
    expect(linesOf(chips)).toEqual([
      ["input_0", "from Data Loading: 4 columns"],
      ["input_1", "from Python Computation: 2 values, a tuple"],
    ]);

    fireEvent.click(within(chips).getByRole("button", { name: "Show the columns of input_1" }));
    const list = chips.querySelector('[data-input-columns="1"]')!;
    expect(list.textContent).toContain("Read them in code as input_1[0] and input_1[1].");
    expect(list.textContent).not.toContain("This input has no columns.");
    expect(list.querySelector("[data-column-tag], [data-layer-tag], [data-layer-line]")).toBeNull();
  });
});

describe("counts at a glance", () => {
  test("opening Inputs asks for the columns of every input not read yet, with no list open, and not for one with nothing yet", () => {
    const onLoadColumns = jest.fn();
    const wired: InputScope[] = [
      { slot: 0, label: "Data Loading", dataType: "dataframe", columns: ["zip"] },
      // Not read yet.
      { slot: 1, label: "Data Loading" },
      // Nothing has arrived yet.
      { slot: 2, label: "Python Computation", columns: null },
    ];
    const view = render(chart(wired, { onLoadColumns }));
    expect(onLoadColumns).not.toHaveBeenCalled();
    const chips = openCategory(view.container, "inputs");
    expect(chips.querySelector("[data-input-columns], [data-inputs-fields]")).toBeNull();
    expect(onLoadColumns).toHaveBeenCalledWith(1);
    expect(onLoadColumns).not.toHaveBeenCalledWith(0);
    expect(onLoadColumns).not.toHaveBeenCalledWith(2);
  });

  test("a line says where its input comes from until its columns are read, and its count once they are", () => {
    const unread: InputScope[] = [
      { slot: 0, label: "Data Pool" },
      { slot: 1, label: "Data Pool", columns: null },
    ];
    const view = render(chart(unread));
    expect(linesOf(openCategory(view.container, "inputs")).slice(0, 2)).toEqual([
      ["input_0", "from Data Pool"],
      ["input_1", "from Data Pool"],
    ]);

    const read = unread.map((input) => ({
      ...input, dataType: "dataframe", columns: ["neighborhood_name", "accessibility"], dtypes: {},
    }));
    view.rerender(chart(read));
    expect(linesOf(chipsOf(view.container, "inputs")!)).toEqual([
      ["input_0", "from Data Pool: 2 columns"],
      ["input_1", "from Data Pool: 2 columns"],
      ["inputs", "input_0 and input_1, stacked: 5 fields"],
    ]);
  });
});

describe("an open list stays open for its node", () => {
  test("when the node's editor mounts again, as after a run or a tab switch, and closes when another dataflow opens", () => {
    const strip = (nodeId: string) => chart([stats(0), stats(1, TOWERS)], { nodeId });
    const first = render(strip("lists-node"));
    const firstChips = openCategory(first.container, "inputs");
    fireEvent.click(within(firstChips).getByRole("button", { name: "Show the columns of input_1" }));
    fireEvent.click(within(firstChips).getByRole("button", { name: "Show the fields of inputs" }));
    first.unmount();

    const again = render(strip("lists-node"));
    const chips = chipsOf(again.container, "inputs");
    expect(chips).not.toBeNull();
    expect(inOrder(chips!)).toEqual([
      "line of input_0", "line of input_1", "list of input_1", "line of inputs", "list of inputs",
    ]);
    expect(within(chips!).getByRole("button", { name: "Hide the columns of input_1" }).getAttribute("aria-expanded"))
      .toBe("true");

    // Another node's lists start closed.
    const other = render(strip("another-lists-node"));
    expect(inOrder(openCategory(other.container, "inputs"))).toEqual([
      "line of input_0", "line of input_1", "line of inputs",
    ]);
    other.unmount();

    // ProjectLoader closes every category when another dataflow opens, and the
    // lists close with them.
    act(() => closeEveryCategory());
    expect(chipsOf(again.container, "inputs")).toBeNull();
    expect(inOrder(openCategory(again.container, "inputs"))).toEqual([
      "line of input_0", "line of input_1", "line of inputs",
    ]);
  });
});
