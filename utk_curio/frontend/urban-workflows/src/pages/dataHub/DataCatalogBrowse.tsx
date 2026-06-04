import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { packagesApi } from "../../api/packagesApi";
import { CatalogPublishPill } from "../../components/packages/CatalogPublishPill";
import {
  DATASET_FORMAT_LABEL,
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
  DatasetFormat,
  DatasetOrigin,
  DatasetSortMode,
  datasetProvenanceLabel,
  facetImportedTotal,
  isDatasetPublishedToCatalog,
  datasetCatalogApi,
  notifyDatasetCatalogRefresh,
  useDatasetCatalog,
} from "../../services/datasetCatalog";
import { formatDatasetLocation } from "../../components/datasets/catalog/datasetDetailHelpers";
import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import styles from "../catalog/CatalogBrowseLayout.module.css";

/** Browse rail: two provenance buckets (API maps ``imported`` filter to hub/imported/source_node). */
const ORIGIN_FILTERS: DatasetOrigin[] = ["computed", "imported"];
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

function isFresh(iso?: string | null): boolean {
  if (!iso) return false;
  const delta = Date.now() - new Date(iso).getTime();
  return Number.isFinite(delta) && delta < 24 * 60 * 60 * 1000;
}

function datasetCount(dataset?: DatasetCatalogItem | null): string | null {
  if (!dataset) return null;
  if (dataset.featureCount != null) return `${dataset.featureCount.toLocaleString()} feat.`;
  if (dataset.rowCount != null) return `${dataset.rowCount.toLocaleString()} rows`;
  return null;
}

function metaLeft(dataset: DatasetCatalogItem): string {
  return [
    datasetCount(dataset),
    formatBytes(dataset.sizeBytes),
    `${dataset.consumerNodeIds.length} nodes consume`,
  ]
    .filter(Boolean)
    .join(" | ");
}

function GeoPreviewIllustration({ format }: { format: DatasetFormat }) {
  const colors: Record<DatasetFormat, { fill: string; stroke: string; bg: string }> = {
    geojson: { fill: "rgba(47,143,74,0.12)", stroke: "rgba(47,143,74,0.3)", bg: "#F0FAF2" },
    csv:     { fill: "rgba(59,111,212,0.1)",  stroke: "rgba(59,111,212,0.25)", bg: "#F0F4FF" },
    json:    { fill: "rgba(122,75,209,0.1)",  stroke: "rgba(122,75,209,0.25)", bg: "#F7F2FF" },
    parquet: { fill: "rgba(251,170,105,0.12)", stroke: "rgba(251,170,105,0.3)", bg: "#FFF8F0" },
    geotiff: { fill: "rgba(122,75,209,0.1)",  stroke: "rgba(122,75,209,0.25)", bg: "#F7F2FF" },
    shp:     { fill: "rgba(136,136,136,0.1)", stroke: "rgba(136,136,136,0.25)", bg: "#F5F5F5" },
  };
  const c = colors[format] || colors.geojson;
  return (
    <div className={styles.geoPreview} style={{ background: c.bg }}>
      <svg className={styles.geoPreviewSvg} viewBox="0 0 296 112" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M60 80 L100 50 L145 62 L180 48 L210 68 L208 98 L165 106 L110 103 L60 96 Z"
          fill={c.fill} stroke={c.stroke} strokeWidth="1"
        />
        <path
          d="M80 84 L115 58 L148 68 L172 58 L195 74 L193 95 L160 100 L118 98 L80 92 Z"
          fill={c.fill}
        />
      </svg>
      <span className={styles.geoPreviewLabel}>preview</span>
    </div>
  );
}

function BrowseCard({
  dataset,
  selected,
  onSelect,
  onViewDetails,
  publishingId,
  onPublish,
  catalogPublishAllowed,
}: {
  dataset: DatasetCatalogItem;
  selected: boolean;
  onSelect: () => void;
  onViewDetails: () => void;
  publishingId: string | null;
  onPublish: (dataset: DatasetCatalogItem) => void;
  catalogPublishAllowed: boolean;
}) {
  const fresh = isFresh(dataset.updatedAt);
  const left = metaLeft(dataset);
  const tags = dataset.tags.length > 0 ? dataset.tags.slice(0, 3) : [dataset.format];
  const lastTagIdx = tags.length - 1;
  const published = isDatasetPublishedToCatalog(dataset);
  const showPublishPill = published || catalogPublishAllowed;

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        styles[`card_${dataset.format}`] || "",
      ].join(" ")}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(); }}
    >
      <div className={`${styles.cardStrip} ${styles[`strip_${dataset.format}`] || ""}`}>
        <span className={styles.cardFormatBadge}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {dataset.installed && <span className={styles.stripBadgePopular}>✓ INSTALLED</span>}
          {selected && <span className={styles.selectedDot} />}
        </div>
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{dataset.title}</h2>
        <p className={styles.publisher}>{formatDatasetLocation(dataset)} · v1.0.0</p>
        <p
          className={styles.cardDescription}
          {...(!dataset.description ? { "aria-hidden": true } : {})}
        >
          {dataset.description || "\u00a0"}
        </p>
        <div className={styles.tagRow}>
          {tags.map((tag, i) => (
            <span
              key={tag}
              className={`${styles.tag} ${i === lastTagIdx ? (styles[`tagAccent_${dataset.format}`] || "") : ""}`}
            >
              {tag}
            </span>
          ))}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>{left}</span>
        <span className={styles.metaRight}>
          <span className={`${styles.liveDot} ${fresh ? styles.liveDotGreen : styles.liveDotGray}`} />
          <span>{relativeTime(dataset.updatedAt)}</span>
        </span>
      </div>

      <div className={styles.cardActions}>
        <div className={styles.cardActionsLeft}>
          {showPublishPill ? (
            <CatalogPublishPill
              variant="hub"
              dirName={dataset.dirName || dataset.id}
              published={published}
              allowPublish={catalogPublishAllowed}
              busy={publishingId === dataset.id}
              onPublish={() => {
                void onPublish(dataset);
              }}
              publishedTitle="Listed in the Data Catalog"
              publishActionTitle="Write this dataset into the dev catalog under datasets/"
            />
          ) : null}
        </div>
        <div className={styles.cardActionsRight}>
          <button
            className={`${styles.linkButton} ${styles[`link_${dataset.format}`] || ""}`}
            type="button"
            onClick={(e) => { e.stopPropagation(); onViewDetails(); }}
          >
            View details ↗
          </button>
        </div>
      </div>
    </article>
  );
}

function BrowseRightDrawer({
  dataset,
  publishingId,
  onPublish,
}: {
  dataset: DatasetCatalogItem | null;
  publishingId: string | null;
  onPublish: (dataset: DatasetCatalogItem) => void;
}) {
  if (!dataset) {
    return (
      <aside className={styles.browseDrawer}>
        <div className={styles.drawerHeader}>
          <p className={styles.drawerTitle}>Dataset Details</p>
          <button className={styles.drawerClose} type="button">✕</button>
        </div>
        <div className={styles.drawerEmpty}>Select a dataset to see details</div>
      </aside>
    );
  }

  const fresh = isFresh(dataset.updatedAt);
  const left = metaLeft(dataset);
  const crs = dataset.schema?.crs ?? null;
  const published = isDatasetPublishedToCatalog(dataset);

  return (
    <aside className={styles.browseDrawer}>
      <div className={styles.drawerHeader}>
        <p className={styles.drawerTitle}>Dataset Details</p>
        <button className={styles.drawerClose} type="button" aria-label="Close">✕</button>
      </div>

      <GeoPreviewIllustration format={dataset.format} />

      <div className={styles.drawerDatasetName}>
        <h2>{dataset.title}</h2>
        <div className={styles.drawerBadgesRow}>
          <span className={`${styles.drawerFormatBadge} ${styles[`dfmt_${dataset.format}`] || ""}`}>
            {DATASET_FORMAT_LABEL[dataset.format]}
          </span>
          {published ? (
            <span className={styles.drawerPublishStatusPublished}>Published</span>
          ) : (
            <span className={styles.drawerPublishStatusUnpublished}>Unpublished</span>
          )}
          {dataset.installed && (
            <span className={`${styles.drawerFormatBadge} ${styles.dfmt_geojson}`}>✓ Installed</span>
          )}
        </div>
      </div>

      <div className={styles.drawerPublisher}>
        <span className={styles.drawerPublisherText}>
          {formatDatasetLocation(dataset)} · v1.0.0
        </span>
        <span className={styles.verifiedBadge}>
          <span className={styles.verifiedCircle}>✓</span>
          Verified
        </span>
      </div>

      <div className={styles.drawerMeta}>
        <span>{left}</span>
        <span className={styles.drawerMetaRight}>
          <span className={`${styles.liveDot} ${fresh ? styles.liveDotGreen : styles.liveDotGray}`} />
          <span>{relativeTime(dataset.updatedAt)}</span>
        </span>
      </div>

      {dataset.description && (
        <div className={styles.drawerSection}>
          <p className={styles.drawerDescription}>{dataset.description}</p>
        </div>
      )}

      <div className={styles.drawerSection}>
        <p className={styles.drawerSectionLabel}>Dataset Info</p>
        <div className={styles.infoRow}>
          <span className={styles.infoRowLabel}>Format</span>
          <span className={styles.infoRowValue}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
        </div>
        {datasetCount(dataset) && (
          <div className={styles.infoRow}>
            <span className={styles.infoRowLabel}>{dataset.featureCount != null ? "Features" : "Rows"}</span>
            <span className={styles.infoRowValue}>{datasetCount(dataset)}</span>
          </div>
        )}
        {dataset.sizeBytes != null && (
          <div className={styles.infoRow}>
            <span className={styles.infoRowLabel}>File size</span>
            <span className={styles.infoRowValue}>{formatBytes(dataset.sizeBytes)}</span>
          </div>
        )}
        {crs && (
          <div className={styles.infoRow}>
            <span className={styles.infoRowLabel}>CRS</span>
            <span className={styles.infoRowValue}>{crs}</span>
          </div>
        )}
        <div className={styles.infoRow}>
          <span className={styles.infoRowLabel}>License</span>
          <span className={styles.infoRowValue}>{dataset.license || "CC BY 4.0"}</span>
        </div>
        <div className={styles.infoRow}>
          <span className={styles.infoRowLabel}>Origin</span>
          <span className={styles.infoRowValue}>{datasetProvenanceLabel(dataset.origin)}</span>
        </div>
      </div>

      {dataset.tags.length > 0 && (
        <div className={styles.drawerSection}>
          <p className={styles.drawerSectionLabel}>Tags</p>
          <div className={styles.drawerTagsRow}>
            {dataset.tags.map((tag) => (
              <span key={tag} className={styles.drawerTag}>{tag}</span>
            ))}
          </div>
        </div>
      )}

      <div className={styles.drawerCtas}>
        {published ? (
          <div className={styles.drawerPublishedPrimary} role="status" aria-label="Published to Data Catalog">
            Published
          </div>
        ) : (
          <button
            type="button"
            className={styles.addToPaletteBtn}
            disabled={publishingId != null}
            onClick={() => onPublish(dataset)}
          >
            Publish
          </button>
        )}
        <button className={styles.viewSampleBtn} type="button">
          View sample data
        </button>
      </div>

      <p className={styles.trustNote}>
        Published by verified author<br />
        Last updated: {relativeTime(dataset.updatedAt)}
      </p>
    </aside>
  );
}

export const DataCatalogBrowse: React.FC = () => {
  const navigate = useNavigate();
  const { projectId } = useFlowContext();
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [origin, setOrigin] = useState<DatasetOrigin | "">("");
  const [format, setFormat] = useState<DatasetFormat | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const catalog = useDatasetCatalog({ search, sort, origin, format, includeHub: true });

  useEffect(() => {
    void packagesApi
      .factoryCapabilities()
      .then((cap) => {
        setCatalogPublishAllowed(cap.catalogPublish);
      })
      .catch(() => {
        setCatalogPublishAllowed(false);
      });
  }, []);
  const selected = useMemo(
    () => catalog.items.find((item) => item.id === selectedId) || catalog.items[0] || null,
    [catalog.items, selectedId],
  );

  /** Total rows in the current search universe (facets are computed before format/origin filters). */
  const catalogFacetDatasetTotal = useMemo(
    () => Object.values(catalog.facets.format).reduce((sum, n) => sum + n, 0),
    [catalog.facets.format],
  );

  const handlePublish = useCallback(
    async (dataset: DatasetCatalogItem) => {
      setPublishingId(dataset.id);
      try {
        await datasetCatalogApi.publishDataset(dataset.id, {
          ...(projectId ? { dataflowId: projectId } : {}),
        });
        notifyDatasetCatalogRefresh();
        await catalog.reload();
        showToast(`Published ${dataset.title}.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not publish dataset.", "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog.reload, projectId, showToast],
  );

  return (
    <div className={styles.page}>
      <aside className={styles.categoryRail}>
        <p className={styles.railLabel}>By format</p>

        <button
          className={`${styles.railButton} ${format === "" ? styles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFormat("")}
        >
          <span>All datasets</span>
          <span className={styles.railCountBadge}>{catalogFacetDatasetTotal}</span>
        </button>

        {FORMAT_FILTERS.map((key) => (
          <button
            key={key}
            className={`${styles.railButton} ${format === key ? styles.railButtonActive : ""}`}
            type="button"
            onClick={() => setFormat((prev) => (prev === key ? "" : key))}
          >
            <span className={styles.railFormatItem}>
              <i className={`${styles.dot} ${styles[`dot_${key}`] || ""}`} />
              {DATASET_FORMAT_LABEL[key]}
            </span>
            <span className={styles.railCount}>{catalog.facets.format[key] ?? 0}</span>
          </button>
        ))}

        <div className={styles.railDivider} />
        <p className={styles.railLabel}>By origin</p>

        <button
          className={`${styles.railButton} ${origin === "" ? styles.railButtonActive : ""}`}
          type="button"
          onClick={() => setOrigin("")}
        >
          <span>All origins</span>
        </button>

        {ORIGIN_FILTERS.map((key) => (
          <button
            key={key}
            className={`${styles.railButton} ${origin === key ? styles.railButtonActive : ""}`}
            type="button"
            onClick={() => setOrigin((prev) => (prev === key ? "" : key))}
          >
            <span>{DATASET_ORIGIN_LABEL[key]}</span>
            <span className={styles.railCount}>
              {key === "imported" ? facetImportedTotal(catalog.facets.origin) : catalog.facets.origin[key] ?? 0}
            </span>
          </button>
        ))}

        <button className={styles.publishRailButton} type="button">Publish a dataset</button>
      </aside>

      <main className={styles.browseMain}>
        <section className={styles.browseHeader}>
          <p className={styles.crumb}>Data Catalog</p>
          <div className={styles.titleRow}>
            <h1>Data Catalog</h1>
            <span className={styles.titleCount}>{catalog.items.length}</span>
          </div>
          <p style={{ margin: "0 0 12px", fontSize: 13, color: "#6B6B76", maxWidth: 720 }}>
            View datasets available in the catalog library.
            Installing a dataset into a project can be done in the project&apos;s data catalog.
          </p>
          <div className={styles.headerTools}>
            <span className={styles.hubStatusChip}>
              <span className={styles.hubStatusDot} />
              Catalog library
            </span>
            <input
              className={styles.hubSearch}
              type="search"
              placeholder="Search catalog datasets…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {/* <button className={styles.publishButton} type="button">Publish Dataset</button> */}
          </div>
        </section>

        <div className={styles.filterBar}>
          <button
            className={`${styles.chip} ${format === "" ? styles.chipActive : ""}`}
            type="button"
            onClick={() => setFormat("")}
          >
            All
          </button>
          {QUICK_FORMAT_FILTERS.map((key) => (
            <button
              key={key}
              className={`${styles.chip} ${format === key ? styles.chipActive : ""}`}
              type="button"
              onClick={() => setFormat((prev) => (prev === key ? "" : key))}
            >
              <span className={`${styles.chipDot} ${styles[`chipDot_${key}`] || ""}`} />
              {DATASET_FORMAT_LABEL[key]}
            </button>
          ))}
          <button className={styles.chip} type="button">Popular</button>
          <button className={styles.newChip} type="button" onClick={() => setSort("recent")}>
            NEW
          </button>

          <span className={styles.filterSpacer} />

          <select
            className={styles.sortSelect}
            value={sort}
            onChange={(e) => setSort(e.target.value as DatasetSortMode)}
          >
            <option value="recent">Sort: Recent activity</option>
            <option value="name">Sort: Name</option>
          </select>

          <div className={styles.viewToggles}>
            <button className={styles.viewToggleActive} type="button" title="Grid view" aria-label="Grid view">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <rect x="0" y="0" width="5" height="4" rx="0.5" fill="#555"/>
                <rect x="7" y="0" width="5" height="4" rx="0.5" fill="#555"/>
                <rect x="0" y="6" width="5" height="4" rx="0.5" fill="#555"/>
                <rect x="7" y="6" width="5" height="4" rx="0.5" fill="#555"/>
              </svg>
            </button>
            <button className={styles.viewToggleInactive} type="button" title="List view" aria-label="List view">
              <svg width="12" height="10" viewBox="0 0 12 10" fill="none">
                <line x1="0" y1="1" x2="12" y2="1" stroke="#BBBBBB" strokeWidth="1.2"/>
                <line x1="0" y1="5" x2="12" y2="5" stroke="#BBBBBB" strokeWidth="1.2"/>
                <line x1="0" y1="9" x2="12" y2="9" stroke="#BBBBBB" strokeWidth="1.2"/>
              </svg>
            </button>
          </div>
        </div>

        {catalog.loading && catalog.items.length === 0 ? (
          <div className={styles.empty}>Loading datasets…</div>
        ) : null}
        {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
        {!catalog.loading && !catalog.refreshing && !catalog.error && catalog.items.length === 0 ? (
          <div className={styles.empty}>No datasets match the current filters.</div>
        ) : null}

        <section
          className={[
            styles.cardGrid,
            catalog.refreshing ? styles.cardGridRefreshing : "",
          ].join(" ")}
        >
          {catalog.items.map((dataset) => (
            <BrowseCard
              key={`${dataset.origin}:${dataset.id}`}
              dataset={dataset}
              selected={selected?.id === dataset.id}
              onSelect={() => setSelectedId(dataset.id)}
              onViewDetails={() => navigate(`/catalog/data/${encodeURIComponent(dataset.id)}`)}
              publishingId={publishingId}
              onPublish={handlePublish}
              catalogPublishAllowed={catalogPublishAllowed}
            />
          ))}
        </section>
      </main>

      <BrowseRightDrawer
        dataset={selected}
        publishingId={publishingId}
        onPublish={handlePublish}
      />
    </div>
  );
};

export default DataCatalogBrowse;
