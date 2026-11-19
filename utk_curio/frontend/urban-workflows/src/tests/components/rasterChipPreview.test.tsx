/**
 * What a chip's hover and the header's lines say of a raster (#662's chips):
 * read as a table is, from the one read the header makes, then shown in the
 * one Curio tooltip's preview (components/editing/widgets/ChipPreview), never
 * in a `title`.
 *
 * - A raster on its own, or a layer chip that names one: its size in cells,
 *   its bands and its CRS, as a frame's preview gives its rows, its columns
 *   and its CRS; then its bands by their labels.
 * - An input of layers lists a raster layer as a line among its tables, and a
 *   tuple its raster as one of its values.
 * - The header says a raster is one where a table would say its columns.
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import React from "react";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { ChipPreview } from "../../components/editing/widgets/ChipPreview";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import type { CodeLanguage, InputScope, ReferenceScope } from "../../utils/references/codeReferences";
import {
  inputScopeFor,
  readInputColumns,
  readInputPreview,
  type InputSource,
} from "../../utils/references/inputScope";
import { openCategory } from "../_support/stripCategories";
import {
  PARK_ACCESS,
  PYTHON_RASTER_REF,
  RASTER_READS,
  SERVER_LAYERS_REF,
} from "../_support/rasterInputFixtures";

afterEach(cleanup);

beforeEach(() => {
  mockFetchPreviewData.mockReset();
  mockFetchPreviewData.mockImplementation(async (path: string) => {
    if (!(path in RASTER_READS)) throw new Error(`no artifact ${path}`);
    return RASTER_READS[path];
  });
});

const textOf = (el: Element | null) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const linesOf = (root: Element) => Array.from(root.querySelectorAll("[data-preview-line]")).map((line) => textOf(line));
const headOf = (root: Element) => textOf(root.querySelector("[data-preview-head]"));
const footOf = (root: Element) => Array.from(root.querySelectorAll("[data-preview-foot]")).map((foot) => textOf(foot));
const captionsOf = (root: Element) => Array.from(root.querySelectorAll("table caption")).map((caption) => textOf(caption));

const DATA_NODE: InputSource = { title: "Park access", type: "Autark", status: "done" };
const PYTHON_NODE: InputSource = { title: "Parks and elevation", type: "Python Computation", status: "done" };

/** The scope of the node that *value* feeds on its circle 0, read as the editor reads it. */
async function scopeOf(value: unknown): Promise<ReferenceScope> {
  const columns = await readInputColumns(value);
  const edges = [{ id: "e0", source: "data", target: "next", sourceHandle: "out", targetHandle: "in" }];
  const nodes = [{ id: "data", data: { title: "Park access" } }];
  const inputs = inputScopeFor("next", edges, nodes, () => value, (data) => data.title ?? null, () => columns);
  return { widgets: [], inputs };
}

/** The hover of the chip *inner* over *value*, which node *source* feeds on circle 0. */
async function hover(inner: string, value: unknown, source: InputSource, language: CodeLanguage = "json") {
  const scope = await scopeOf(value);
  const preview = await readInputPreview(value);
  const { container } = render(
    <ChipPreview inner={inner} scope={scope} language={language} data={{ inputs: { 0: { source, preview } } }} />,
  );
  return container.firstElementChild as HTMLElement;
}

describe("a chip's hover", () => {
  test("a layer chip naming example 34's heatmap: its size, its band and its CRS", async () => {
    const root = await hover("input_0:park_access", SERVER_LAYERS_REF, DATA_NODE);
    expect(root.getAttribute("data-chip-preview")).toBe("layer");
    expect(headOf(root)).toBe("park_access layer of input_0");
    expect(linesOf(root)).toEqual(["3 by 2 cells · 1 band · Raster, EPSG:3395", "Band: count_tip_parks"]);
    expect(root.querySelector("table")).toBeNull();
    expect(footOf(root)).toEqual([]);
  });

  test("an input of a table and a raster: the table's rows, then a line for the raster", async () => {
    const root = await hover("input_0", { path: "python-pair", dataType: "dict" }, PYTHON_NODE, "python");
    expect(headOf(root)).toBe("input_0 from Parks and elevation · a Python Computation node");
    expect(linesOf(root)).toEqual(["2 layers", "elevation · raster, 40 by 30 cells, 2 bands"]);
    expect(captionsOf(root)).toEqual(["tip_parks · 1 feature, Point"]);
  });

  test("a raster on its own: its size, its bands by their labels and its CRS", async () => {
    const root = await hover("input_0", PYTHON_RASTER_REF, PYTHON_NODE, "python");
    expect(root.getAttribute("data-chip-preview")).toBe("input");
    expect(linesOf(root)).toEqual(["40 by 30 cells · 2 bands · Raster, EPSG:3395", "Bands: elevation_m, band_2"]);
    expect(footOf(root)).toEqual([]);
  });

  test("a tuple's raster is one of its values, as a line of its own", async () => {
    const root = await hover("input_0", { path: "python-tuple", dataType: "outputs" }, PYTHON_NODE, "python");
    expect(linesOf(root)).toEqual([
      "A tuple of 2 values. Read them in code as input_0[0] and input_0[1].",
      "input_0[1] · raster, 40 by 30 cells, 2 bands",
    ]);
    expect(captionsOf(root)).toEqual(["input_0[0] · 1 row × 2 columns"]);
  });

  test("a raster of many bands lists its first 5 and says how many it has", async () => {
    const properties: Record<string, unknown> = {
      ...PARK_ACCESS.data.features[0].properties,
      bands: ["sum", "avg", "min", "max", "count", "weighted", "avg_norm"].map((fn, i) => ({ id: `band_${i + 1}`, label: `${fn}_tip_parks` })),
    };
    const raster = {
      ...PARK_ACCESS,
      data: { ...PARK_ACCESS.data, features: [{ ...PARK_ACCESS.data.features[0], properties }] },
    };
    const root = await hover("input_0", raster, DATA_NODE);
    expect(linesOf(root)).toEqual([
      "3 by 2 cells · 7 bands · Raster, EPSG:3395",
      "Bands: sum_tip_parks, avg_tip_parks, min_tip_parks, max_tip_parks, count_tip_parks",
    ]);
    expect(footOf(root)).toEqual(["first 5 of 7 bands"]);
  });
});

describe("the header's lines", () => {
  test("an input of layers lists its heatmap among them, saying it is a raster where a table lists its columns", async () => {
    const { inputs } = await scopeOf(SERVER_LAYERS_REF);
    const view = render(<ReferenceStrip widgets={[]} inputs={inputs} language="json" onInsert={jest.fn()} />);
    const chips = openCategory(view.container, "inputs");
    expect(textOf(chips.querySelector("[data-input-about]"))).toBe("from Park access: 3 layers");
    fireEvent.click(within(chips).getByRole("button", { name: "Show the columns of input_0" }));
    const lines = Array.from(chips.querySelectorAll("[data-layer-line]"));
    expect(lines.map((line) => line.getAttribute("data-layer-line"))).toEqual(["tip_parks", "tip_roads", "park_access"]);
    expect(Array.from(lines[2].children).map((part) => textOf(part))).toEqual(["park_access", "a raster"]);
    expect(lines[2].querySelector("[data-column-tag]")).toBeNull();
  });

  test("a raster on its own says it is one, on its line and in its list", () => {
    const raster: InputScope = { slot: 0, label: "Python Computation", dataType: "raster", columns: [], dtypes: {} };
    const view = render(<ReferenceStrip widgets={[]} inputs={[raster]} language="python" onInsert={jest.fn()} />);
    const chips = openCategory(view.container, "inputs");
    expect(textOf(chips.querySelector("[data-input-about]"))).toBe("from Python Computation: a raster");
    fireEvent.click(within(chips).getByRole("button", { name: "Show the columns of input_0" }));
    expect(textOf(chips.querySelector('[data-input-columns="0"]'))).toBe("This input is a raster: it has no columns.");
  });
});
