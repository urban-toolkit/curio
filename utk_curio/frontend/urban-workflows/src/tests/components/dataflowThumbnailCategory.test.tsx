/**
 * A dataflow's thumbnail paints each node's bar in the colour of the node's
 * category: the category its template declares, which the server reads off the
 * manifests for a saved project and a preview built in the browser takes from
 * the node's registered descriptor. A node with no category, or one the
 * palette has no colour for, is the neutral grey. The node's type plays no part
 * in it, so a package's node is painted as a built-in one is.
 */
import React from "react";
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";

import type { GraphPreview, GraphPreviewNode } from "../../api/projectsApi";
import DataflowThumbnail from "../../components/DataflowThumbnail";
import { CATEGORY_FALLBACK_FG, NODE_CATEGORY_KEY, categoryFg } from "../../constants/nodeCategoryPalette";
import type { NodeCategory } from "../../registry/types";
import { shippedManifest, shippedManifests } from "../_support/categoryDescriptors";

const node = (id: string, type: string, category?: string | null): GraphPreviewNode => ({
  id,
  type,
  x: 300 * Number(id.replace(/\D/g, "") || 0),
  y: 0,
  ...(category !== undefined ? { category } : {}),
});

/** The fill of each node's bar, in the preview's order. */
function bars(nodes: GraphPreviewNode[]): string[] {
  const preview: GraphPreview = { nodes, edges: [] };
  const { container } = render(<DataflowThumbnail preview={preview} />);
  return Array.from(container.querySelectorAll("g")).map((g) => {
    const rects = g.querySelectorAll("rect");
    expect(rects).toHaveLength(2);
    return rects[1].getAttribute("fill") ?? "";
  });
}

const colour = (category: NodeCategory) => categoryFg(NODE_CATEGORY_KEY[category]);

describe("DataflowThumbnail colours each node by its category", () => {
  test("a package's node takes the colour of the category its template declares, as a built-in one does", () => {
    expect(
      bars([
        node("n0", "scout.rasters/raster-calculator@1", "computation"),
        node("n1", "acme.hydro/gauge@1", "data"),
        node("n2", "scout.comparison/donuts@1", "vis_grammar"),
        node("n3", "acme.hydro/table", "vis_simple"),
        node("n4", "acme.tools/route@1", "flow"),
        node("n5", "curio.builtin/vis-vega@1", "vis_grammar"),
      ]),
    ).toEqual([
      "var(--curio-category-computation-fg)",
      "var(--curio-category-data-fg)",
      "var(--curio-category-vis-fg)",
      "var(--curio-category-vis-fg)",
      "var(--curio-category-package-fg)",
      "var(--curio-category-vis-fg)",
    ]);
  });

  test("a node with no category is grey, whatever its type", () => {
    // A built-in type with no category is not looked up anywhere: the
    // preview's category is the only thing the bar reads.
    expect(
      bars([
        node("n0", "curio.builtin/data-loading@1"),
        node("n1", "curio.builtin/vis-vega", null),
        node("n2", "acme.gone/gauge@1", null),
        node("n3", "VIS_VEGA"),
      ]),
    ).toEqual(Array(4).fill(CATEGORY_FALLBACK_FG));
  });

  test("a category the palette has no colour for is grey", () => {
    // A manifest in an account's store is read as written, so its category
    // can be anything, including an Object.prototype key.
    const odd = ["", "weird", "Data", "vis", "package", "constructor", "__proto__", "toString", "hasOwnProperty"];
    expect(bars(odd.map((category, i) => node(`n${i}`, "acme.hydro/gauge@1", category)))).toEqual(
      Array(odd.length).fill(CATEGORY_FALLBACK_FG),
    );
  });

  test("every built-in kind takes the colour of the category its manifest declares", () => {
    // The thumbnail kept its own map of built-in kinds, which drifted from
    // the manifest (#524): Data Pool painted as computation, Spatial Join
    // grey. The preview now carries each template's own category.
    const manifest = shippedManifest("curio.builtin@1");
    const nodes = manifest.templates.map((template, i) =>
      node(`n${i}`, `${manifest.id}/${template.id}@1`, template.category),
    );
    expect(nodes.length).toBeGreaterThan(0);
    expect(bars(nodes)).toEqual(manifest.templates.map((template) => colour(template.category as NodeCategory)));
  });

  test("every category a shipped template declares has a colour", () => {
    for (const [dirName, manifest] of Object.entries(shippedManifests())) {
      for (const template of manifest.templates) {
        expect([dirName, template.id, Object.keys(NODE_CATEGORY_KEY).includes(template.category)])
          .toEqual([dirName, template.id, true]);
      }
    }
  });
});
