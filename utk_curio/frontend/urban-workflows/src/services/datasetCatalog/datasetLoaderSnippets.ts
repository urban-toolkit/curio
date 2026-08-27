import {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetFormat,
  DatasetGroupLayerRef,
  DatasetLoaderSnippet,
} from "./datasetCatalogTypes";

type DatasetLike = DatasetCatalogItem | DatasetDragPayload;

function datasetPath(dataset: DatasetLike): string {
  return dataset.path || dataset.uri || "<dataset-path>";
}

/**
 * Dataset ids are interpolated into generated Python source, so only ids
 * matching this whitelist may appear inside a ``curio_dataset_path("<id>")``
 * call — an id with a quote or backslash would break out of the string
 * literal. KEEP IN SYNC with ``_SAFE_DATASET_ID_RE`` in the backend generator
 * (``backend/app/datasets/domain/catalog_item.py``) and the scan regex in
 * ``backend/app/api/routes.py``.
 */
const SAFE_DATASET_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$/;

function safeDatasetId(datasetId: string | null | undefined): string | null {
  if (!datasetId || !SAFE_DATASET_ID_RE.test(datasetId)) return null;
  return datasetId;
}

function idOf(dataset: DatasetLike): string | null {
  return "datasetId" in dataset ? dataset.datasetId : dataset.id;
}

/**
 * Python expression for the location line of a loader snippet. Preferred form
 * is the portable ``curio_dataset_path("<id>")`` call — the sandbox resolves it
 * to a real filesystem path at execution time, so generated code carries no
 * machine-, user-, or mount-specific absolute path. Falls back to the literal
 * path when no (safe) id is available.
 */
function pathExpr(path: string, datasetId?: string | null): string {
  const safeId = safeDatasetId(datasetId);
  return safeId ? `curio_dataset_path(${JSON.stringify(safeId)})` : JSON.stringify(path);
}

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
 * Loader for a multilayer OSM PBF group: reads every extracted layer's
 * GeoParquet into one ``layers`` dict keyed by layer name, so a single node
 * represents the full multilayer import. GeoParquet is read with
 * ``gpd.read_parquet`` (geometry + CRS), falling back to ``pd.read_parquet``.
 */
export function osmGroupLoaderSnippet(
  layers: DatasetGroupLayerRef[],
): DatasetLoaderSnippet {
  const readerLines = layers.map((layer, index) => {
    const key = layer.layerName || layer.title || `layer_${index}`;
    const path = layer.path || layer.uri || "<dataset-path>";
    return `layers[${JSON.stringify(key)}] = _curio_read_layer(${pathExpr(path, layer.id)})`;
  });
  const code = [
    "def _curio_read_layer(path):",
    "    try:",
    "        return gpd.read_parquet(path)",
    "    except Exception:",
    "        return pd.read_parquet(path)",
    "",
    "layers = {}",
    ...readerLines,
  ].join("\n");
  return {
    language: "python",
    imports: ["import geopandas as gpd", "import pandas as pd"],
    pathVariable: "layers",
    code,
    returnVariable: "layers",
  };
}

function snippetForFormat(
  format: DatasetFormat,
  path: string,
  datasetId?: string | null,
): DatasetLoaderSnippet {
  const expr = pathExpr(path, datasetId);
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
    return {
      language: "python",
      imports: ["import geopandas as gpd"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\ngdf = gpd.read_file(dataset_path)`,
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
    // back to `pd.read_parquet` for non-geo tables.
    return {
      language: "python",
      imports: ["import pandas as pd", "import geopandas as gpd"],
      pathVariable: "dataset_path",
      code: `dataset_path = ${expr}\ntry:\n    df = gpd.read_parquet(dataset_path)\nexcept Exception:\n    df = pd.read_parquet(dataset_path)`,
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
  return snippetForFormat(dataset.format, datasetPath(dataset), idOf(dataset));
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
  const idCalls = (groupLayers ? groupLayers.map((layer) => safeDatasetId(layer.id)) : [safeDatasetId(idOf(dataset))])
    .filter((id): id is string => Boolean(id))
    .map((id) => `curio_dataset_path(${JSON.stringify(id)})`);
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
