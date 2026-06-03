export type DatasetOrigin = "source_node" | "computed" | "imported" | "hub";

export type DatasetFormat = "csv" | "geojson" | "json" | "parquet" | "geotiff" | "shp";

export type DatasetSortMode = "recent" | "name";

export interface DatasetSchemaField {
  name: string;
  type: string;
  nullable?: boolean;
  sample?: string | number | boolean | null;
}

export interface DatasetSchema {
  fields: DatasetSchemaField[];
  geometryType?: string | null;
  crs?: string | null;
}

export interface DatasetLoaderSnippet {
  language: "python";
  imports: string[];
  code: string;
  pathVariable: string;
  /** Variable name that should be returned from a standalone Data Loading node (e.g. "df"). */
  returnVariable?: string | null;
}

export interface DatasetCatalogItem {
  id: string;
  title: string;
  description?: string;
  origin: DatasetOrigin;
  format: DatasetFormat;
  uri: string;
  path?: string | null;
  /** Folder name in the dataset store (e.g. ``data.urbanlab.chicago-boundary@1``). Present for catalog (hub) datasets. */
  dirName?: string | null;
  sizeBytes?: number | null;
  rowCount?: number | null;
  featureCount?: number | null;
  producerNodeId?: string | null;
  consumerNodeIds: string[];
  updatedAt: string;
  sourceLabel?: string | null;
  license?: string | null;
  tags: string[];
  schema?: DatasetSchema | null;
  loaderSnippet?: DatasetLoaderSnippet | null;
  installed?: boolean;
  /** True when the producer node has been re-executed since the dataset was last installed. */
  needsReinstall?: boolean;
  /** True when a computed dataset (origin="computed") has been published to the Data Catalog.
   * The origin field stays "computed" — use this flag to determine published state. */
  publishedToHub?: boolean;
}

export interface DatasetCatalogFacets {
  origin: Record<DatasetOrigin, number>;
  format: Record<DatasetFormat, number>;
}

export interface DatasetCatalogResponse {
  items: DatasetCatalogItem[];
  facets: DatasetCatalogFacets;
}

export interface DatasetPreviewResponse {
  schema: DatasetSchema;
  rows: Record<string, unknown>[];
  rowLimit: number;
  offset: number;
  totalRows: number;
  truncated: boolean;
  unsupported?: boolean;
  message?: string;
}

export interface DatasetPreviewQuery {
  dataflowId?: string | null;
  offset?: number;
  rowLimit?: number;
}

export interface DatasetCatalogQuery {
  dataflowId?: string | null;
  search?: string;
  format?: DatasetFormat | "";
  origin?: DatasetOrigin | "";
  sort?: DatasetSortMode;
  includeHub?: boolean;
  /** Current (possibly unsaved) node outputs to show as computed datasets immediately. */
  liveOutputs?: Array<{ node_id: string; filename: string }>;
}

export interface DatasetDragPayload {
  datasetId: string;
  title: string;
  uri: string;
  path?: string | null;
  format: DatasetFormat;
  loaderSnippet?: DatasetLoaderSnippet | null;
}

export const DATASET_ORIGIN_LABEL: Record<DatasetOrigin, string> = {
  source_node: "Source nodes",
  computed: "Computed",
  imported: "Imported",
  hub: "Data Catalog",
};

export const DATASET_FORMAT_LABEL: Record<DatasetFormat, string> = {
  csv: "CSV",
  geojson: "GeoJSON",
  json: "JSON",
  parquet: "Parquet",
  geotiff: "GeoTIFF",
  shp: "SHP",
};
