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
    };
  }
  if (format === "geojson" || format === "shp") {
    return {
      language: "python",
      imports: ["import geopandas as gpd"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\ngdf = gpd.read_file(dataset_path)`,
    };
  }
  if (format === "json") {
    return {
      language: "python",
      imports: ["import json"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\nwith open(dataset_path) as f:\n    data = json.load(f)`,
    };
  }
  if (format === "geotiff") {
    return {
      language: "python",
      imports: ["import rasterio"],
      pathVariable: "dataset_path",
      code: `dataset_path = "${path}"\nsrc = rasterio.open(dataset_path)`,
    };
  }
  return {
    language: "python",
    imports: [],
    pathVariable: "dataset_path",
    code: `dataset_path = "${path}"`,
  };
}

export function getDatasetLoaderSnippet(dataset: DatasetLike): DatasetLoaderSnippet {
  if (dataset.loaderSnippet) return dataset.loaderSnippet;
  return snippetForFormat(dataset.format, datasetPath(dataset));
}

export function buildDatasetLoaderCode(dataset: DatasetLike): string {
  const snippet = getDatasetLoaderSnippet(dataset);
  return [...snippet.imports, "", snippet.code].filter(Boolean).join("\n");
}

export function mergeDatasetLoaderCode(currentCode: string | undefined, dataset: DatasetLike): string {
  const trimmed = (currentCode || "").trim();
  const snippet = getDatasetLoaderSnippet(dataset);
  const missingImports = snippet.imports.filter((line) => !trimmed.includes(line));
  const title = "title" in dataset ? dataset.title : "Dataset";
  const marker = `# Curio dataset loader: ${title}`;
  const block = [marker, snippet.code].join("\n");

  if (!trimmed) {
    return [...snippet.imports, "", block].filter(Boolean).join("\n");
  }
  if (dataset.path && trimmed.includes(dataset.path)) {
    return trimmed;
  }

  return [
    ...missingImports,
    missingImports.length > 0 ? "" : null,
    trimmed,
    "",
    block,
  ].filter((part): part is string => part !== null).join("\n");
}
