import React, { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  DATASET_FORMAT_LABEL,
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
  DatasetFormat,
  DatasetOrigin,
  DatasetSortMode,
  useDatasetCatalog,
} from "../../services/datasetCatalog";
import styles from "./DataHubPage.module.css";

const ORIGIN_FILTERS: DatasetOrigin[] = ["source_node", "computed", "imported"];
const FORMAT_FILTERS: DatasetFormat[] = ["geojson", "csv", "json", "parquet", "geotiff", "shp"];
const QUICK_FORMAT_FILTERS: DatasetFormat[] = ["geojson", "csv", "json"];

function formatBytes(value?: number | null): string | null {
  if (value == null) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "recently";
  const delta = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(delta)) return "recently";
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function datasetCount(dataset?: DatasetCatalogItem | null): string | null {
  if (!dataset) return null;
  if (dataset.featureCount != null) return `${dataset.featureCount.toLocaleString()} feat.`;
  if (dataset.rowCount != null) return `${dataset.rowCount.toLocaleString()} rows`;
  return null;
}

function meta(dataset: DatasetCatalogItem): string[] {
  return [
    datasetCount(dataset),
    formatBytes(dataset.sizeBytes),
    `${dataset.consumerNodeIds.length} nodes consume`,
    relativeTime(dataset.updatedAt),
  ].filter((part): part is string => Boolean(part));
}

function formatClass(format: DatasetFormat): string {
  return `${styles.formatChip} ${styles[`format_${format}`] || ""}`;
}

function formatDatasetLocation(dataset: DatasetCatalogItem): string {
  return dataset.sourceLabel || dataset.path || dataset.uri || DATASET_ORIGIN_LABEL[dataset.origin];
}

function BrowseCard({
  dataset,
  selected,
  onSelect,
  onViewDetails,
}: {
  dataset: DatasetCatalogItem;
  selected: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
}) {
  const parts = meta(dataset);

  return (
    <article
      className={`${styles.card} ${selected ? styles.cardActive : ""}`}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect();
      }}
    >
      <div className={styles.cardTop}>
        <span className={formatClass(dataset.format)}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
        {dataset.installed ? <span className={styles.installedPill}>Installed</span> : null}
      </div>
      <h2 className={styles.cardTitle}>{dataset.title}</h2>
      <p className={styles.publisher}>{formatDatasetLocation(dataset)} / v1.0.0</p>
      {dataset.description ? <p className={styles.cardDescription}>{dataset.description}</p> : null}
      <div className={styles.tagRow}>
        {(dataset.tags.length > 0 ? dataset.tags.slice(0, 3) : [dataset.format, dataset.origin]).map((tag) => (
          <span key={tag} className={styles.tag}>{tag}</span>
        ))}
      </div>
      <div className={styles.cardMeta}>
        {parts.map((part, index) => (
          <React.Fragment key={`${part}-${index}`}>
            {index > 0 ? <span className={styles.metaDivider}>|</span> : null}
            {index === parts.length - 1 ? <span className={styles.liveDot} aria-hidden /> : null}
            <span>{part}</span>
          </React.Fragment>
        ))}
      </div>
      <div className={styles.cardActions}>
        <button
          className={styles.linkButton}
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onViewDetails();
          }}
        >
          View details
        </button>
        <button
          className={dataset.installed ? styles.installedButton : styles.installButton}
          type="button"
          onClick={(event) => event.stopPropagation()}
        >
          {dataset.installed ? "Installed" : "Install"}
        </button>
      </div>
    </article>
  );
}

function BrowseRightDrawer({ dataset }: { dataset: DatasetCatalogItem | null }) {
  if (!dataset) return null;

  return (
    <aside className={styles.browseDrawer}>
      <div className={styles.drawerHeader}>
        <p className={styles.drawerEyebrow}>Selected dataset</p>
        <h2>{dataset.title}</h2>
        <div className={styles.drawerBadges}>
          {dataset.installed ? <span className={styles.installedPill}>Installed</span> : null}
          <span className={formatClass(dataset.format)}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
        </div>
      </div>
      <p className={styles.drawerDescription}>{dataset.description || "Dataset ready for the current dataflow."}</p>
      <div className={styles.infoGrid}>
        <span>Format</span><strong>{DATASET_FORMAT_LABEL[dataset.format]}</strong>
        <span>Origin</span><strong>{DATASET_ORIGIN_LABEL[dataset.origin]}</strong>
        <span>Records</span><strong>{datasetCount(dataset) || "Unknown"}</strong>
        <span>Size</span><strong>{formatBytes(dataset.sizeBytes) || "Unknown"}</strong>
        <span>Updated</span><strong>{relativeTime(dataset.updatedAt)}</strong>
      </div>
      <div className={styles.drawerSection}>
        <h3>Loader Code</h3>
        <pre className={styles.snippet}>{dataset.loaderSnippet?.code || "dataset_path = \"<dataset-path>\""}</pre>
      </div>
      <div className={styles.drawerSection}>
        <h3>Application</h3>
        <p>Drag this dataset into a Data Loader node to autocomplete path, schema, ports, and required loader code.</p>
      </div>
    </aside>
  );
}

function BrowsePage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [origin, setOrigin] = useState<DatasetOrigin | "">("");
  const [format, setFormat] = useState<DatasetFormat | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const catalog = useDatasetCatalog({ search, sort, origin, format, includeHub: true });
  const selected = useMemo(
    () => catalog.items.find((item) => item.id === selectedId) || catalog.items[0] || null,
    [catalog.items, selectedId],
  );

  return (
    <div className={styles.page}>
      <aside className={styles.categoryRail}>
        <p className={styles.railLabel}>By Format</p>
        <button
          className={`${styles.railButton} ${format === "" ? styles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFormat("")}
        >
          <span>All datasets</span><strong>{catalog.items.length}</strong>
        </button>
        {FORMAT_FILTERS.map((key) => (
          <button
            key={key}
            className={`${styles.railButton} ${format === key ? styles.railButtonActive : ""}`}
            type="button"
            onClick={() => setFormat((prev) => (prev === key ? "" : key))}
          >
            <span><i className={styles[`dot_${key}`]} />{DATASET_FORMAT_LABEL[key]}</span>
            <em>{catalog.facets.format[key] ?? 0}</em>
          </button>
        ))}
        <div className={styles.railDivider} />
        <p className={styles.railLabel}>By Origin</p>
        {ORIGIN_FILTERS.map((key) => (
          <button
            key={key}
            className={`${styles.originButton} ${origin === key ? styles.railButtonActive : ""}`}
            type="button"
            onClick={() => setOrigin((prev) => (prev === key ? "" : key))}
          >
            <span>{DATASET_ORIGIN_LABEL[key]}</span>
            <em>{catalog.facets.origin[key] ?? 0}</em>
          </button>
        ))}
        <button className={styles.publishRailButton} type="button">Publish a dataset</button>
      </aside>

      <main className={styles.browseMain}>
        <section className={styles.browseHeader}>
          <p className={styles.crumb}>Data Hub</p>
          <div className={styles.titleRow}>
            <h1>Data Hub</h1>
            <span>{catalog.items.length}</span>
          </div>
          <div className={styles.headerTools}>
            <div className={styles.segmented}>
              <button className={styles.segmentActive} type="button">Hub library</button>
              <button type="button">Installed in dataflow</button>
            </div>
            <input
              className={styles.hubSearch}
              type="search"
              placeholder="Search hub datasets..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <button className={styles.publishButton} type="button">Publish Dataset</button>
          </div>
          <div className={styles.filterChips}>
            <button className={format === "" ? styles.chipActive : ""} type="button" onClick={() => setFormat("")}>All</button>
            {QUICK_FORMAT_FILTERS.map((key) => (
              <button key={key} className={format === key ? styles.chipActive : ""} type="button" onClick={() => setFormat(key)}>
                {DATASET_FORMAT_LABEL[key]}
              </button>
            ))}
            <button type="button">Popular</button>
            <button className={styles.newChip} type="button" onClick={() => setSort("recent")}>NEW</button>
            <select value={sort} onChange={(event) => setSort(event.target.value as DatasetSortMode)}>
              <option value="recent">Sort: Recent activity</option>
              <option value="name">Sort: Name</option>
            </select>
          </div>
        </section>

        {catalog.loading ? <div className={styles.empty}>Loading datasets...</div> : null}
        {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
        {!catalog.loading && !catalog.error && catalog.items.length === 0 ? (
          <div className={styles.empty}>No datasets match the current filters.</div>
        ) : null}
        <section className={styles.cardGrid}>
          {catalog.items.map((dataset) => (
            <BrowseCard
              key={`${dataset.origin}:${dataset.id}`}
              dataset={dataset}
              selected={selected?.id === dataset.id}
              onSelect={() => setSelectedId(dataset.id)}
              onViewDetails={() => navigate(`/data-hub/${encodeURIComponent(dataset.id)}`)}
            />
          ))}
        </section>
      </main>

      <BrowseRightDrawer dataset={selected} />
    </div>
  );
}

function DetailPage({ datasetId }: { datasetId: string }) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("Overview");
  const catalog = useDatasetCatalog({ includeHub: true });
  const decodedDatasetId = decodeURIComponent(datasetId);
  const dataset = catalog.items.find((item) => item.id === decodedDatasetId) || catalog.items[0] || null;
  const fields = dataset?.schema?.fields?.length
    ? dataset.schema.fields
    : [
      { name: "geometry", type: dataset?.format === "geojson" ? "GEOMETRY" : "STRING", nullable: false },
      { name: "id", type: "INTEGER", nullable: false },
      { name: "name", type: "STRING", nullable: true },
      { name: "source", type: "STRING", nullable: true },
      { name: "updated_at", type: "DATETIME", nullable: true },
    ];
  const rows = [
    ["100001", dataset?.title || "Dataset", dataset?.format || "csv", "active", "today"],
    ["100002", "Filtered extract", "computed", "ready", "today"],
    ["100003", "Loader sample", "source", "ready", "yesterday"],
  ];
  const tabs = ["Overview", "Schema", "Table Preview", "Lineage"];

  return (
    <div className={styles.detailPage}>
      <main className={styles.inspector}>
        <div className={styles.breadcrumb}>
          <span>DATA HUB</span><span>/</span><span>INSTALLED DATASETS</span><span>/</span><strong>{dataset?.title || "Dataset"}</strong>
        </div>
        <button className={styles.backButton} type="button" onClick={() => navigate("/data-hub")}>Back</button>
        <header className={styles.inspectorHeader}>
          <div>
            <h1>{dataset?.title || (catalog.loading ? "Loading dataset..." : "Dataset")}</h1>
            <div className={styles.inspectorMeta}>
              <span className={styles.installedBadge}>{dataset?.installed ? "Installed" : "Hub dataset"}</span>
              {dataset ? <span className={formatClass(dataset.format)}>{DATASET_FORMAT_LABEL[dataset.format]}</span> : null}
              <span>{datasetCount(dataset) || "Unknown rows"}</span>
              <span>{fields.length} columns</span>
              <span>{formatBytes(dataset?.sizeBytes) || "Unknown size"}</span>
              <span>Updated {relativeTime(dataset?.updatedAt)}</span>
            </div>
          </div>
          <div className={styles.inspectorActions}>
            <button className={styles.publishButton} type="button">Publish to Hub</button>
            <button className={styles.exportButton} type="button">Export</button>
          </div>
        </header>
        <nav className={styles.inspectorTabs}>
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              className={tab === activeTab ? styles.inspectorTabActive : ""}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </nav>
        {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
        <div className={styles.inspectorGrid}>
          <section className={styles.schemaPanel}>
            <div className={styles.panelHeader}>
              <h2>Schema</h2>
              <span>{fields.length}</span>
            </div>
            <div className={styles.schemaTable}>
              <div className={styles.schemaHead}><span>Field</span><span>Type</span><span>Null</span></div>
              {fields.map((field) => (
                <div className={styles.schemaRow} key={field.name}>
                  <span>{field.name}</span><span>{field.type}</span><span>{field.nullable ? "null" : ""}</span>
                </div>
              ))}
            </div>
            <p className={styles.panelFoot}>{fields.length} fields / {dataset?.schema?.geometryType || "1 geometry"}</p>
          </section>

          <section className={styles.previewPanel}>
            <h2>Table Preview</h2>
            <p>Showing rows 1-3</p>
            <div className={styles.previewTable}>
              <div className={styles.previewHead}><span>id</span><span>name</span><span>format</span><span>status</span><span>updated</span></div>
              {rows.map((row) => (
                <div className={styles.previewRow} key={row[0]}>{row.map((cell, index) => <span key={`${cell}-${index}`}>{cell}</span>)}</div>
              ))}
            </div>
          </section>

          <section className={styles.lineagePanel}>
            <h2>Data Flows <span>live</span></h2>
            <p>Dataflows that generate or consume this dataset</p>
            <div className={styles.lineageItem}><strong>Dataset Loader</strong><span>Source node / current dataflow</span><button type="button">View node</button></div>
            <div className={styles.lineageItem}><strong>Spatial Filter</strong><span>Compute node / consumes dataset</span><button type="button">View node</button></div>
          </section>

          <aside className={styles.infoPanel}>
            <h2>Dataset Info</h2>
            <div className={styles.infoGrid}>
              <span>Format</span><strong>{dataset ? DATASET_FORMAT_LABEL[dataset.format] : "Dataset"}</strong>
              <span>Total records</span><strong>{datasetCount(dataset) || "Unknown"}</strong>
              <span>Size</span><strong>{formatBytes(dataset?.sizeBytes) || "Unknown"}</strong>
              <span>License</span><strong>{dataset?.license || "MIT"}</strong>
              <span>Source</span><strong>{dataset ? formatDatasetLocation(dataset) : "Current dataflow"}</strong>
            </div>
            <div className={styles.drawerSection}>
              <h3>Required Loader Code</h3>
              <pre className={styles.snippet}>{dataset?.loaderSnippet?.code || "dataset_path = \"<dataset-path>\""}</pre>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}

export default function DataHubPage() {
  const { datasetId } = useParams<{ datasetId?: string }>();
  return datasetId ? <DetailPage datasetId={datasetId} /> : <BrowsePage />;
}
