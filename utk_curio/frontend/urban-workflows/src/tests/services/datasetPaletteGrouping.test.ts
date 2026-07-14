import {
  groupDatasetsForPalette,
  osmGroupBaseTitle,
  sortDatasetPaletteEntries,
  type DatasetPaletteEntry,
  type DatasetPaletteGroup,
  type DatasetPaletteSingle,
} from "../../services/datasetCatalog/datasetPaletteGrouping";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

function ds(overrides: Partial<DatasetCatalogItem>): DatasetCatalogItem {
  return {
    id: "d",
    title: "Dataset",
    origin: "imported",
    format: "parquet",
    uri: "curio://x",
    consumerNodeIds: [],
    updatedAt: "2026-07-14T00:00:00Z",
    tags: [],
    installed: true,
    ...overrides,
  } as DatasetCatalogItem;
}

describe("groupDatasetsForPalette", () => {
  test("folds same-groupId layers into one group, singles pass through", () => {
    const items = [
      ds({ id: "a", groupId: "osm.x1", title: "chicago_loop (points)", layerName: "points" }),
      ds({ id: "single", groupId: undefined, title: "Cooling Centers" }),
      ds({ id: "b", groupId: "osm.x1", title: "chicago_loop (lines)", layerName: "lines" }),
      ds({ id: "c", groupId: "osm.x1", title: "chicago_loop (multipolygons)", layerName: "multipolygons" }),
    ];

    const entries = groupDatasetsForPalette(items);

    // First-seen order: the group placeholder sits where the first member was.
    expect(entries.map((e) => e.kind)).toEqual(["group", "single"]);
    const group = entries[0] as DatasetPaletteGroup;
    expect(group.groupId).toBe("osm.x1");
    expect(group.members.map((m) => m.id)).toEqual(["a", "b", "c"]);
    expect(group.title).toBe("chicago_loop");
  });

  test("a single-member group is still a group", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "only", groupId: "osm.x9", title: "roads (points)", layerName: "points" }),
    ]);
    expect(entries).toHaveLength(1);
    expect(entries[0].kind).toBe("group");
  });

  test("representative updatedAt is the latest member value", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "a", groupId: "g", title: "x (a)", updatedAt: "2026-07-10T00:00:00Z" }),
      ds({ id: "b", groupId: "g", title: "x (b)", updatedAt: "2026-07-14T00:00:00Z" }),
    ]);
    expect((entries[0] as DatasetPaletteGroup).updatedAt).toBe("2026-07-14T00:00:00Z");
  });

  test("datasets with no groupId are never grouped", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "a" }),
      ds({ id: "b" }),
    ]);
    expect(entries.every((e) => e.kind === "single")).toBe(true);
  });

  test("keeps two distinct imports (different groupIds) as separate groups", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "a1", groupId: "osm.x1", title: "loop (points)" }),
      ds({ id: "b1", groupId: "osm.x2", title: "loop (points)" }),
    ]);
    expect(entries).toHaveLength(2);
    expect(entries.every((e) => e.kind === "group")).toBe(true);
  });
});

describe("representative group timestamps", () => {
  test("importedAt/installedAt are the latest member values", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "a", groupId: "g", title: "x (a)", createdAt: "2026-07-01T00:00:00Z", installedAt: "2026-07-05T00:00:00Z" }),
      ds({ id: "b", groupId: "g", title: "x (b)", createdAt: "2026-07-03T00:00:00Z", installedAt: "2026-07-02T00:00:00Z" }),
    ]);
    const group = entries[0] as DatasetPaletteGroup;
    expect(group.importedAt).toBe("2026-07-03T00:00:00Z");
    expect(group.installedAt).toBe("2026-07-05T00:00:00Z");
  });
});

describe("sortDatasetPaletteEntries", () => {
  const singleId = (e: DatasetPaletteEntry) =>
    e.kind === "single" ? (e as DatasetPaletteSingle).dataset.id : e.groupId;

  test("orders by import time (createdAt), most recent first", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "old", createdAt: "2026-07-01T00:00:00Z" }),
      ds({ id: "new", createdAt: "2026-07-10T00:00:00Z" }),
      ds({ id: "mid", createdAt: "2026-07-05T00:00:00Z" }),
    ]);
    expect(sortDatasetPaletteEntries(entries, "importedAt").map(singleId)).toEqual([
      "new",
      "mid",
      "old",
    ]);
  });

  test("orders by install time (installedAt), independent of import time", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "a", createdAt: "2026-07-10T00:00:00Z", installedAt: "2026-07-01T00:00:00Z" }),
      ds({ id: "b", createdAt: "2026-07-01T00:00:00Z", installedAt: "2026-07-10T00:00:00Z" }),
    ]);
    expect(sortDatasetPaletteEntries(entries, "installedAt").map(singleId)).toEqual(["b", "a"]);
  });

  test("a group sorts as a unit by its representative timestamp", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "single", createdAt: "2026-07-04T00:00:00Z" }),
      ds({ id: "g1", groupId: "osm.g", title: "loop (points)", createdAt: "2026-07-09T00:00:00Z" }),
      ds({ id: "g2", groupId: "osm.g", title: "loop (lines)", createdAt: "2026-07-08T00:00:00Z" }),
    ]);
    // Group's representative importedAt = 2026-07-09 > single's 2026-07-04.
    expect(sortDatasetPaletteEntries(entries, "importedAt").map(singleId)).toEqual([
      "osm.g",
      "single",
    ]);
  });

  test("entries with an unknown timestamp sort last (stable)", () => {
    const entries = groupDatasetsForPalette([
      ds({ id: "known", installedAt: "2026-07-05T00:00:00Z" }),
      ds({ id: "unknown1", installedAt: null }),
      ds({ id: "unknown2", installedAt: null }),
    ]);
    expect(sortDatasetPaletteEntries(entries, "installedAt").map(singleId)).toEqual([
      "known",
      "unknown1",
      "unknown2",
    ]);
  });
});

describe("osmGroupBaseTitle", () => {
  test("strips the trailing (layer) suffix", () => {
    expect(osmGroupBaseTitle([ds({ title: "chicago_loop (multipolygons)" })], "g")).toBe(
      "chicago_loop",
    );
  });

  test("falls back to the group id when no usable title", () => {
    expect(osmGroupBaseTitle([ds({ title: "" })], "osm.x1")).toBe("osm.x1");
    expect(osmGroupBaseTitle([], "osm.x1")).toBe("osm.x1");
  });
});
