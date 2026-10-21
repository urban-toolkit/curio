/**
 * The lists an input's tag opens, in the header's Inputs (#662). The owner's
 * review of the header: with `input_0`'s columns open, `inputs` went to the end
 * of the header, below the columns, and read as one of them; and the arrow that
 * opens a list was a bare glyph.
 *
 * - In an open category its tags stay together on one row, in order: opening a
 *   list never moves them.
 * - A tag that opens a list (an input's columns or layers, the fields of
 *   `inputs`) is one pill: the tag, and on its right a chevron button pointing
 *   down when closed and up when open, with `aria-expanded` and a name and a
 *   title that say what it shows or hides. The open tag's pill shows as pressed.
 * - An open list is a panel below the tags row, headed by its tag's name
 *   ("input_0 columns", "input_0 layers", "inputs fields"). Several open lists
 *   stack in the tags' order, whatever order they were opened in.
 * - The categories' buttons point the same chevron down when closed and up when
 *   open.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import type { InputScope } from "../../utils/references/codeReferences";
import { categoryButton, openCategory } from "../_support/stripCategories";

const BASE = { scenario: "s-base", name: "Baseline", color: "#2a9d8f", rank: 0 };
const TALL = { scenario: "s-tall", name: "Twice as tall", color: "#e76f51", rank: 1 };

const shade = (slot: number, scenario = BASE): InputScope => ({
  slot,
  label: "Shade",
  dataType: "dataframe",
  columns: ["segment", "sunlight"],
  dtypes: { segment: "object", sunlight: "float64" },
  scenario,
});

const chart = (inputs: InputScope[]) =>
  render(<ReferenceStrip widgets={[]} inputs={inputs} language="json" grammar="vega-lite" onInsert={jest.fn()} />);

/** Each tag and each open list under Inputs, in the order the page holds them. */
const inOrder = (chips: HTMLElement) =>
  Array.from(chips.querySelectorAll("[data-input-tag], [data-inputs-tag], [data-input-columns], [data-inputs-fields]"))
    .map((el) => {
      if (el.hasAttribute("data-input-columns")) return `list of input_${el.getAttribute("data-input-columns")}`;
      if (el.hasAttribute("data-inputs-fields")) return "list of inputs";
      return `tag ${el.textContent}`;
    });

/** The name a list's panel is headed by. */
const headOf = (list: Element) => list.querySelector("[data-list-name]")?.textContent;

const chevronOf = (button: Element) => button.querySelector("[data-chevron]")?.getAttribute("data-chevron");

describe("an open list leaves the tags where they are", () => {
  test("with input_0's columns open, inputs is still the next tag after input_0, and the columns are in a panel below the row", () => {
    const view = chart([shade(0)]);
    const chips = openCategory(view.container, "inputs");
    fireEvent.click(screen.getByRole("button", { name: "Show the columns of input_0" }));

    expect(inOrder(chips)).toEqual(["tag input_0", "tag inputs", "list of input_0"]);
    const row = chips.querySelector('[data-input-tag="0"]')!.closest("[data-strip-tags]");
    expect(row).not.toBeNull();
    const list = chips.querySelector('[data-input-columns="0"]')!;
    expect(row!.contains(chips.querySelector("[data-inputs-tag]"))).toBe(true);
    expect(row!.contains(list)).toBe(false);
    expect(row!.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(headOf(list)).toBe("input_0 columns");
    expect(Array.from(list.querySelectorAll("[data-column-tag]")).map((tag) => tag.textContent)).toEqual([
      "segment", "sunlight",
    ]);
  });

  test("several open lists stack below the row in the tags' order, whatever order they opened in", () => {
    const view = chart([shade(0), shade(1, TALL)]);
    const chips = openCategory(view.container, "inputs");
    fireEvent.click(screen.getByRole("button", { name: "Show the fields of inputs" }));
    fireEvent.click(screen.getByRole("button", { name: "Show the columns of input_1" }));
    fireEvent.click(screen.getByRole("button", { name: "Show the columns of input_0" }));

    expect(inOrder(chips)).toEqual([
      "tag input_0", "tag input_1", "tag inputs", "list of input_0", "list of input_1", "list of inputs",
    ]);
    const lists = Array.from(chips.querySelectorAll("[data-input-columns], [data-inputs-fields]"));
    expect(lists.map(headOf)).toEqual(["input_0 columns", "input_1 columns", "inputs fields"]);
    const row = chips.querySelector("[data-strip-tags]")!;
    for (const list of lists) expect(row.contains(list)).toBe(false);
  });

  test("an input that carries layers opens to a panel of its layers, each followed by its columns", () => {
    const layered: InputScope = {
      slot: 0,
      label: "OSM",
      columns: [],
      layers: [
        { name: "table_osm_roads", columns: ["highway"] },
        { name: "table_osm_buildings", columns: ["height"] },
      ],
    };
    const view = render(<ReferenceStrip widgets={[]} inputs={[layered]} language="json" onInsert={jest.fn()} />);
    const chips = openCategory(view.container, "inputs");
    fireEvent.click(screen.getByRole("button", { name: "Show the columns of input_0" }));
    const list = chips.querySelector('[data-input-columns="0"]')!;
    expect(chips.querySelector("[data-strip-tags]")!.contains(list)).toBe(false);
    expect(headOf(list)).toBe("input_0 layers");
    expect(Array.from(list.querySelectorAll("[data-layer-tag], [data-column-tag]")).map((tag) => tag.textContent)).toEqual([
      "table_osm_roads", "highway", "table_osm_buildings", "height",
    ]);
  });

  test("closing a list takes its panel away and leaves the row as it was", () => {
    const view = chart([shade(0)]);
    const chips = openCategory(view.container, "inputs");
    fireEvent.click(screen.getByRole("button", { name: "Show the columns of input_0" }));
    const button = screen.getByRole("button", { name: "Hide the columns of input_0" });
    fireEvent.click(button);
    expect(inOrder(chips)).toEqual(["tag input_0", "tag inputs"]);
    expect([button.getAttribute("aria-expanded"), chevronOf(button)]).toEqual(["false", "down"]);
  });
});

describe("each expander is a chevron button", () => {
  test("attached to its tag as one pill, pointing down closed and up open, with aria-expanded, a name and a title", () => {
    const view = chart([shade(0)]);
    const chips = openCategory(view.container, "inputs");
    for (const [what, tagSelector] of [
      ["the columns of input_0", '[data-input-tag="0"]'],
      ["the fields of inputs", "[data-inputs-tag]"],
    ] as const) {
      const button = screen.getByRole("button", { name: `Show ${what}` });
      const tag = chips.querySelector(tagSelector)!;
      const pill = tag.closest("[data-tag-pill]");
      expect(pill).not.toBeNull();
      expect(pill!.contains(button)).toBe(true);
      expect(tag.nextElementSibling).toBe(button);
      expect([button.getAttribute("aria-expanded"), button.getAttribute("title"), chevronOf(button)]).toEqual([
        "false", `Show ${what}`, "down",
      ]);
      expect(pill!.getAttribute("data-open")).toBe("false");

      fireEvent.click(button);
      const open = screen.getByRole("button", { name: `Hide ${what}` });
      expect(open).toBe(button);
      expect([open.getAttribute("aria-expanded"), open.getAttribute("title"), chevronOf(open)]).toEqual([
        "true", `Hide ${what}`, "up",
      ]);
      // The open tag shows as pressed.
      expect(pill!.getAttribute("data-open")).toBe("true");
    }
  });

  test("a category's button points the same chevron down when closed and up when open", () => {
    const view = chart([shade(0)]);
    const button = categoryButton(view.container, "inputs")!;
    expect([button.getAttribute("aria-expanded"), chevronOf(button)]).toEqual(["false", "down"]);
    fireEvent.click(button);
    expect([button.getAttribute("aria-expanded"), chevronOf(button)]).toEqual(["true", "up"]);
  });
});
