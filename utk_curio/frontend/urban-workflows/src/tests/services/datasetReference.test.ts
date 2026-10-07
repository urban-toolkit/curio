/**
 * What a dataset's copy control hands over (#206).
 *
 * The issue asks for "a way to copy the path". The path is the wrong thing to
 * hand out, and handing it out is part of why the request exists: an absolute
 * path is specific to one machine, one user and one mount, so pasting it into a
 * node produces code that works until someone else opens the dataflow. The
 * portable reference is ``curio_load_data("<id>")`` — exactly what the
 * palette's own generated loaders emit, and what the sandbox resolves and reads
 * at execution time.
 *
 * The location is still shown in the details view, as information.
 */
import {
  datasetReference,
  datasetReferenceCode,
} from "../../services/datasetCatalog/datasetReference";
import type { DatasetGroupLayerRef } from "../../services/datasetCatalog/datasetCatalogTypes";
import {
  datasetIdsInCode,
  osmGroupLoaderSnippet,
} from "../../services/datasetCatalog/datasetLoaderSnippets";

const item = (over: Record<string, unknown> = {}) =>
  ({ id: "data.utk.acs@1", path: "C:/Users/fabio/.curio/data/acs.parquet", ...over }) as never;

describe("datasetReference", () => {
  test("hands over the portable call, not the path", () => {
    expect(datasetReference(item()).code).toBe('curio_load_data("data.utk.acs@1")');
  });

  test("still reports where the bytes are", () => {
    expect(datasetReference(item()).location).toBe("C:/Users/fabio/.curio/data/acs.parquet");
  });

  test("falls back to uri when there is no path", () => {
    expect(datasetReference(item({ path: undefined, uri: "curio://outputs/x" })).location).toBe(
      "curio://outputs/x",
    );
  });

  test("reports an empty location rather than inventing one", () => {
    // A live node output has no on-disk location yet; the details view hides
    // the row rather than showing "undefined".
    expect(datasetReference(item({ path: undefined, uri: undefined })).location).toBe("");
  });
});

describe("ids that cannot be embedded", () => {
  // Ids are interpolated into Python source, so one carrying a quote or a
  // backslash would break out of the string literal. Same whitelist the
  // generator applies, and the same fallback it makes.
  test("falls back to a quoted literal path", () => {
    const ref = datasetReference(item({ id: 'evil");import os#' }));
    expect(ref.code).toBe('"C:/Users/fabio/.curio/data/acs.parquet"');
  });

  test("an id starting with punctuation is not embedded", () => {
    expect(datasetReference(item({ id: ".hidden" })).code).not.toContain("curio_");
  });

  test("a missing id is not embedded", () => {
    expect(datasetReference(item({ id: undefined })).code).not.toContain("curio_");
  });
});

describe("datasetReferenceCode", () => {
  test("is the code half of the reference", () => {
    expect(datasetReferenceCode(item())).toBe(datasetReference(item()).code);
  });

  test("hands over curio_load_collection for a collection", () => {
    expect(
      datasetReferenceCode({ id: "imported.xabc@1", path: "/x/index.parquet", uri: "", format: "collection" }),
    ).toBe('curio_load_collection("imported.xabc@1")');
  });
});

describe("a layer group's reference (#724)", () => {
  // A group card as the listing sends it (`build_layer_group_item`): the group
  // id names no file, and the card lists its layers, each with its own id.
  const layer = (id: string, layerName: string, format: "geojson" | "parquet"): DatasetGroupLayerRef => ({
    id,
    title: `Loop (${layerName})`,
    uri: `curio://datasets/${id}@1`,
    path: `/store/${id}@1/data/${layerName}.${format}`,
    format,
    layerName,
  });
  const groups: Array<[string, DatasetGroupLayerRef[]]> = [
    // An OpenStreetMap tag set from the Discovery Catalog, split by geometry.
    [
      "osm.x1a2b3c4",
      [
        layer("imported.xpoints", "points", "geojson"),
        layer("imported.xpolylines", "polylines", "geojson"),
        layer("imported.xpolygons", "polygons", "geojson"),
      ],
    ],
    ["gpkg.x1a2b3c4", [layer("imported.xparks", "parks", "parquet"), layer("imported.xtrails", "trails", "parquet")]],
    ["gtfs.x1a2b3c4", [layer("imported.xstops", "stops", "parquet"), layer("imported.xroutes", "routes", "parquet")]],
  ];

  test.each(groups)("a %s group hands over the loader its dropped card's node runs", (groupId, layers) => {
    const kind = groupId.split(".")[0];
    const ref = datasetReference({
      id: groupId,
      path: null,
      uri: `curio://${kind}/${groupId}`,
      format: kind,
      groupLayers: layers,
    } as never);
    // A group card's drop loads the layers with this loader (`osmGroupLoaderSnippet`).
    expect(ref.code).toBe(osmGroupLoaderSnippet(layers).code);
    expect(datasetIdsInCode(ref.code)).toEqual(layers.map((each) => each.id));
    expect(ref.code).not.toContain(groupId);
  });

  test("one of a group's layers still hands over its one call", () => {
    const stops = {
      ...layer("imported.xstops", "stops", "parquet"),
      groupId: "gtfs.x1a2b3c4",
    };
    expect(datasetReference(stops as never).code).toBe('curio_load_data("imported.xstops")');
  });
});
