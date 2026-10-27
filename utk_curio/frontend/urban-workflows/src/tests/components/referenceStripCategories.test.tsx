/**
 * The header above a node's code or spec (#662): one row of the categories of
 * chips the node can use, Inputs, Scenarios, Widgets and Selections, each
 * with its count and only when it has chips, all closed. A click opens a
 * category's chips under the row and closes the one open, so one category shows
 * its chips at a time. A category stays open for its node while the dataflow is
 * open, so the node's editor mounting again keeps it; another node's header
 * starts closed.
 *
 * The header reads the editor's language and grammar and the node's inputs,
 * never its code: code shows no Scenarios and no `inputs` tag.
 */
import React from "react";
import { fireEvent, render } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import type { InputScope } from "../../utils/references/codeReferences";
import type { SelectionTag } from "../../utils/references/selectionTags";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import { categoryButton, chipsOf, draggedText, headerRow, openCategory } from "../_support/stripCategories";

const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f", rank: 0 };
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51", rank: 1 };

const inputs: InputScope[] = [
  { slot: 0, label: "Shade", dataType: "dataframe", columns: ["segment", "sunlight"], scenario: BASE },
  { slot: 1, label: "Shade", dataType: "dataframe", columns: ["segment", "sunlight"], scenario: TALL },
];
const widgets: WidgetDef[] = [
  { name: "y", type: "text", default: "sunlight" },
  { name: "combine", type: "choice", default: "mean", options: { choices: ["mean", "sum"] } },
  { name: "y_title", type: "text", default: "" },
];
const selections: SelectionTag[] = [{ name: "picked", node: "scatter", column: "osm_id", ids: [101] }];

// Each test its own node, so no category it opens is open in another.
let made = 0;
const newNode = () => `strip-node-${(made += 1)}`;

function chart(nodeId: string, more: Record<string, unknown> = {}) {
  return (
    <ReferenceStrip
      nodeId={nodeId}
      widgets={widgets}
      inputs={inputs}
      selections={selections}
      language="json"
      grammar="vega-lite"
      onInsert={jest.fn()}
      {...more}
    />
  );
}

describe("the header's row", () => {
  test("lists each category with its count, all closed, and no chip until one opens", () => {
    const view = render(chart(newNode()));
    expect(headerRow(view.container)).toEqual([
      { category: "inputs", label: "Inputs 3", open: false },
      { category: "scenarios", label: "Scenarios 5", open: false },
      { category: "widgets", label: "Widgets 3", open: false },
      { category: "selections", label: "Selections 1", open: false },
    ]);
    for (const tag of [
      "[data-input-tag]", "[data-inputs-tag]", "[data-widget-tag]", "[data-selection-tag]",
      "[data-scenario-swatches]", "[data-scenario-input]", "[data-strip-chips]",
    ]) {
      expect(view.container.querySelector(tag)).toBeNull();
    }
  });

  test("a click opens a category's chips under the row, and a second click closes it", () => {
    const onInsert = jest.fn();
    const view = render(chart(newNode(), { onInsert }));
    const widgetsChips = openCategory(view.container, "widgets");
    expect(categoryButton(view.container, "widgets")!.getAttribute("aria-expanded")).toBe("true");
    const tags = Array.from(widgetsChips.querySelectorAll("[data-widget-tag]"));
    expect(tags.map((tag) => tag.textContent)).toEqual(["y", "combine", "y_title"]);
    expect(draggedText(tags[1])).toBe("[!! combine !!]");
    fireEvent.click(tags[0]);
    expect(onInsert).toHaveBeenCalledWith("y");
    // Under the row, not in it.
    const strip = view.container.querySelector("[data-widget-strip]")!;
    const row = categoryButton(view.container, "widgets")!.parentElement!;
    expect(row.contains(widgetsChips)).toBe(false);
    expect(strip.contains(widgetsChips)).toBe(true);
    // The others stay closed.
    expect(chipsOf(view.container, "inputs")).toBeNull();
    expect(view.container.querySelector("[data-input-tag]")).toBeNull();

    fireEvent.click(categoryButton(view.container, "widgets")!);
    expect(chipsOf(view.container, "widgets")).toBeNull();
    expect(view.container.querySelector("[data-widget-tag]")).toBeNull();
  });

  test("opening a category closes the one open, either way round, and only its chips show", () => {
    const view = render(chart(newNode()));
    const open = () => headerRow(view.container).filter((entry) => entry.open).map((entry) => entry.category);
    const shown = () =>
      Array.from(view.container.querySelectorAll("[data-strip-chips]")).map((group) => group.getAttribute("data-strip-chips"));

    openCategory(view.container, "inputs");
    openCategory(view.container, "widgets");
    expect(open()).toEqual(["widgets"]);
    expect(shown()).toEqual(["widgets"]);
    expect(view.container.querySelector("[data-input-tag]")).toBeNull();
    openCategory(view.container, "inputs");
    expect(open()).toEqual(["inputs"]);
    expect(shown()).toEqual(["inputs"]);
    expect(view.container.querySelector("[data-widget-tag]")).toBeNull();

    // Every other category the same way, each with its own chips.
    expect(openCategory(view.container, "selections").querySelector('[data-selection-tag="picked"]')!.textContent).toBe(
      "selection picked",
    );
    expect(open()).toEqual(["selections"]);
    expect(openCategory(view.container, "scenarios").querySelector("[data-scenario-swatches]")).not.toBeNull();
    expect(open()).toEqual(["scenarios"]);
    expect(shown()).toEqual(["scenarios"]);
  });

  test("a header with no node id, which keeps its own categories, opens one at a time too", () => {
    const view = render(
      <ReferenceStrip widgets={widgets} inputs={inputs} language="python" onInsert={jest.fn()} />,
    );
    const open = () => headerRow(view.container).filter((entry) => entry.open).map((entry) => entry.category);
    openCategory(view.container, "inputs");
    openCategory(view.container, "widgets");
    expect(open()).toEqual(["widgets"]);
    expect(view.container.querySelector("[data-input-tag]")).toBeNull();
    openCategory(view.container, "inputs");
    expect(open()).toEqual(["inputs"]);
    expect(view.container.querySelector("[data-widget-tag]")).toBeNull();
  });

  test("a category shows only when it has chips", () => {
    const view = render(
      <ReferenceStrip nodeId={newNode()} widgets={[]} inputs={[{ slot: 0, label: "Roads" }]} language="python" onInsert={jest.fn()} />,
    );
    expect(headerRow(view.container)).toEqual([{ category: "inputs", label: "Inputs 1", open: false }]);
  });

  test("a read-only node's categories open too, and its tags do not drag", () => {
    const view = render(chart(newNode(), { disabled: true }));
    const chips = openCategory(view.container, "widgets");
    expect(chips.querySelector('[data-widget-tag="y"]')!.getAttribute("draggable")).toBe("false");
  });
});

describe("a category stays open for its node", () => {
  test("when the node's editor mounts again, as after a tab switch or the notebook view", () => {
    const node = newNode();
    const first = render(chart(node));
    openCategory(first.container, "widgets");
    openCategory(first.container, "scenarios");
    first.unmount();

    const again = render(chart(node));
    expect(headerRow(again.container).filter((entry) => entry.open).map((entry) => entry.category)).toEqual([
      "scenarios",
    ]);
    expect(chipsOf(again.container, "scenarios")!.querySelector("[data-scenario-swatches]")).not.toBeNull();
    expect(chipsOf(again.container, "widgets")).toBeNull();
  });

  test("and another node's header starts closed", () => {
    const node = newNode();
    const first = render(chart(node));
    openCategory(first.container, "inputs");
    const other = render(chart(newNode()));
    expect(headerRow(other.container).every((entry) => !entry.open)).toBe(true);
    expect(headerRow(first.container)[0]).toEqual({ category: "inputs", label: "Inputs 3", open: true });
  });
});

describe("what the header reads", () => {
  test("code, Python or JavaScript, shows no Scenarios and no inputs tag, though its inputs come from boxes", () => {
    for (const language of ["python", "javascript"] as const) {
      const view = render(
        <ReferenceStrip nodeId={newNode()} widgets={widgets} inputs={inputs} language={language} onInsert={jest.fn()} />,
      );
      expect(headerRow(view.container).map((entry) => entry.label)).toEqual(["Inputs 2", "Widgets 3"]);
      const chips = openCategory(view.container, "inputs");
      expect(Array.from(chips.querySelectorAll("[data-input-tag]")).map((tag) => tag.textContent)).toEqual([
        "input_0", "input_1",
      ]);
      expect(view.container.querySelector("[data-inputs-tag]")).toBeNull();
      view.unmount();
    }
  });

  test("an Autark spec has no inputs tag, and its Scenarios a chip per input", () => {
    const view = render(chart(newNode(), { grammar: undefined }));
    expect(headerRow(view.container).map((entry) => entry.label)).toEqual([
      "Inputs 2", "Scenarios 2", "Widgets 3", "Selections 1",
    ]);
  });

  test("nothing at all when the node can use no chip", () => {
    const view = render(<ReferenceStrip nodeId={newNode()} widgets={[]} inputs={[]} language="json" grammar="vega-lite" onInsert={jest.fn()} />);
    expect(view.container.innerHTML).toBe("");
  });
});
