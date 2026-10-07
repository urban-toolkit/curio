import {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetFormat,
  DatasetGroupLayerRef,
  DatasetLoaderSnippet,
} from "./datasetCatalogTypes";
import { AUTARK_LAYER_TYPES } from "../../utils/autarkLayerTypes";

type DatasetLike = DatasetCatalogItem | DatasetDragPayload;

/**
 * The Autark layer a dataset downloaded from the Discovery Catalog is, when its
 * layer is one (an OpenStreetMap download's `buildings`). A GeoPackage layer
 * may have any name, so the name alone decides nothing. KEEP IN SYNC with
 * `autark_layer_type` in the backend generator.
 */
function autarkLayerType(dataset: DatasetLike): string | null {
  if (!("discoverySource" in dataset) || !dataset.discoverySource) return null;
  const layer = dataset.layerName;
  return typeof layer === "string" && AUTARK_LAYER_TYPES.has(layer) ? layer : null;
}

function datasetPath(dataset: DatasetLike): string {
  return dataset.path || dataset.uri || "<dataset-path>";
}

/**
 * Dataset ids are interpolated into generated Python source, so only ids
 * matching this whitelist may appear inside a ``curio_load_data("<id>")``
 * call — an id with a quote or backslash would break out of the string
 * literal. KEEP IN SYNC with ``_SAFE_DATASET_ID_RE`` in the backend generator
 * (``backend/app/datasets/domain/catalog_item.py``) and the scan regex in
 * ``backend/app/datasets/domain/code_refs.py``.
 */
const SAFE_DATASET_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$/;

/**
 * Every dataset id a piece of node code references through
 * ``curio_load_data("<id>")``, ``curio_data_path("<id>")`` or
 * ``curio_load_collection("<id>")``.
 *
 * The reader half of the contract the generators above write, kept beside them
 * so the grammar has one home. Both quote styles are accepted because users
 * edit the generated code, matching ``DATASET_PATH_CALL_RE`` in
 * ``backend/app/datasets/domain/code_refs.py``.
 *
 * This exists because a node can reference a dataset two ways and only one was
 * ever looked at (#205). Dragging a dataset onto the canvas writes bindings
 * (``datasetSource`` / ``datasetRefs``); typing or editing the loader call
 * writes nothing but the code. "Which nodes use this dataset" only knew about
 * the bindings, so a hand-authored loader -- exactly what the reporter built --
 * counted as using nothing.
 */
export function datasetIdsInCode(code: unknown): string[] {
  if (typeof code !== "string" || !code) return [];
  const ids: string[] = [];
  const seen = new Set<string>();
  // Fresh matcher per call: a module-level /g regex carries lastIndex between
  // calls, so sharing one would make results depend on call order.
  //
  // The \1 backreference is load-bearing: it requires the closing quote to
  // match the opening one, so `curio_load_data("x')` is not a reference.
  // `curio_data_path` (the file) and `curio_load_collection` (a collection's
  // index) reference the dataset just as much (`DATASET_PATH_CALL_RE` matches all three).
  // The id is the first argument; options may follow it, as
  // `curio_load_data("<id>", bounds=...)`.
  const re = /(?:curio_load_data|curio_data_path|curio_load_collection)\(\s*(["'])([A-Za-z0-9][A-Za-z0-9._@-]{0,199})\1\s*[,)]/g;
  for (const match of code.matchAll(re)) {
    const id = match[2];
    if (seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
    // Same bound as the backend's MAX_EXEC_DATASET_IDS: generated or
    // pathological code must not turn a highlight into a long scan.
    if (ids.length >= 32) break;
  }
  return ids;
}

function safeDatasetId(datasetId: string | null | undefined): string | null {
  if (!datasetId || !SAFE_DATASET_ID_RE.test(datasetId)) return null;
  return datasetId;
}

function idOf(dataset: DatasetLike): string | null {
  return "datasetId" in dataset ? dataset.datasetId : dataset.id;
}

/**
 * Python expression for the location line of an id-less loader snippet. A
 * dataset with a (safe) id never gets one: its loader is the portable
 * ``curio_load_data("<id>")`` call, which the sandbox resolves and reads at
 * execution time, so generated code carries no machine-, user-, or
 * mount-specific absolute path.
 */
function pathExpr(path: string): string {
  return JSON.stringify(path);
}

/** What a loader names the value `curio_load_data` returns, per format. KEEP IN
 * SYNC with `LOADED_VARIABLES` in the backend generator. */
const LOADED_VARIABLES: Partial<Record<DatasetFormat, string>> = {
  csv: "df",
  parquet: "df",
  geojson: "gdf",
  shp: "gdf",
  json: "data",
  geotiff: "src",
  bundle: "bundle",
  onnx: "session",
  netcdf: "ds",
};

/** Formats whose loaded value stays in the node's own code: a node's output
 * cannot carry an onnxruntime session or an xarray Dataset, so their loader
 * names the value and returns nothing. KEEP IN SYNC with `KEPT_IN_CODE` in the
 * backend generator. */
const KEPT_IN_CODE: ReadonlySet<DatasetFormat> = new Set<DatasetFormat>(["onnx", "netcdf"]);

/** The options a loader names after the id, so its node shows them: a
 * GeoTIFF's `bounds` read only the cells inside them. KEEP IN SYNC with
 * `LOADER_OPTIONS` in the backend generator. */
const LOADER_OPTIONS: Partial<Record<DatasetFormat, string>> = { geotiff: ", bounds=None" };

/**
 * Loader body for ``format: bundle`` datasets (multi-output / tuple node
 * results). Reads ``data/bundle.json`` + ``data/parts/*`` and returns the parts
 * as a tuple so the sandbox re-detects the same ``outputs`` envelope the
 * producing node emitted.
 */
function bundleLoaderCode(locationExpr: string): string {
  return [
    `bundle_path = ${locationExpr}`,
    "def _curio_load_bundle(path):",
    "    base = os.path.dirname(os.path.dirname(path))",
    "    with open(path) as f:",
    "        spec = json.load(f)",
    "    items = []",
    '    for part in sorted(spec.get("parts", []), key=lambda p: p.get("index", 0)):',
    '        fmt, kind = part.get("format"), part.get("kind")',
    '        file_path = os.path.join(base, part["file"]) if part.get("file") else None',
    '        if fmt == "parquet":',
    "            try:",
    "                value = gpd.read_parquet(file_path)",
    "            except Exception:",
    "                value = pd.read_parquet(file_path)",
    '        elif fmt == "csv":',
    "            value = pd.read_csv(file_path)",
    '        elif fmt in ("geojson", "shp"):',
    "            value = gpd.read_file(file_path)",
    '        elif fmt == "geotiff":',
    "            import rasterio",
    "            value = rasterio.open(file_path)",
    "        else:",
    "            with open(file_path) as part_file:",
    "                loaded = json.load(part_file)",
    '            if kind in ("int", "float", "bool", "str", "null") and isinstance(loaded, dict) and "value" in loaded:',
    '                value = loaded["value"]',
    "            else:",
    "                value = loaded",
    "        items.append(value)",
    "    return tuple(items)",
    "bundle = _curio_load_bundle(bundle_path)",
  ].join("\n");
}

/**
 * Loader for a multilayer OSM group: reads every layer into one ``layers``
 * dict keyed by layer name, so a single node represents the full multilayer
 * import. An uploaded ``.pbf``'s layers are GeoParquet, read with
 * ``gpd.read_parquet`` (geometry + CRS), falling back to ``pd.read_parquet``;
 * a Discovery download's layers are GeoJSON, read with ``gpd.read_file`` as a
 * single GeoJSON dataset is.
 */
export function osmGroupLoaderSnippet(
  layers: DatasetGroupLayerRef[],
): DatasetLoaderSnippet {
  const readerLines = layers.map((layer, index) => {
    const key = layer.layerName || layer.title || `layer_${index}`;
    const safeId = safeDatasetId(layer.id);
    if (safeId) {
      // The sandbox reads each layer by its own format (GeoJSON or GeoParquet).
      return `layers[${JSON.stringify(key)}] = curio_load_data(${JSON.stringify(safeId)})`;
    }
    const path = layer.path || layer.uri || "<dataset-path>";
    const reader = layer.format === "geojson" || layer.format === "shp" ? "gpd.read_file" : "_curio_read_layer";
    return `layers[${JSON.stringify(key)}] = ${reader}(${pathExpr(path)})`;
  });
  const readsParquet = readerLines.some((line) => line.includes("_curio_read_layer("));
  const code = [
    ...(readsParquet
      ? [
          "def _curio_read_layer(path):",
          "    try:",
          "        return gpd.read_parquet(path)",
          "    except Exception:",
          "        return pd.read_parquet(path)",
          "",
        ]
      : []),
    "layers = {}",
    ...readerLines,
  ].join("\n");
  const readsByPath = readerLines.some((line) => !line.includes("curio_load_data("));
  return {
    language: "python",
    imports: readsByPath ? ["import geopandas as gpd", "import pandas as pd"] : [],
    pathVariable: "layers",
    code,
    // NetCDF variables stay in the node's code, as a single one does.
    returnVariable: layers.some((layer) => KEPT_IN_CODE.has(layer.format)) ? null : "layers",
  };
}

function snippetForFormat(
  format: DatasetFormat,
  path: string,
  datasetId?: string | null,
  layerType?: string | null,
): DatasetLoaderSnippet {
  const safeId = safeDatasetId(datasetId);
  if (safeId) {
    const quoted = JSON.stringify(safeId);
    if (format === "collection") {
      return {
        language: "python",
        imports: [],
        pathVariable: null,
        code: `collection = curio_load_collection(${quoted})`,
        returnVariable: "collection",
      };
    }
    const variable = LOADED_VARIABLES[format];
    if (variable) {
      return {
        language: "python",
        imports: [],
        pathVariable: null,
        code: `${variable} = curio_load_data(${quoted}${LOADER_OPTIONS[format] ?? ""})`,
        returnVariable: KEPT_IN_CODE.has(format) ? null : variable,
      };
    }
    return {
      language: "python",
      imports: [],
      pathVariable: "dataset_path",
      code: `dataset_path = curio_data_path(${quoted})`,
      returnVariable: null,
    };
  }
  const expr = pathExpr(path);
  if (format === "csv") {
    return {
      language: "python",
      imports: ["import pandas as pd"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\ndf = pd.read_csv(dataset_path)`,
      returnVariable: "df",
    };
  }
  if (format === "geojson" || format === "shp") {
    // A layer type is set as the frame's metadata, so an Autark node draws the
    // frame as that layer.
    const typed = layerType && AUTARK_LAYER_TYPES.has(layerType)
      ? `\ngdf.metadata = {"layerType": ${JSON.stringify(layerType)}}`
      : "";
    return {
      language: "python",
      imports: ["import geopandas as gpd"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\ngdf = gpd.read_file(dataset_path)${typed}`,
      returnVariable: "gdf",
    };
  }
  if (format === "json") {
    // Computed dict/list outputs (e.g. autk-grammar pool wrappers) are persisted
    // zlib-compressed (`.json.zlib`) while user-imported `.json` files are plain
    // text — both carry `format: json`. Read binary and try zlib first; a plain
    // JSON document never decompresses as zlib, so the fallback is safe (kept in
    // lockstep with the backend `loader_snippet` json branch).
    return {
      language: "python",
      imports: ["import json", "import zlib"],
      pathVariable: "dataset_path",
      code: [
        `dataset_path = ${expr}`,
        'with open(dataset_path, "rb") as f:',
        "    _raw = f.read()",
        "try:",
        "    _raw = zlib.decompress(_raw)",
        "except zlib.error:",
        "    pass  # plain .json - bytes are already the document",
        'data = json.loads(_raw.decode("utf-8"))',
      ].join("\n"),
      returnVariable: "data",
    };
  }
  if (format === "geotiff") {
    return {
      language: "python",
      imports: ["import rasterio"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\nsrc = rasterio.open(dataset_path)`,
      returnVariable: "src",
    };
  }
  if (format === "onnx") {
    return {
      language: "python",
      imports: ["import onnxruntime as ort"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\nsession = ort.InferenceSession(dataset_path, providers=["CPUExecutionProvider"])`,
      returnVariable: null,
    };
  }
  if (format === "netcdf") {
    return {
      language: "python",
      imports: ["import xarray as xr"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\nds = xr.open_dataset(dataset_path, engine="netcdf4")`,
      returnVariable: null,
    };
  }
  if (format === "collection") {
    // A collection's data file is its index: one row per file. Without an id
    // only the index can be read; `curio_load_collection` adds each file's path.
    return {
      language: "python",
      imports: ["import pandas as pd"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\ncollection = pd.read_parquet(dataset_path)`,
      returnVariable: "collection",
    };
  }
  if (format === "bundle") {
    // A bundle is a multi-output (tuple / `outputs`) node result, stored as
    // `data/bundle.json` + `data/parts/*` under the dataset dir. Rebuild each
    // part with the reader matching its kind and return them as a tuple, so the
    // sandbox re-detects an `outputs` envelope identical to the one the
    // producing node emitted (same parts, order, and types/schema).
    return {
      language: "python",
      imports: [
        "import json",
        "import os",
        "import pandas as pd",
        "import geopandas as gpd",
      ],
      pathVariable: "bundle_path",
      code: bundleLoaderCode(expr),
      returnVariable: "bundle",
    };
  }
  if (format === "parquet") {
    // Computed GeoDataFrames are stored as GeoParquet (geometry + CRS
    // preserved); plain DataFrames as ordinary parquet. Read with
    // `gpd.read_parquet` first so a geo dataset reloads as a GeoDataFrame —
    // matching the output type/schema of the node that produced it — and fall
    // back to `pd.read_parquet` for non-geo tables. A layer type is set as the
    // frame's metadata, as for GeoJSON above.
    const typed = layerType && AUTARK_LAYER_TYPES.has(layerType)
      ? `\ndf.metadata = {"layerType": ${JSON.stringify(layerType)}}`
      : "";
    return {
      language: "python",
      imports: ["import pandas as pd", "import geopandas as gpd"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\ntry:\n    df = gpd.read_parquet(dataset_path)\nexcept Exception:\n    df = pd.read_parquet(dataset_path)${typed}`,
      returnVariable: "df",
    };
  }
  return {
    language: "python",
    imports: [],
    pathVariable: "dataset_path",
    code: `dataset_path = ${expr}`,
    returnVariable: null,
  };
}

export function getDatasetLoaderSnippet(dataset: DatasetLike): DatasetLoaderSnippet {
  if (dataset.loaderSnippet) return dataset.loaderSnippet;
  // A layer group's id names no file: its loader reads each layer.
  if (dataset.groupLayers && dataset.groupLayers.length > 0) return osmGroupLoaderSnippet(dataset.groupLayers);
  return snippetForFormat(dataset.format, datasetPath(dataset), idOf(dataset), autarkLayerType(dataset));
}

export function buildDatasetLoaderCode(dataset: DatasetLike): string {
  const snippet = getDatasetLoaderSnippet(dataset);
  const parts: (string | null)[] = [...snippet.imports, "", snippet.code];
  if (snippet.returnVariable) {
    parts.push(`return ${snippet.returnVariable}`);
  }
  return parts.filter(Boolean).join("\n");
}

export function mergeDatasetLoaderCode(currentCode: string | undefined, dataset: DatasetLike): string {
  const trimmed = (currentCode || "").trim();
  const snippet = getDatasetLoaderSnippet(dataset);
  const missingImports = snippet.imports.filter((line) => !trimmed.includes(line));
  const title = "title" in dataset ? dataset.title : "Dataset";
  const marker = `# Curio dataset loader: ${title}`;
  const block = [marker, snippet.code].join("\n");

  if (!trimmed) {
    // New empty node: include a return statement so the data flows downstream.
    const parts: (string | null)[] = [...snippet.imports, "", block];
    if (snippet.returnVariable) parts.push(`return ${snippet.returnVariable}`);
    return parts.filter(Boolean).join("\n");
  }
  // Already-applied check: id-form loader calls (per-layer for OSM groups), or
  // the legacy literal path for nodes generated before id-based resolution.
  const groupLayers =
    "groupLayers" in dataset && dataset.groupLayers && dataset.groupLayers.length > 0
      ? dataset.groupLayers
      : null;
  const call = dataset.format === "collection" && !groupLayers ? "curio_load_collection" : "curio_load_data";
  // Up to the id's closing quote: a call that goes on with options, such as a
  // raster's bounds, loads the dataset just as much.
  const idCalls = (groupLayers ? groupLayers.map((layer) => safeDatasetId(layer.id)) : [safeDatasetId(idOf(dataset))])
    .filter((id): id is string => Boolean(id))
    .map((id) => `${call}(${JSON.stringify(id)}`);
  const alreadyApplied =
    (idCalls.length > 0 && idCalls.every((call) => trimmed.includes(call))) ||
    (dataset.path ? trimmed.includes(dataset.path) : false);
  if (alreadyApplied) {
    return trimmed;
  }

  // If the existing code ends with a `return` statement, insert the loader
  // block BEFORE it and update the return to use the snippet's result variable.
  const returnLineMatch = trimmed.match(/^([\s\S]*?)\n?((\s*)return\b[^\n]*)$/);
  if (returnLineMatch && snippet.returnVariable) {
    const beforeReturn = returnLineMatch[1].trimEnd();
    const returnIndent = returnLineMatch[3];
    // The existing return may sit inside an if/for/with (non-empty indent). Emit
    // the loader block at the SAME indent as the return, or column-0 lines would
    // land between indented code and an indented return → IndentationError.
    const indentedBlock = returnIndent
      ? block.split("\n").map((line) => (line ? returnIndent + line : line)).join("\n")
      : block;
    const newReturn = `${returnIndent}return ${snippet.returnVariable}`;
    return [
      ...missingImports,
      missingImports.length > 0 ? "" : null,
      beforeReturn,
      "",
      indentedBlock,
      newReturn,
    ].filter((part): part is string => part !== null).join("\n");
  }

  return [
    ...missingImports,
    missingImports.length > 0 ? "" : null,
    trimmed,
    "",
    block,
  ].filter((part): part is string => part !== null).join("\n");
}
