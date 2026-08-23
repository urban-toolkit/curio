import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { packagesApi } from "../../api/packagesApi";
import {
  DATASET_FORMAT_LABEL,
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
  DatasetFormat,
  DatasetOrigin,
  DatasetSortMode,
  datasetCatalogApi,
  facetImportedTotal,
  notifyDatasetCatalogRefresh,
  useDatasetCatalog,
} from "../../services/datasetCatalog";
import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import { DataCatalogBrowseCard } from "./DataCatalogBrowseCard";
import { DataCatalogBrowseDrawer } from "./DataCatalogBrowseDrawer";
import { DatasetDetailModal } from "../../components/datasets/catalog/DatasetDetailModal";
import {
  FORMAT_FILTERS,
  ORIGIN_FILTERS,
  QUICK_FORMAT_FILTERS,
} from "./dataHubBrowseConstants";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export const DataCatalogBrowse: React.FC = () => {
  const navigate = useNavigate();
  const { projectId } = useFlowContext();
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [origin, setOrigin] = useState<DatasetOrigin | "">("");
  const [format, setFormat] = useState<DatasetFormat | "">("");
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const [sampleDatasetId, setSampleDatasetId] = useState<string | null>(null);
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

  useEffect(() => {
    if (catalog.items.length === 0) {
      setSelectedId(undefined);
      return;
    }
    if (selectedId === null) return;
    if (selectedId != null && catalog.items.some((item) => item.id === selectedId)) return;
    setSelectedId(undefined);
  }, [catalog.items, selectedId]);

  const drawerDataset = useMemo(() => {
    if (selectedId === null) return null;
    if (selectedId != null) {
      return catalog.items.find((item) => item.id === selectedId) ?? null;
    }
    return catalog.items[0] ?? null;
  }, [catalog.items, selectedId]);
  const sampleDataset = useMemo(
    () => (sampleDatasetId ? catalog.items.find((item) => item.id === sampleDatasetId) ?? null : null),
    [catalog.items, sampleDatasetId],
  );

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
    <div className={[styles.page, drawerSlotOpen ? styles.pageWithDrawer : ""].filter(Boolean).join(" ")}>
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
              {key === "imported"
                ? facetImportedTotal(catalog.facets.origin)
                : catalog.facets.origin[key] ?? 0}
            </span>
          </button>
        ))}
      </aside>

      <main className={styles.browseMain}>
        <section className={styles.browseHeader}>
          <p className={styles.crumb}>Data Catalog</p>
          <div className={styles.titleRow}>
            <CatalogKindIcon kind="dataset" size="md" title="Dataset catalog" />
            <h1>Data Catalog</h1>
            <span className={styles.titleCount}>{catalog.items.length}</span>
          </div>
          <p style={{ margin: "0 0 12px", fontSize: 13, color: "#6B6B76", maxWidth: 720 }}>
            View datasets available in the catalog library. Adding a dataset to a dataflow is done
            in the project&apos;s Data Catalog.
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
        </div>

        {catalog.loading && catalog.items.length === 0 ? (
          <div className={styles.empty}>Loading datasets…</div>
        ) : null}
        {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
        {!catalog.loading && !catalog.refreshing && !catalog.error && catalog.items.length === 0 ? (
          <div className={styles.empty}>No datasets match the current filters.</div>
        ) : null}

        <section
          className={[styles.cardGrid, catalog.refreshing ? styles.cardGridRefreshing : ""].join(" ")}
        >
          {catalog.items.map((dataset) => (
            <DataCatalogBrowseCard
              key={`${dataset.origin}:${dataset.id}`}
              dataset={dataset}
              selected={drawerDataset?.id === dataset.id}
              onSelect={() => setSelectedId(dataset.id)}
              onViewDetails={() => navigate(`/catalog/data/${encodeURIComponent(dataset.id)}`)}
              publishingId={publishingId}
              onPublish={handlePublish}
              catalogPublishAllowed={catalogPublishAllowed}
            />
          ))}
        </section>
      </main>

      <DataCatalogBrowseDrawer
        dataset={drawerDataset}
        publishingId={publishingId}
        onPublish={handlePublish}
        onClose={() => setSelectedId(null)}
        onViewSample={(dataset) => setSampleDatasetId(dataset.id)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {sampleDatasetId ? (
        <DatasetDetailModal
          datasetId={sampleDatasetId}
          fallbackDataset={sampleDataset}
          initialTab="Table Preview"
          onClose={() => setSampleDatasetId(null)}
        />
      ) : null}
    </div>
  );
};

export default DataCatalogBrowse;
