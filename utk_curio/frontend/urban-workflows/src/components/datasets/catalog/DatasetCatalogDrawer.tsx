import React, {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileImport, faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  beginDatasetDrag,
  endDatasetDrag,
  writeDatasetDragData,
  DatasetCatalogItem,
  DatasetOrigin,
  DatasetSortMode,
  DATASET_CATALOG_REFRESH_EVENT,
  datasetCatalogApi,
  useDatasetCatalog,
} from "../../../services/datasetCatalog";
import { DatasetCard } from "./DatasetCard";
import { DatasetDetailModal } from "./DatasetDetailModal";
import { InstalledDatasetsList } from "./InstalledDatasetsList";
import { flowOutputRefFromRaw } from "../../../utils/flowOutputRef";
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
  // Computed tab filters by producerNodeId client-side; do not narrow by origin here.
  return "";
}

export const DatasetCatalogDrawer: React.FC<DatasetCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const importInFlightRef = useRef(false);
  const { projectId, saveCurrentProject, setDataflowDatasets, outputs } = useFlowContext();
  const { showToast } = useToastContext();
  const [tab, setTab] = useState<DrawerTab>("browse");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [pinned, setPinned] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [detailDatasetId, setDetailDatasetId] = useState<string | null>(null);
  const [, startUiTransition] = useTransition();

  // Only track live execution outputs while the drawer is open — avoids
  // refetch churn and main-thread work while the panel is off-screen.
  const liveOutputs = useMemo(() => {
    if (!presented || !outputs || outputs.length === 0) return undefined;
    return outputs
      .map((o) => flowOutputRefFromRaw(o?.nodeId ?? "", o?.output))
      .filter((r): r is NonNullable<typeof r> => r !== null);
  }, [presented, outputs]);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(search), 280);
    return () => window.clearTimeout(handle);
  }, [search]);

  // Tabs filter client-side only — keep a stable fetch so switching tabs is instant.
  const catalog = useDatasetCatalog({
    dataflowId: projectId,
    search: debouncedSearch,
    sort,
    origin: tabOrigin(tab),
    includeHub: true,
    liveOutputs,
    enabled: presented,
  });

  const catalogItems = useDeferredValue(catalog.items);

  // Reload when a node execution auto-installs a computed dataset.
  useEffect(() => {
    if (!presented) return;
    const onRefresh = () => void catalog.reload({ bustCache: true });
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
  }, [catalog.reload, presented]);

  const items = useMemo(() => {
    const needle = debouncedSearch.trim().toLowerCase();
    const matchesSearch = (item: DatasetCatalogItem) => {
      if (!needle) return true;
      const haystack = [
        item.title,
        item.description,
        item.sourceLabel,
        item.format,
        ...(item.tags ?? []),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    };

    let list = catalogItems;
    if (tab === "featured") {
      list = list.filter((item) => item.origin === "hub" || item.installed).slice(0, 6);
    } else if (tab === "installed") {
      list = list.filter((item) => item.origin !== "hub" || item.installed);
    } else if (tab === "computed") {
      list = list.filter(
        (item) => item.origin === "computed" || Boolean(item.producerNodeId),
      );
    }
    return list.filter(matchesSearch);
  }, [catalogItems, tab, debouncedSearch]);

  const installedCount = useMemo(
    () => catalogItems.filter((item) => item.origin !== "hub" || item.installed).length,
    [catalogItems],
  );
  // Count all datasets that were produced by a node (includes published/imported ones).
  const computedCount = useMemo(
    () =>
      catalogItems.filter((item) => item.origin === "computed" || Boolean(item.producerNodeId))
        .length,
    [catalogItems],
  );
  const tabInstalledCount =
    catalogItems.length > 0
      ? installedCount
      : (catalog.facets.origin.imported ?? 0) +
        (catalog.facets.origin.computed ?? 0) +
        (catalog.facets.origin.source_node ?? 0);
  const tabComputedCount =
    catalogItems.length > 0 ? computedCount : (catalog.facets.origin.computed ?? 0);

  const detailFallback = useMemo(
    () => (detailDatasetId ? catalogItems.find((item) => item.id === detailDatasetId) ?? null : null),
    [catalogItems, detailDatasetId],
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
        const installed = await datasetCatalogApi.installToDataflow(id, dataset.id, dataset);
        setDataflowDatasets((prev) => {
          const next = prev.filter((row) => (row?.datasetId || row?.id) !== installed.id);
          // Folder-backed datasets (hub, imported, computed→imported): store only
          // the lean link to the dataset folder.  All metadata is authoritative in
          // the installed manifest.json on disk and is read by the backend API.
          // Fat refs must be avoided here — on the next project save the frontend
          // regenerates spec.trill from this state, so a fat ref would overwrite
          // the correct lean ref the backend already wrote.
          const ref = installed.dirName
            ? {
                datasetId: installed.id,
                dirName: installed.dirName,
                origin: installed.origin,
                ...(installed.producerNodeId ? { producerNodeId: installed.producerNodeId } : {}),
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
        const published = await datasetCatalogApi.publishDataset(datasetId, { dataflowId: id, liveOutputs });
        // Sync the React state so the next auto-save matches backend refs:
        // computed stays computed + publishedToHub; others stay imported + publishedToHub.
        // Remove both the original ref (by old datasetId) and any existing ref
        // for the new catalog id (in case the ID was remapped on publish).
        setDataflowDatasets((prev) => {
          const next = prev.filter((row) => {
            const rowId = row?.datasetId || row?.id;
            return rowId !== datasetId && rowId !== published.id;
          });
          // Computed datasets keep origin="computed" always; track publish state separately.
          const isComputed = Boolean(published.producerNodeId);
          const ref: Record<string, unknown> = {
            datasetId: published.id,
            dirName: published.dirName,
            origin: isComputed ? "computed" : "imported",
            installedAt: new Date().toISOString(),
            publishedToHub: true,
          };
          if (published.producerNodeId) ref.producerNodeId = published.producerNodeId;
          return [...next, ref];
        });
        await catalog.reload();
        showToast("Dataset published to Data Catalog.", "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not publish dataset.", "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog, ensureProjectId, setDataflowDatasets, showToast, liveOutputs],
  );

  const onUnpublish = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const confirmed = window.confirm(
        `Unpublish ${dataset.title} from the Data Catalog?\n\nThis removes the catalog listing. Installed copies in dataflows are not removed.`,
      );
      if (!confirmed) return;
      setBusyId(dataset.id);
      try {
        const id = await ensureProjectId();
        await datasetCatalogApi.unpublishDataset(dataset.id, { dataflowId: id });
        // Revert the ref's origin in React state. Computed datasets stay "computed";
        // non-computed hub datasets revert to "imported". Keep dirName — it now
        // points to the user's local copy (preserved by the backend unpublish routine).
        setDataflowDatasets((prev) =>
          prev.map((row) => {
            const rowId = row?.datasetId || row?.id;
            if (rowId !== dataset.id) return row;
            const isComputed = Boolean(row?.producerNodeId ?? dataset.producerNodeId);
            if (isComputed) {
              return { ...row, origin: "computed", publishedToHub: false };
            }
            return { ...row, origin: "imported", publishedToHub: false };
          }),
        );
        await catalog.reload();
        showToast(`${dataset.title} unpublished from the Data Catalog.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not unpublish dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [catalog, ensureProjectId, setDataflowDatasets, showToast],
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
    writeDatasetDragData(event.dataTransfer, beginDatasetDrag(dataset));
  }, []);

  const handleDatasetDragEnd = useCallback(() => {
    endDatasetDrag();
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
        aria-hidden={!presented}
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
            <h2 id="dataset-catalog-title" className={styles.title}>Data Catalog</h2>
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
            onChange={(event) => {
              const value = event.target.value;
              startUiTransition(() => setSearch(value));
            }}
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
            onClick={() => startUiTransition(() => setTab("featured"))}
          >
            Featured
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === "browse" ? styles.tabActive : ""}`}
            onClick={() => startUiTransition(() => setTab("browse"))}
          >
            Browse all
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === "installed" ? styles.tabActive : ""}`}
            onClick={() => startUiTransition(() => setTab("installed"))}
          >
            Installed <span>{tabInstalledCount}</span>
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === "computed" ? styles.tabActive : ""}`}
            onClick={() => startUiTransition(() => setTab("computed"))}
          >
            Computed <span>{tabComputedCount}</span>
          </button>
        </div>

        <main className={styles.content}>
          {catalog.error ? <div className={styles.error}>{catalog.error}</div> : null}
          {/* Show full loading state only on initial load (no items yet).
              Background refreshes keep existing items visible. */}
          {catalog.loading && items.length === 0 ? (
            <div className={styles.skeletonList} aria-busy="true" aria-label="Loading datasets">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className={styles.skeletonCard} />
              ))}
            </div>
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
                onDragEnd={handleDatasetDragEnd}
                refreshing={false}
              />
            )
          ) : (
            <>
              {!catalog.error ? (
                <p className={styles.sectionLabel}>{TAB_LABEL[tab]}</p>
              ) : null}
              {!catalog.loading && !catalog.error && items.length === 0 ? (
                <div className={styles.empty}>
                  {tab === "computed"
                    ? "No computed datasets yet. Run a dataflow node that outputs a table — it will appear here and be installed automatically."
                    : "No datasets match the current filters."}
                </div>
              ) : null}
              <div className={styles.cardList}>
                {items.map((dataset) => {
                  const isComputedInstalled =
                    dataset.origin === "computed" && dataset.installed === true;
                  const isInstalled =
                    isComputedInstalled ||
                    (!isComputedInstalled &&
                      (dataset.installed === true ||
                        (dataset.origin !== "hub" && dataset.origin !== "computed")));
                  const isPublished = dataset.origin === "hub" || dataset.publishedToHub === true;
                  return (
                    <DatasetCard
                      key={`${dataset.origin}:${dataset.id}`}
                      dataset={dataset}
                      isInstalled={isInstalled}
                      isPublished={isPublished}
                      busy={busyId === dataset.id || publishingId === dataset.id}
                      publishingId={publishingId}
                      onDragStart={(event) => handleDatasetDragStart(dataset, event)}
                      onDragEnd={handleDatasetDragEnd}
                      onInstall={(row) => void onInstall(row)}
                      onUninstall={
                        projectId && !isComputedInstalled
                          ? (row) => void onUninstall(row)
                          : undefined
                      }
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
          liveOutputs={liveOutputs}
          fallbackDataset={detailFallback}
          onClose={closeDatasetDetails}
        />
      ) : null}
    </>
  );
};
