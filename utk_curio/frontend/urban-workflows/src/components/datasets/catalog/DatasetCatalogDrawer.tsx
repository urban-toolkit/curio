import React, { useCallback, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileImport, faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  createDatasetDragPayload,
  DATASET_DRAG_MIME,
  DatasetCatalogItem,
  DatasetOrigin,
  DatasetSortMode,
  datasetCatalogApi,
  useDatasetCatalog,
} from "../../../services/datasetCatalog";
import { DatasetCard } from "./DatasetCard";
import { DatasetDetailModal } from "./DatasetDetailModal";
import { InstalledDatasetsList } from "./InstalledDatasetsList";
import styles from "./DatasetCatalogDrawer.module.css";

export interface DatasetCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

type DrawerTab = "featured" | "browse" | "installed" | "computed";

const TAB_LABEL: Record<DrawerTab, string> = {
  featured: "Featured",
  browse: "Browse",
  installed: "Installed",
  computed: "Computed",
};

function tabOrigin(tab: DrawerTab): DatasetOrigin | "" {
  return tab === "computed" ? "computed" : "";
}

export const DatasetCatalogDrawer: React.FC<DatasetCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const importInFlightRef = useRef(false);
  const { projectId, saveCurrentProject, setDataflowDatasets } = useFlowContext();
  const { showToast } = useToastContext();
  const [tab, setTab] = useState<DrawerTab>("browse");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [pinned, setPinned] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [detailDatasetId, setDetailDatasetId] = useState<string | null>(null);

  const includeHub = tab === "featured" || tab === "browse";
  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    search,
    sort,
    origin: tabOrigin(tab),
    includeHub,
  });

  const items = useMemo(() => {
    if (tab === "featured") {
      return catalog.items.filter((item) => item.origin === "hub" || item.installed).slice(0, 6);
    }
    if (tab === "installed") {
      return catalog.items.filter((item) => item.origin !== "hub" || item.installed);
    }
    if (tab === "computed") {
      return catalog.items.filter((item) => item.origin === "computed");
    }
    return catalog.items;
  }, [catalog.items, tab]);

  const installedCount = useMemo(
    () => catalog.items.filter((item) => item.origin !== "hub" || item.installed).length,
    [catalog.items],
  );
  const computedCount = catalog.facets.origin.computed ?? 0;
  const detailFallback = useMemo(
    () => (detailDatasetId ? catalog.items.find((item) => item.id === detailDatasetId) ?? null : null),
    [catalog.items, detailDatasetId],
  );

  const ensureProjectId = useCallback(async (): Promise<string | null> => {
    if (projectId) return projectId;
    try {
      const detail = await saveCurrentProject();
      return (detail as { id?: string } | undefined)?.id || null;
    } catch (err) {
      showToast((err as Error)?.message || "Save the dataflow before installing datasets.", "error");
      return null;
    }
  }, [projectId, saveCurrentProject, showToast]);

  const onInstall = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const id = await ensureProjectId();
      if (!id) return;
      setBusyId(dataset.id);
      try {
        const installed = await datasetCatalogApi.installToDataflow(id, dataset.id);
        setDataflowDatasets((prev) => {
          const next = prev.filter((row) => (row?.datasetId || row?.id) !== installed.id);
          // Hub datasets: store only the lean link to the folder; all metadata
          // lives in the installed manifest and is read by the backend API.
          const ref =
            installed.origin === "hub" && installed.dirName
              ? {
                  datasetId: installed.id,
                  dirName: installed.dirName,
                  origin: "hub" as const,
                  installedAt: new Date().toISOString(),
                }
              : {
                  datasetId: installed.id,
                  title: installed.title,
                  description: installed.description,
                  origin: installed.origin,
                  uri: installed.uri,
                  path: installed.path,
                  format: installed.format,
                  sizeBytes: installed.sizeBytes,
                  rowCount: installed.rowCount,
                  featureCount: installed.featureCount,
                  sourceLabel: installed.sourceLabel,
                  tags: installed.tags,
                  updatedAt: installed.updatedAt,
                  installedAt: new Date().toISOString(),
                };
          return [...next, ref];
        });
        await catalog.reload();
        showToast(`Installed ${dataset.title}.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not install dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [catalog, ensureProjectId, setDataflowDatasets, showToast],
  );

  const onUninstall = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const id = await ensureProjectId();
      if (!id) return;
      setBusyId(dataset.id);
      try {
        await datasetCatalogApi.uninstallFromDataflow(id, dataset.id);
        setDataflowDatasets((prev) =>
          prev.filter((row) => (row?.datasetId || row?.id) !== dataset.id),
        );
        await catalog.reload();
        showToast(`Removed ${dataset.title} from this dataflow.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not remove dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [catalog, ensureProjectId, setDataflowDatasets, showToast],
  );

  const onPublish = useCallback(
    async (datasetId: string) => {
      const id = await ensureProjectId();
      if (!id) return;
      setPublishingId(datasetId);
      try {
        await datasetCatalogApi.publishDataset(datasetId, { dataflowId: id });
        await catalog.reload();
        showToast("Dataset published to Data Hub.", "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not publish dataset.", "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog, ensureProjectId, showToast],
  );

  const onUnpublish = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const confirmed = window.confirm(
        `Unpublish ${dataset.title} from the Data Hub?\n\nThis removes the hub listing. Installed copies in dataflows are not removed.`,
      );
      if (!confirmed) return;
      setBusyId(dataset.id);
      try {
        // Hub unpublish API is not wired yet; surface intent until backend lands.
        showToast(`${dataset.title} unpublish is not available yet.`, "info");
      } finally {
        setBusyId(null);
      }
    },
    [showToast],
  );

  const onPickImport = useCallback(async (file: File) => {
    if (importInFlightRef.current) return;
    importInFlightRef.current = true;
    setBusyId("import");
    try {
      const imported = await catalog.importDataset(file);
      setDataflowDatasets((prev) => {
        const next = prev.filter((row) => (row?.datasetId || row?.id) !== imported.id);
        // Imported datasets now live in the user datasets folder with a manifest —
        // store only the lean ref, same as hub datasets.
        const ref =
          imported.dirName
            ? {
                datasetId: imported.id,
                dirName: imported.dirName,
                origin: imported.origin,
                installedAt: new Date().toISOString(),
              }
            : {
                datasetId: imported.id,
                title: imported.title,
                description: imported.description,
                origin: imported.origin,
                uri: imported.uri,
                path: imported.path,
                format: imported.format,
                sizeBytes: imported.sizeBytes,
                rowCount: imported.rowCount,
                featureCount: imported.featureCount,
                sourceLabel: imported.sourceLabel,
                tags: imported.tags,
                updatedAt: imported.updatedAt,
                installedAt: new Date().toISOString(),
              };
        return [...next, ref];
      });
      showToast(`Imported ${file.name}.`, "success");
    } catch (err) {
      showToast((err as Error)?.message || "Could not import dataset.", "error");
    } finally {
      importInFlightRef.current = false;
      setBusyId(null);
    }
  }, [catalog, setDataflowDatasets, showToast]);

  const handleDatasetDragStart = useCallback((dataset: DatasetCatalogItem, event: React.DragEvent<HTMLElement>) => {
    event.dataTransfer.setData(DATASET_DRAG_MIME, JSON.stringify(createDatasetDragPayload(dataset)));
    event.dataTransfer.effectAllowed = "copy";
  }, []);

  const openDatasetDetails = useCallback((dataset: DatasetCatalogItem) => {
    setDetailDatasetId(dataset.id);
  }, []);

  const closeDatasetDetails = useCallback(() => {
    setDetailDatasetId(null);
  }, []);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  return (
    <>
      <div
        className={`${styles.overlayRoot} ${presented ? styles.overlayRootPresented : ""}`}
        data-curio-dataset-catalog-drawer="true"
      >
      <button type="button" className={styles.scrim} aria-label="Close dataset catalog" onClick={() => { if (!pinned) onRequestClose(); }} />
      <aside
        ref={drawerRef}
        className={styles.drawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby="dataset-catalog-title"
        tabIndex={-1}
        onTransitionEnd={handleDrawerTransitionEnd}
      >
        <header className={styles.header}>
          <button
            type="button"
            className={`${styles.pinButton} ${pinned ? styles.pinButtonActive : ""}`}
            aria-label={pinned ? "Unpin drawer" : "Pin drawer open"}
            aria-pressed={pinned}
            title={pinned ? "Unpin drawer" : "Pin drawer (scrim won't close)"}
            onClick={() => setPinned((v) => !v)}
          >
            <FontAwesomeIcon icon={faThumbtack} aria-hidden />
          </button>
          <div className={styles.titleBlock}>
            <h2 id="dataset-catalog-title" className={styles.title}>Data catalog</h2>
            <p className={styles.subtitle}>Datasets available to this dataflow.</p>
          </div>
          <button className={styles.closeButton} type="button" onClick={onRequestClose} aria-label="Close">
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </header>

        <div className={styles.searchBar}>
          <input
            className={styles.searchInput}
            type="search"
            placeholder="Search datasets, sources..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className={styles.sortSelect}
            value={sort}
            aria-label="Sort datasets"
            onChange={(event) => setSort(event.target.value as DatasetSortMode)}
          >
            <option value="recent">Sort: New</option>
            <option value="name">Sort: Name</option>
          </select>
        </div>

        <div className={styles.tabs}>
          <button
            type="button"
            className={`${styles.tab} ${tab === "featured" ? styles.tabActive : ""}`}
            onClick={() => setTab("featured")}
          >
            Featured
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === "browse" ? styles.tabActive : ""}`}
            onClick={() => setTab("browse")}
          >
            Browse all
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === "installed" ? styles.tabActive : ""}`}
            onClick={() => setTab("installed")}
          >
            Installed <span>{installedCount}</span>
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === "computed" ? styles.tabActive : ""}`}
            onClick={() => setTab("computed")}
          >
            Computed <span>{computedCount}</span>
          </button>
        </div>

        <main className={styles.content}>
          {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
          {/* Show full loading state only on initial load (no items yet).
              Background refreshes keep existing items visible. */}
          {catalog.loading && items.length === 0 ? (
            <div className={styles.empty}>Loading datasets...</div>
          ) : null}
          {tab === "installed" ? (
            !catalog.loading && !catalog.error && items.length === 0 ? (
              <div className={styles.empty}>No datasets installed in this dataflow yet.</div>
            ) : (
              <InstalledDatasetsList
                datasets={items}
                busy={busyId != null || publishingId != null}
                publishingId={publishingId}
                onUninstall={projectId ? (dataset) => void onUninstall(dataset) : undefined}
                onPublish={(datasetId) => void onPublish(datasetId)}
                onDragStart={handleDatasetDragStart}
                refreshing={catalog.refreshing}
              />
            )
          ) : (
            <>
              {!catalog.error ? (
                <p className={styles.sectionLabel}>{TAB_LABEL[tab]}</p>
              ) : null}
              {!catalog.loading && !catalog.error && items.length === 0 ? (
                <div className={styles.empty}>No datasets match the current filters.</div>
              ) : null}
              <div
                className={styles.cardList}
                style={catalog.refreshing ? { opacity: 0.6, pointerEvents: "none", transition: "opacity 0.15s" } : { transition: "opacity 0.15s" }}
              >
                {items.map((dataset) => {
                  const isInstalled = dataset.installed === true || dataset.origin !== "hub";
                  const isPublished = dataset.origin === "hub";
                  return (
                    <DatasetCard
                      key={`${dataset.origin}:${dataset.id}`}
                      dataset={dataset}
                      isInstalled={isInstalled}
                      isPublished={isPublished}
                      busy={busyId === dataset.id || publishingId === dataset.id}
                      publishingId={publishingId}
                      onDragStart={(event) => handleDatasetDragStart(dataset, event)}
                      onInstall={(row) => void onInstall(row)}
                      onUninstall={projectId ? (row) => void onUninstall(row) : undefined}
                      onUnpublish={
                        isPublished && isInstalled
                          ? (row) => void onUnpublish(row)
                          : undefined
                      }
                      onPublish={(datasetId) => void onPublish(datasetId)}
                      onOpenDetails={openDatasetDetails}
                    />
                  );
                })}
              </div>
            </>
          )}
          <div className={styles.assistNote}>
            <strong>Shared dataflow environment</strong>
            <span>Drag a dataset onto a loader node to fill path, schema, ports, and required loader code.</span>
          </div>
        </main>

        <footer className={styles.footer}>
          <input
            ref={fileInputRef}
            className={styles.fileInput}
            type="file"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file) void onPickImport(file);
              event.currentTarget.value = "";
            }}
          />
          <button
            type="button"
            className={styles.importButton}
            disabled={busyId === "import"}
            onClick={() => fileInputRef.current?.click()}
          >
            <FontAwesomeIcon icon={faFileImport} /> {busyId === "import" ? "Importing..." : "Import dataset"}
          </button>
        </footer>
      </aside>
      </div>

      {detailDatasetId ? (
        <DatasetDetailModal
          datasetId={detailDatasetId}
          dataflowId={projectId}
          fallbackDataset={detailFallback}
          onClose={closeDatasetDetails}
        />
      ) : null}
    </>
  );
};
