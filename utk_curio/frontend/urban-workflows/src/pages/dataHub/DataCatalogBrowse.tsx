import React, { useCallback, useEffect, useMemo, useState } from "react";
import { packagesApi } from "../../api/packagesApi";
import {
  DATASET_FORMAT_LABEL,
  DATASET_IMPORT_ACCEPT,
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
  DatasetFormat,
  DatasetOrigin,
  DatasetSortMode,
  datasetCatalogApi,
  facetImportedTotal,
  notifyDatasetCatalogRefresh,
  useDatasetCatalog,
  useDatasetImport,
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
import { CatalogHeaderImport } from "../catalog/CatalogHeaderImport";
import styles from "../catalog/CatalogBrowseLayout.module.css";

export const DataCatalogBrowse: React.FC = () => {
  const { projectId } = useFlowContext();
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [origin, setOrigin] = useState<DatasetOrigin | "">("");
  const [format, setFormat] = useState<DatasetFormat | "">("");
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const [detailDatasetId, setDetailDatasetId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [defaultsBusyId, setDefaultsBusyId] = useState<string | null>(null);
  // Client-side, unlike the format/origin facets: "in all projects" is a
  // property of the ACCOUNT, and the listing endpoint has no notion of it.
  const [scope, setScope] = useState<"" | "defaults">("");
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const catalog = useDatasetCatalog({ search, sort, origin, format, includeHub: true });
  // The SAME hook the Data Catalog drawer's footer calls, so the register,
  // the cross-surface refresh notification and the OSM layer-count wording
  // cannot drift between the page and the drawer.
  const { importing: importingDataset, importFile: onImportDataset } = useDatasetImport({
    importDataset: catalog.importDataset,
    showToast,
  });

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
  const detailDataset = useMemo(
    () => (detailDatasetId ? catalog.items.find((item) => item.id === detailDatasetId) ?? null : null),
    [catalog.items, detailDatasetId],
  );

  const catalogFacetDatasetTotal = useMemo(
    () => Object.values(catalog.facets.format).reduce((sum, n) => sum + n, 0),
    [catalog.facets.format],
  );

  // How many of the listed datasets are in the account's "all projects" list.
  // Counted off the listing rather than `defaults.size`, so a stale id the
  // listing no longer carries is not advertised as a filterable row.
  const inAllProjectsCount = useMemo(
    () => catalog.items.filter((item) => defaults.has(item.id)).length,
    [catalog.items, defaults],
  );

  const visibleItems = useMemo(
    () =>
      scope === "defaults"
        ? catalog.items.filter((item) => defaults.has(item.id))
        : catalog.items,
    [catalog.items, scope, defaults],
  );

  const reloadDefaults = useCallback(async () => {
    try {
      const resp = await datasetCatalogApi.listDatasetDefaults();
      setDefaults(new Set(resp.datasets));
    } catch {
      // A defaults read must never take the catalog page down with it.
      setDefaults(new Set());
    }
  }, []);

  useEffect(() => {
    void reloadDefaults();
  }, [reloadDefaults]);

  const handleAddToAllProjects = useCallback(
    async (dataset: DatasetCatalogItem) => {
      setDefaultsBusyId(dataset.id);
      try {
        const resp = await datasetCatalogApi.addDatasetToDefaults(dataset.id);
        setDefaults(new Set(resp.datasets));
        notifyDatasetCatalogRefresh();
        await catalog.reload();
        // Say how many it actually reached: "all your projects" is two
        // mechanisms, and only the eager half has a number to report.
        const n = resp.projects.filter((p) => p.ok).length;
        showToast(
          n === 0
            ? `${dataset.title} will be added to new projects.`
            : `Added ${dataset.title} to ${n} project${n === 1 ? "" : "s"}, and to new ones.`,
          "success",
        );
      } catch (err) {
        showToast(`Couldn't add ${dataset.title} to all projects`, "error");
      } finally {
        setDefaultsBusyId(null);
      }
    },
    [catalog.reload, showToast],
  );

  const handleRemoveFromAllProjects = useCallback(
    async (dataset: DatasetCatalogItem) => {
      setDefaultsBusyId(dataset.id);
      try {
        const resp = await datasetCatalogApi.removeDatasetFromDefaults(dataset.id);
        setDefaults(new Set(resp.datasets));
        notifyDatasetCatalogRefresh();
        await catalog.reload();
        showToast(`Removed ${dataset.title} from all projects.`, "success");
      } catch (err) {
        showToast(`Couldn't remove ${dataset.title} from all projects`, "error");
      } finally {
        setDefaultsBusyId(null);
      }
    },
    [catalog.reload, showToast],
  );

  const handleUnpublish = useCallback(
    async (dataset: DatasetCatalogItem) => {
      setPublishingId(dataset.id);
      try {
        await datasetCatalogApi.unpublishDataset(dataset.id, {
          ...(projectId ? { dataflowId: projectId } : {}),
        });
        notifyDatasetCatalogRefresh();
        await catalog.reload();
        showToast(`Unpublished ${dataset.title}.`, "success");
      } catch (err) {
        showToast(`Couldn't unpublish ${dataset.title}`, "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog.reload, projectId, showToast],
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
        showToast(`Couldn't publish ${dataset.title}`, "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog.reload, projectId, showToast],
  );

  return (
    <div className={[styles.page, drawerSlotOpen ? styles.pageWithDrawer : ""].filter(Boolean).join(" ")}>
      <aside className={styles.categoryRail}>
        {/* "By status" leads the rail, as it does on the Node and Agent pages.
            This one opened straight into "By format": the account-level scope
            existed only as a chip down in the filter bar, so the three catalogs
            disagreed about where you look for the same kind of filter. */}
        <p className={styles.railLabel}>By status</p>

        <button
          className={`${styles.railButton} ${scope === "" ? styles.railButtonActive : ""}`}
          type="button"
          onClick={() => setScope("")}
        >
          <span>All datasets</span>
          <span className={styles.railCountBadge}>{catalogFacetDatasetTotal}</span>
        </button>

        <button
          className={`${styles.railButton} ${scope === "defaults" ? styles.railButtonActive : ""}`}
          type="button"
          onClick={() => setScope((prev) => (prev === "defaults" ? "" : "defaults"))}
        >
          <span>In all projects</span>
          <span className={styles.railCount}>{inAllProjectsCount}</span>
        </button>

        <div className={styles.railDivider} />
        <p className={styles.railLabel}>By format</p>

        <button
          className={`${styles.railButton} ${format === "" ? styles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFormat("")}
        >
          {/* "All formats", not "All datasets": the status section above owns
              that label now, and this button only clears the format facet. */}
          <span>All formats</span>
          <span className={styles.railCount}>{catalogFacetDatasetTotal}</span>
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
            <span className={styles.titleCount}>{visibleItems.length}</span>
          </div>
          <p className={styles.pageIntro}>
            Datasets in the shared catalog. Adding one here adds it to{" "}
            <strong>all your projects</strong>, present and future; add it to a single
            project from that project&apos;s Data Catalog.
          </p>
          <div className={styles.headerTools}>
            <input
              className={styles.hubSearch}
              type="search"
              placeholder="Search catalog datasets…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {/* Register-only, exactly like the drawer's footer import: it adds
                an account-level catalog item and attaches it to no project.
                That suits this page, which has no project to attach to. */}
            <CatalogHeaderImport
              label="Import dataset"
              accept={DATASET_IMPORT_ACCEPT}
              busy={importingDataset}
              onPick={(file) => void onImportDataset(file)}
              title="Add a data file to your catalog"
            />
          </div>
        </section>

        <div className={styles.filterBar}>
          <button
            className={`${styles.chip} ${
              format === "" && scope === "" ? styles.chipActive : ""
            }`}
            type="button"
            onClick={() => {
              setFormat("");
              setScope("");
            }}
          >
            All
          </button>
          {/* The peer of the Node catalog's "In all projects" chip. Datasets
              had no account-level scope to filter on until they grew a
              defaults list. */}
          <button
            className={`${styles.chip} ${scope === "defaults" ? styles.chipActive : ""}`}
            type="button"
            onClick={() => setScope((prev) => (prev === "defaults" ? "" : "defaults"))}
          >
            In all projects
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
        {!catalog.loading && !catalog.refreshing && !catalog.error && visibleItems.length === 0 ? (
          <div className={styles.empty}>No datasets match the current filters.</div>
        ) : null}

        <section
          className={[styles.cardGrid, catalog.refreshing ? styles.cardGridRefreshing : ""].join(" ")}
        >
          {visibleItems.map((dataset) => (
            <DataCatalogBrowseCard
              key={`${dataset.origin}:${dataset.id}`}
              dataset={dataset}
              selected={drawerDataset?.id === dataset.id}
              onSelect={() => setSelectedId(dataset.id)}
              onViewDetails={() => setDetailDatasetId(dataset.id)}
              inAllProjects={defaults.has(dataset.id)}
            />
          ))}
        </section>
      </main>

      <DataCatalogBrowseDrawer
        dataset={drawerDataset}
        publishingId={publishingId}
        catalogPublishAllowed={catalogPublishAllowed}
        onPublish={handlePublish}
        onUnpublish={handleUnpublish}
        inAllProjects={drawerDataset != null && defaults.has(drawerDataset.id)}
        defaultsBusy={drawerDataset != null && defaultsBusyId === drawerDataset.id}
        onAddToAllProjects={handleAddToAllProjects}
        onRemoveFromAllProjects={handleRemoveFromAllProjects}
        onClose={() => setSelectedId(null)}
        onViewDetails={(dataset) => setDetailDatasetId(dataset.id)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {detailDatasetId ? (
        <DatasetDetailModal
          datasetId={detailDatasetId}
          fallbackDataset={detailDataset}
          onClose={() => setDetailDatasetId(null)}
        />
      ) : null}
    </div>
  );
};

export default DataCatalogBrowse;
