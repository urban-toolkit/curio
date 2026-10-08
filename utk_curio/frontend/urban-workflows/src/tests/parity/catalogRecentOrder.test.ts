/**
 * The canvas's Data palette lists datasets in the catalog's Recent activity
 * order. ``catalog_recent_order.json`` lists each case's items in the order the
 * catalog's listing gives them (``test_catalog_recent_parity.py`` runs them
 * through the listing); the palette, given them in that order, keeps it. A
 * palette layer group takes the date of its latest layer, as the catalog's
 * group does.
 */
import * as fs from "fs";
import * as path from "path";
import {
  groupDatasetsForPalette,
  sortDatasetPaletteEntries,
  type DatasetPaletteEntry,
  type DatasetPaletteGroup,
} from "../../services/datasetCatalog/datasetPaletteGrouping";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..");
const FIXTURE = path.join(
  REPO_ROOT, "utk_curio", "backend", "tests", "test_datasets", "catalog_recent_order.json",
);

interface Row {
  id: string;
  title?: string | null;
  updatedAt?: string | null;
}

interface Cases {
  recent: { case: string; items: Row[] }[];
  groups: { case: string; layers: (string | null)[]; updatedAt: string }[];
}

const CASES: Cases = JSON.parse(fs.readFileSync(FIXTURE, "utf-8"));

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
  for (const c of CASES.recent) {
    test(c.case, () => {
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
    test(c.case, () => {
      const members = c.layers.map((stamp, i) =>
        dataset(
          { id: `imported.xparity${LAYERS[i]}`, title: `parity (${LAYERS[i]})`, updatedAt: stamp },
          { groupId: "osm.xparity", layerName: LAYERS[i] },
        ),
      );
      const [group] = groupDatasetsForPalette(members) as DatasetPaletteGroup[];
      expect(group.updatedAt).toBe(c.updatedAt);
      expect(group.importedAt).toBe(c.updatedAt);
    });
  }
});
