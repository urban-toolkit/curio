/**
 * The cases in services/datasetCatalog/catalogDates.cases.json, run through the
 * canvas's Data palette. backend/tests/test_datasets/test_catalog_dates.py runs
 * the same file through the catalog listing, so the palette reads dataset dates
 * as the catalog does: given a case's items in the order the catalog lists
 * them, the palette keeps that order, and a palette layer group takes the date
 * of its latest layer, as the catalog's group does.
 */
import fs from "fs";
import path from "path";

import {
  groupDatasetsForPalette,
  sortDatasetPaletteEntries,
  type DatasetPaletteEntry,
  type DatasetPaletteGroup,
} from "../../services/datasetCatalog/datasetPaletteGrouping";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

interface Row {
  id: string;
  title?: string | null;
  updatedAt?: string | null;
}

interface DateCases {
  cases: { name: string; items: Row[] }[];
  groups: { name: string; layers: (string | null)[]; updatedAt: string }[];
}

const CASES: DateCases = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../services/datasetCatalog/catalogDates.cases.json"), "utf8"),
);

const LAYERS = ["points", "lines", "multipolygons", "other_relations"];

function dataset(row: Row, extra: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem {
  return {
    id: row.id,
    title: row.title ?? "",
    origin: "imported",
    format: "parquet",
    uri: `curio://${row.id}`,
    consumerNodeIds: [],
    updatedAt: row.updatedAt,
    tags: [],
    installed: true,
    ...extra,
  } as DatasetCatalogItem;
}

const entryId = (entry: DatasetPaletteEntry) =>
  entry.kind === "single" ? entry.dataset.id : entry.groupId;

describe("the Data palette keeps the catalog's Recent activity order", () => {
  for (const c of CASES.cases) {
    test(c.name, () => {
      // No createdAt, so a row's import time is its updatedAt, the catalog's key.
      const entries = groupDatasetsForPalette(c.items.map((row) => dataset(row)));
      expect(sortDatasetPaletteEntries(entries, "importedAt").map(entryId)).toEqual(
        c.items.map((row) => row.id),
      );
    });
  }
});

describe("a palette layer group takes the date of its latest layer", () => {
  for (const c of CASES.groups) {
    test(c.name, () => {
      const members = c.layers.map((stamp, i) =>
        dataset(
          { id: `imported.xdates${LAYERS[i]}`, title: `dates (${LAYERS[i]})`, updatedAt: stamp },
          { groupId: "osm.xdates", layerName: LAYERS[i] },
        ),
      );
      const [group] = groupDatasetsForPalette(members) as DatasetPaletteGroup[];
      expect(group.updatedAt).toBe(c.updatedAt);
      expect(group.importedAt).toBe(c.updatedAt);
    });
  }
});
