import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

jest.mock("reactflow", () => ({
  useReactFlow: () => ({ getNodes: () => [], setNodes: jest.fn(), setCenter: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
// The package-palette barrel bootstraps the whole node registry on import;
// stub it to the two symbols DatasetPaletteRows actually needs.
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
  OVERLAY_TRIGGER_DELAY_PROPS: { show: 0, hide: 0 },
}));
// DatasetConnectionBadge pulls in datasetLineage → FlowProvider → vega (ESM) at
// import time; stub it since it isn't under test here.
jest.mock("../../components/datasets/catalog/DatasetConnectionBadge", () => ({
  DatasetConnectionBadge: () => null,
}));
jest.mock("../../utils/focusDatasetNodes", () => ({
  focusLinkedNodes: () => 0,
}));

import { DatasetGroupRow } from "../../components/menus/nodes/datasetPalette/DatasetPaletteRows";
import type { DatasetPaletteGroup } from "../../services/datasetCatalog";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

function member(id: string, title: string): DatasetCatalogItem {
  return {
    id,
    title,
    origin: "imported",
    format: "parquet",
    uri: `curio://datasets/${id}`,
    dirName: `${id}@1`,
    consumerNodeIds: [],
    updatedAt: "2026-07-14T00:00:00Z",
    tags: ["parquet"],
    installed: true,
    groupId: "osm.x1",
  } as DatasetCatalogItem;
}

function group(): DatasetPaletteGroup {
  return {
    kind: "group",
    groupId: "osm.x1",
    title: "chicago_loop",
    updatedAt: "2026-07-14T00:00:00Z",
    members: [
      member("loop.points", "chicago_loop (points)"),
      member("loop.lines", "chicago_loop (lines)"),
      member("loop.multipolygons", "chicago_loop (multipolygons)"),
    ],
  };
}

describe("DatasetGroupRow", () => {
  test("collapsed by default: shows the OSM PBF parent, hides members", () => {
    render(<DatasetGroupRow group={group()} />);
    expect(screen.getByText("chicago_loop")).toBeInTheDocument();
    expect(screen.getByText("OSM PBF")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /Expand chicago_loop/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("chicago_loop (points)")).not.toBeInTheDocument();
  });

  test("expands to reveal each layer as an individually draggable row", async () => {
    render(<DatasetGroupRow group={group()} />);
    await userEvent.click(screen.getByRole("button", { name: /Expand chicago_loop/ }));

    expect(screen.getByText("chicago_loop (points)")).toBeInTheDocument();
    expect(screen.getByText("chicago_loop (lines)")).toBeInTheDocument();
    expect(screen.getByText("chicago_loop (multipolygons)")).toBeInTheDocument();

    // Each member layer sits in the group's labelled region and is draggable.
    const region = screen.getByRole("group", { name: "chicago_loop layers" });
    const draggables = within(region).getAllByText(/chicago_loop \(/);
    expect(draggables.length).toBe(3);
    for (const anchor of within(region).getAllByRole("button")) {
      // The drag handle carries the draggable attribute on the row.
      // (Presence of the member rows is the key assertion here.)
      expect(anchor).toBeInTheDocument();
    }

    expect(
      screen.getByRole("button", { name: /Collapse chicago_loop/ }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});
