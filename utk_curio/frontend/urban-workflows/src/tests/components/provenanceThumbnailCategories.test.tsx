/**
 * The provenance drawer draws an opened version's thumbnail with the
 * categories the nodes' registered descriptors give now, as the Projects page
 * draws a saved project with the categories its manifests declare now. So a
 * version saved without categories is drawn in colour, and a node no
 * registered package provides keeps the category recorded with its version.
 * Drawing changes nothing that is saved.
 */
import React from "react";
import { fireEvent, render } from "@testing-library/react";

jest.mock("../../hook/useCode", () => ({
  useCode: () => ({ loadTrill: jest.fn() }),
}));

import { DataflowProvenance } from "../../components/provenance/DataflowProvenance";
import { TrillGenerator } from "../../TrillGenerator";
import { colorForCategory } from "../../constants/nodeCategoryPalette";
import { clearCategoryDescriptors, registerCategoryDescriptor } from "../_support/categoryDescriptors";

beforeAll(() => {
  registerCategoryDescriptor("acme.hydro/gauge@1", "data");
  registerCategoryDescriptor("scout.comparison/donuts@1", "vis_grammar");
});

afterAll(() => clearCategoryDescriptors());

beforeEach(() => {
  TrillGenerator.reset();
  TrillGenerator.provenanceJSON = {
    id: "wf",
    nodes: [
      {
        // Saved with no categories.
        id: "v1",
        label: "v1",
        timestamp: 1,
        preview: {
          nodes: [
            { id: "a", type: "acme.hydro/gauge@1", x: 0, y: 0 },
            { id: "b", type: "scout.comparison/donuts", x: 300, y: 0 },
          ],
          edges: [{ source: "a", target: "b" }],
        },
      },
      {
        // Recorded with categories.
        id: "v2",
        label: "v2",
        timestamp: 2,
        preview: {
          nodes: [
            { id: "a", type: "acme.hydro/gauge@1", category: "computation", x: 0, y: 0 },
            { id: "c", type: "acme.gone/gauge@1", category: "vis_simple", x: 300, y: 0 },
            { id: "d", type: "acme.gone/table@1", category: null, x: 600, y: 0 },
          ],
          edges: [],
        },
      },
    ],
    edges: [{ id: "v1_to_v2", source: "v1", target: "v2", label: "Node added" }],
  };
});

/** Opens every version, as a click on its row does. */
const renderOpened = (view: "list" | "graph" = "list") => {
  const utils = render(<DataflowProvenance view={view} />);
  for (const id of ["v1", "v2"]) {
    fireEvent.click(utils.container.querySelector(`[data-provenance-item="${id}"] button`)!);
  }
  return utils;
};

/** The colour of each node's bar in a version's thumbnail. */
const fills = (container: HTMLElement, id: string) =>
  Array.from(container.querySelectorAll(`[data-provenance-item="${id}"] svg g`)).map((g) =>
    g.querySelectorAll("rect")[1].getAttribute("fill"),
  );

describe("the provenance drawer colours each version's nodes by category", () => {
  test.each(["list", "graph"] as const)(
    "from the registered descriptors, else what the version recorded (%s)",
    (view) => {
      const { container } = renderOpened(view);

      expect(fills(container, "v1")).toEqual([colorForCategory("data"), colorForCategory("vis_grammar")]);
      expect(fills(container, "v2")).toEqual([
        colorForCategory("data"),
        colorForCategory("vis_simple"),
        colorForCategory(null),
      ]);
    },
  );

  test("the registered category wins over the recorded one, in a colour of its own", () => {
    expect(colorForCategory("data")).not.toBe(colorForCategory("computation"));
    expect(fills(renderOpened().container, "v2")[0]).toBe("var(--curio-category-data-fg)");
  });

  test("drawing leaves the saved versions as they were", () => {
    renderOpened();

    const saved = TrillGenerator.getSerializableDataflowProvenance().graph.nodes;
    expect(saved[0].preview.nodes[0]).toEqual({ id: "a", type: "acme.hydro/gauge@1", x: 0, y: 0 });
    expect(saved[1].preview.nodes[0].category).toBe("computation");
  });
});
