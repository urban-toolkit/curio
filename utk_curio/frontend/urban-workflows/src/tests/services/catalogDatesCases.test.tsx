import React from "react";
import fs from "fs";
import path from "path";
import { render } from "@testing-library/react";

/**
 * The cases in services/datasetCatalog/catalogDates.cases.json, run through the
 * canvas's Data palette. backend/tests/test_datasets/test_catalog_dates.py runs
 * the same file through the catalog listing, so the two agree: given a case's
 * items as the listing gives them, the palette shows the same items in the same
 * order (a layer group where its first layer is listed), and a palette layer
 * group takes the date of its latest layer, as the catalog's group does.
 */

jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
  OVERLAY_TRIGGER_DELAY_PROPS: { delay: { show: 0, hide: 0 } },
}));
jest.mock("../../components/menus/nodes/datasetPalette/DatasetPaletteRows", () => ({
  DatasetRow: ({ dataset }: { dataset: { id: string } }) => <div data-palette-entry={dataset.id} />,
  DatasetGroupRow: ({ group }: { group: { groupId: string } }) => (
    <div data-palette-entry={group.groupId} />
  ),
}));
jest.mock("../../components/menus/nodes/datasetPalette/DatasetInstallingRow", () => ({
  DatasetInstallingRow: () => null,
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "flow-1",
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
  }),
}));
jest.mock("../../providers/datasetCatalog", () => ({
  useDatasetCatalogDrawer: () => ({ openDatasetCatalogDrawer: jest.fn() }),
}));
jest.mock("../../providers/DatasetPaletteContext", () => ({
  useDatasetPalette: () => ({ datasetRevealId: null, setDatasetRevealId: jest.fn() }),
}));
jest.mock("../../components/datasets/catalog/datasetDetailsContext", () => ({
  useDatasetDetails: () => ({ openDatasetDetails: jest.fn() }),
}));
// Only the listing is stubbed: the palette filters and groups it as it does on
// the canvas.
let mockListing: unknown[] = [];
jest.mock("../../services/datasetCatalog", () => ({
  ...jest.requireActual("../../services/datasetCatalog"),
  useDatasetCatalog: () => ({
    items: mockListing,
    loading: false,
    refreshing: false,
    reload: jest.fn(),
  }),
  prefetchDatasetCatalog: jest.fn(),
}));
jest.mock("../../utils/saveOutputDataset", () => ({ buildSaveableLiveOutputs: () => undefined }));

import { DatasetsPaletteDropdown } from "../../components/menus/nodes/datasetPalette/DatasetsPaletteDropdown";
import {
  groupDatasetsForPalette,
  type DatasetPaletteGroup,
} from "../../services/datasetCatalog/datasetPaletteGrouping";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

interface Row {
  id: string;
  title?: string | null;
  updatedAt?: string | null;
  createdAt?: string | null;
  installedAt?: string | null;
  groupId?: string;
  layerName?: string;
}

interface DateCases {
  cases: { name: string; items: Row[] }[];
  groups: { name: string; layers: (string | null)[]; updatedAt: string }[];
}

const CASES: DateCases = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../services/datasetCatalog/catalogDates.cases.json"), "utf8"),
);

const LAYERS = ["points", "lines", "multipolygons", "other_relations"];

/** A dataset added to this dataflow, as the listing gives it. */
function dataset(row: Row): DatasetCatalogItem {
  return {
    origin: "imported",
    format: "parquet",
    uri: `curio://${row.id}`,
    consumerNodeIds: [],
    tags: [],
    installed: true,
    ...row,
    title: row.title ?? "",
  } as DatasetCatalogItem;
}

/** The listing's ids, a layer group once, where its first layer is listed. */
function listingOrder(rows: Row[]): string[] {
  const order: string[] = [];
  for (const row of rows) {
    const id = row.groupId ?? row.id;
    if (!order.includes(id)) order.push(id);
  }
  return order;
}

/** The ids of the entries the open palette shows, top to bottom. */
function paletteOrder(rows: Row[]): string[] {
  mockListing = rows.map(dataset);
  const { unmount } = render(<DatasetsPaletteDropdown open setOpen={() => {}} />);
  const shown = Array.from(document.body.querySelectorAll("[data-palette-entry]")).map(
    (entry) => entry.getAttribute("data-palette-entry") ?? "",
  );
  unmount();
  return shown;
}

describe("the Data palette shows the listing's items in the listing's order", () => {
  for (const c of CASES.cases) {
    test(c.name, () => {
      expect(paletteOrder(c.items)).toEqual(listingOrder(c.items));
    });
  }
});

describe("a palette layer group takes the date of its latest layer", () => {
  for (const c of CASES.groups) {
    test(c.name, () => {
      const members = c.layers.map((stamp, i) =>
        dataset({
          id: `imported.xdates${LAYERS[i]}`,
          title: `dates (${LAYERS[i]})`,
          updatedAt: stamp,
          groupId: "osm.xdates",
          layerName: LAYERS[i],
        }),
      );
      const [group] = groupDatasetsForPalette(members) as DatasetPaletteGroup[];
      expect(group.updatedAt).toBe(c.updatedAt);
    });
  }
});
