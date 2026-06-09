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
  if (format === "parquet") {
    return {
      language: "python",
      imports: ["import pandas as pd"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\ndf = pd.read_parquet(dataset_path)`,
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
