/**
 * A dataset widget (Data Loading's Data) and what a file or a Data Catalog
 * dataset dropped on its node does: the widget holds the dataset's id, and the
 * node's bindings follow what the widget holds, so a save, usage counts and
 * Remove from project see it (datasetApplication's applyDatasetToWidget).
 */
import {
  applyDatasetToWidget,
  buildDatasetWidgetNodeOptions,
  isWidgetLoaderCode,
  keptInCodeLoader,
  nodeBoundDatasetIds,
  widgetLoaderCode,
  type DatasetCatalogItem,
  type DatasetDragPayload,
} from "../../services/datasetCatalog";
import {
  datasetWidgetBindings,
  datasetWidgetIds,
  datasetWidgetReadBy,
  firstDatasetWidget,
  withDatasetValue,
} from "../../utils/widgets/datasetWidgets";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

const DATA: WidgetDef = { name: "data", type: "dataset", label: "Data", default: "" };
const STARTER = "data = curio_load_data([!! data !!])\nreturn data\n";

function card(id: string, overrides: Partial<DatasetDragPayload> = {}): DatasetDragPayload {
  return {
    datasetId: id,
    title: `Title of ${id}`,
    uri: `curio://datasets/${id}@1`,
    path: `/store/${id}@1/data/file.csv`,
    format: "csv",
    origin: "imported",
    ...overrides,
  } as DatasetDragPayload;
}

/** A layer group's drag, as an OSM extract's import or its palette row makes it. */
function groupCard(id: string, layers: string[]): DatasetDragPayload {
  return card(id, {
    title: "manhattan",
    format: "osm" as DatasetDragPayload["format"],
    path: null,
    groupLayers: layers.map((layer) => ({
      id: `imported.x${layer}`,
      title: `manhattan (${layer})`,
      uri: `curio://datasets/imported.x${layer}@1`,
      path: `/store/imported.x${layer}@1/data/${layer}.parquet`,
      format: "parquet",
      layerName: layer,
    })) as DatasetDragPayload["groupLayers"],
  });
}

describe("which dataset widget a drop on a node sets", () => {
  test("the dataset widget its code reads", () => {
    const widgets = [{ name: "k", type: "number", default: 1 }, DATA];
    expect(datasetWidgetReadBy(widgets, STARTER)?.name).toBe("data");
  });

  test("none when the code reads no dataset widget, so the loader is merged into the code", () => {
    expect(datasetWidgetReadBy([DATA], "import pandas as pd\nreturn pd.DataFrame()")).toBeNull();
    expect(datasetWidgetReadBy([DATA], "")).toBeNull();
    expect(datasetWidgetReadBy([{ name: "data", type: "text", default: "" }], STARTER)).toBeNull();
  });

  test("a widget of another kind is never the one, whatever the code reads", () => {
    expect(firstDatasetWidget([{ name: "n", type: "number", default: 1 }])).toBeNull();
    expect(firstDatasetWidget([{ name: "n", type: "number", default: 1 }, DATA])?.name).toBe("data");
  });
});

describe("a dataset dropped on a node's dataset widget", () => {
  test("the widget holds the dataset's id and the node is bound to it", () => {
    const next = applyDatasetToWidget({ widgets: [DATA] }, "data", card("imported.xtrees"));
    expect(next.widgets).toEqual([{ ...DATA, value: "imported.xtrees" }]);
    expect(next.datasetRefs).toEqual(["imported.xtrees"]);
    expect(Object.keys(next.appliedDatasets)).toEqual(["imported.xtrees"]);
    expect(next.datasetWidgets).toEqual({
      data: { id: "imported.xtrees", title: "Title of imported.xtrees", format: "csv", refs: ["imported.xtrees"] },
    });
  });

  test("a second dataset takes the first one's place, and other bindings stay", () => {
    const first = applyDatasetToWidget(
      { widgets: [DATA], datasetRefs: ["data.merged-into-code"] },
      "data",
      card("imported.xtrees"),
    );
    const second = applyDatasetToWidget(first, "data", card("imported.xparks"));
    expect(second.widgets[0].value).toBe("imported.xparks");
    expect(second.datasetRefs).toEqual(["data.merged-into-code", "imported.xparks"]);
    expect(Object.keys(second.appliedDatasets)).toEqual(["imported.xparks"]);
    expect(second.datasetWidgets.data.refs).toEqual(["imported.xparks"]);
  });

  test("a layer group binds its member layers, and the widget holds the group's own id", () => {
    const next = applyDatasetToWidget({ widgets: [DATA] }, "data", groupCard("osm.x1a2b3c4d", ["buildings", "roads"]));
    expect(next.widgets[0].value).toBe("osm.x1a2b3c4d");
    expect(next.datasetRefs).toEqual(["imported.xbuildings", "imported.xroads"]);
    expect(Object.keys(next.appliedDatasets)).toEqual(["imported.xbuildings", "imported.xroads"]);
    expect(next.datasetWidgets.data).toMatchObject({ id: "osm.x1a2b3c4d", title: "manhattan" });
  });

  test("a dataset another dataset widget also holds keeps its binding", () => {
    const two = [DATA, { ...DATA, name: "other", label: "Other" }];
    let data = applyDatasetToWidget({ widgets: two }, "data", card("imported.xtrees"));
    data = applyDatasetToWidget(data, "other", card("imported.xtrees"));
    data = applyDatasetToWidget(data, "data", card("imported.xparks"));
    expect(data.datasetRefs).toEqual(["imported.xtrees", "imported.xparks"]);
  });

  test("a node made from a dataset dropped on the canvas names what its widget holds", () => {
    const made = applyDatasetToWidget(
      { widgets: [DATA], datasetSource: { datasetId: "imported.xtrees", title: "Trees", format: "csv", origin: "imported" } },
      "data",
      card("imported.xparks", { title: "Parks" }),
    );
    expect(made.datasetSource).toMatchObject({ datasetId: "imported.xparks", title: "Parks" });
    const plain = applyDatasetToWidget({ widgets: [DATA] }, "data", card("imported.xparks"));
    expect(plain.datasetSource).toBeUndefined();
  });

  test("the bindings a save keeps read back as they were written", () => {
    const next = applyDatasetToWidget({ widgets: [DATA] }, "data", card("imported.xtrees"));
    expect(datasetWidgetBindings(JSON.parse(JSON.stringify(next)))).toEqual(next.datasetWidgets);
    expect(datasetWidgetBindings({ datasetWidgets: { data: { id: 3 } } })).toEqual({});
    expect(datasetWidgetBindings({ datasetWidgets: ["data"] })).toEqual({});
  });
});

describe("what a node's dataset widgets bind it to", () => {
  test("a value set some other way, such as by an agent, counts too", () => {
    const widgets = withDatasetValue([DATA], "data", "data.utk.trees");
    expect(datasetWidgetIds(widgets)).toEqual(["data.utk.trees"]);
    expect(nodeBoundDatasetIds({ widgets })).toEqual(["data.utk.trees"]);
    expect(nodeBoundDatasetIds({ widgets: [DATA] })).toEqual([]);
  });
});

describe("a dataset dropped on the empty canvas", () => {
  test("makes the node a drop on a fresh Data Loading node makes", () => {
    const options = buildDatasetWidgetNodeOptions(card("imported.xtrees"), { x: 10, y: 20 }, [DATA], STARTER);
    expect(options).not.toBeNull();
    expect(options!.code).toBe(STARTER);
    expect(options!.position).toEqual({ x: 10, y: 20 });
    expect(options!.widgets).toEqual([{ ...DATA, value: "imported.xtrees" }]);
    expect(options!.datasetRefs).toEqual(["imported.xtrees"]);
    expect(options!.datasetSource).toMatchObject({ datasetId: "imported.xtrees" });
  });

  test("before the starters have come, the node takes its starter when it mounts", () => {
    const options = buildDatasetWidgetNodeOptions(card("imported.xtrees"), { x: 0, y: 0 }, [DATA], undefined);
    expect(options).not.toBeNull();
    expect("code" in options!).toBe(false);
  });

  test("a NetCDF file keeps what it loads in the code, reading the widget", () => {
    const options = buildDatasetWidgetNodeOptions(
      card("imported.xclimate", { format: "netcdf" }),
      { x: 0, y: 0 },
      [DATA],
      STARTER,
    );
    expect(options!.code).toBe(keptInCodeLoader(card("imported.xclimate", { format: "netcdf" }), "data"));
  });

  test("a GeoTIFF's node names its bounds, as a dropped raster's loader always did", () => {
    const options = buildDatasetWidgetNodeOptions(
      card("imported.xdepth", { format: "geotiff" }),
      { x: 0, y: 0 },
      [DATA],
      STARTER,
    );
    expect(options!.code).toBe("data = curio_load_data([!! data !!], bounds=None)\nreturn data\n");
  });

  test("a template with no dataset widget is left to the loader code a drop writes", () => {
    expect(buildDatasetWidgetNodeOptions(card("x.y"), { x: 0, y: 0 }, [], STARTER)).toBeNull();
  });
});

describe("the code a drop writes from the starter", () => {
  const NETCDF = keptInCodeLoader(card("a", { format: "netcdf" }), "data")!;
  const ONNX = keptInCodeLoader(card("a", { format: "onnx" }), "data")!;
  const GEOTIFF = "data = curio_load_data([!! data !!], bounds=None)\nreturn data\n";

  test("is the starter for a value the node hands on, naming a GeoTIFF's bounds", () => {
    expect(widgetLoaderCode(card("a"), "data", STARTER)).toBe(STARTER);
    expect(widgetLoaderCode(card("a", { format: "parquet" }), "data", STARTER)).toBe(STARTER);
    expect(widgetLoaderCode(card("a", { format: "geotiff" }), "data", STARTER)).toBe(GEOTIFF);
    expect(widgetLoaderCode(card("a", { format: "netcdf" }), "data", STARTER)).toBe(NETCDF);
  });

  test("names a GeoTIFF's bounds only where the starter reads the widget", () => {
    const custom = "import rasterio\nreturn rasterio.open([!! data !!])\n";
    expect(widgetLoaderCode(card("a", { format: "geotiff" }), "data", custom)).toBe(custom);
  });

  test("before the starters have come, is the loader that keeps a value in the code, or nothing", () => {
    expect(widgetLoaderCode(card("a"), "data", undefined)).toBeUndefined();
    expect(widgetLoaderCode(card("a", { format: "geotiff" }), "data", undefined)).toBeUndefined();
    expect(widgetLoaderCode(card("a", { format: "onnx" }), "data", undefined)).toBe(ONNX);
  });

  test("is followed by the next drop while no one has edited it", () => {
    for (const written of [STARTER, `${STARTER}\n`, NETCDF, ONNX, GEOTIFF]) {
      expect(isWidgetLoaderCode(written, "data", STARTER)).toBe(true);
    }
    // A CSV after a NetCDF file returns its table again, and a NetCDF file
    // after a GeoTIFF keeps its Dataset in the code.
    expect(widgetLoaderCode(card("b"), "data", STARTER)).toBe(STARTER);
    expect(widgetLoaderCode(card("b", { format: "netcdf" }), "data", STARTER)).toBe(NETCDF);
  });

  test("is left alone once someone has edited it", () => {
    expect(isWidgetLoaderCode(`${STARTER}print(len(data))\n`, "data", STARTER)).toBe(false);
    expect(isWidgetLoaderCode(NETCDF.replace("# ds", "print(ds)\n# ds"), "data", STARTER)).toBe(false);
    expect(isWidgetLoaderCode(STARTER.replace("data !!", "other !!"), "data", STARTER)).toBe(false);
    expect(isWidgetLoaderCode(undefined, "data", STARTER)).toBe(false);
    expect(isWidgetLoaderCode("", "data", STARTER)).toBe(false);
  });
});

describe("what a NetCDF file or an ONNX model loads stays in the code", () => {
  test("their loader reads the widget and returns nothing", () => {
    expect(keptInCodeLoader(card("a", { format: "netcdf" }), "data")).toBe(
      "ds = curio_load_data([!! data !!])\n# ds cannot leave this node: return a table, a raster or a value made from it.\n",
    );
    expect(keptInCodeLoader(card("a", { format: "onnx" }), "data")).toMatch(/^session = curio_load_data\(\[!! data !!\]\)\n/);
  });

  test("every other format's value leaves the node as the starter returns it", () => {
    for (const format of ["csv", "geojson", "parquet", "geotiff", "json", "bundle", "collection"]) {
      expect(keptInCodeLoader(card("a", { format: format as DatasetCatalogItem["format"] }), "data")).toBeNull();
    }
  });
});
