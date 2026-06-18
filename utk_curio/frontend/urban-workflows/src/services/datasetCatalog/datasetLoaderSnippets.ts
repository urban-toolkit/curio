import {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetFormat,
  DatasetLoaderSnippet,
} from "./datasetCatalogTypes";

type DatasetLike = DatasetCatalogItem | DatasetDragPayload;

function datasetPath(dataset: DatasetLike): string {
  return dataset.path || dataset.uri || "<dataset-path>";
}

/**
 * Loader body for ``format: bundle`` datasets (multi-output / tuple node
 * results). Reads ``data/bundle.json`` + ``data/parts/*`` and returns the parts
 * as a tuple so the sandbox re-detects the same ``outputs`` envelope the
 * producing node emitted.
 */
function bundleLoaderCode(path: string): string {
  return [
    `bundle_path = "${path}"`,
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

function snippetForFormat(format: DatasetFormat, path: string): DatasetLoaderSnippet {
  if (format === "csv") {
    return {
      language: "python",
      imports: ["import pandas as pd"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\ndf = pd.read_csv(dataset_path)`,
      returnVariable: "df",
    };
  }
  if (format === "geojson" || format === "shp") {
    return {
      language: "python",
      imports: ["import geopandas as gpd"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\ngdf = gpd.read_file(dataset_path)`,
      returnVariable: "gdf",
    };
  }
  if (format === "json") {
    return {
      language: "python",
      imports: ["import json"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\nwith open(dataset_path) as f:\n    data = json.load(f)`,
      returnVariable: "data",
    };
  }
  if (format === "geotiff") {
    return {
      language: "python",
      imports: ["import rasterio"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\nsrc = rasterio.open(dataset_path)`,
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
      code: bundleLoaderCode(path),
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
      code: `dataset_path = "${path}"\ntry:\n    df = gpd.read_parquet(dataset_path)\nexcept Exception:\n    df = pd.read_parquet(dataset_path)`,
      returnVariable: "df",
    };
  }
  return {
    language: "python",
    imports: [],
    pathVariable: "dataset_path",
    code: `dataset_path = "${path}"`,
    returnVariable: null,
  };
}

export function getDatasetLoaderSnippet(dataset: DatasetLike): DatasetLoaderSnippet {
  if (dataset.loaderSnippet) return dataset.loaderSnippet;
  return snippetForFormat(dataset.format, datasetPath(dataset));
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
  if (dataset.path && trimmed.includes(dataset.path)) {
    return trimmed;
  }

  // If the existing code ends with a `return` statement, insert the loader
  // block BEFORE it and update the return to use the snippet's result variable.
  const returnLineMatch = trimmed.match(/^([\s\S]*?)\n?((\s*)return\b[^\n]*)$/);
  if (returnLineMatch && snippet.returnVariable) {
    const beforeReturn = returnLineMatch[1].trimEnd();
    const returnIndent = returnLineMatch[3];
    const newReturn = `${returnIndent}return ${snippet.returnVariable}`;
    return [
      ...missingImports,
      missingImports.length > 0 ? "" : null,
      beforeReturn,
      "",
      block,
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
