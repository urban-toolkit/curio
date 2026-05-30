import React, { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faFileImport, faXmark } from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  createDatasetDragPayload,
  DATASET_DRAG_MIME,
  DATASET_FORMAT_LABEL,
  DATASET_ORIGIN_LABEL,
  DatasetCatalogItem,
  DatasetOrigin,
  DatasetSortMode,
  datasetCatalogApi,
  useDatasetCatalog,
} from "../../../services/datasetCatalog";
import styles from "./DatasetCatalogDrawer.module.css";

export interface DatasetCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

type DrawerTab = "featured" | "browse" | "installed" | "computed";

function formatBytes(value?: number | null): string | null {
  if (value == null) return null;
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function relativeTime(iso: string): string {
  const delta = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(delta)) return "recent";
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function datasetMeta(dataset: DatasetCatalogItem): string[] {
  const primaryCount =
    dataset.featureCount != null
      ? `${dataset.featureCount.toLocaleString()} feat.`
      : dataset.rowCount != null
        ? `${dataset.rowCount.toLocaleString()} rows`
        : null;
  return [
    primaryCount,
    formatBytes(dataset.sizeBytes),
    dataset.consumerNodeIds.length > 0 ? `${dataset.consumerNodeIds.length} nodes consume` : "ready",
  ].filter((part): part is string => Boolean(part));
}

function initials(title: string): string {
  const words = title.trim().split(/\s+/).filter(Boolean);
  const seed = words.length > 1 ? `${words[0][0]}${words[1][0]}` : title.slice(0, 2);
  return seed.toUpperCase();
}

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
  const navigate = useNavigate();
  const { projectId, saveCurrentProject, setDataflowDatasets } = useFlowContext();
  const { showToast } = useToastContext();
  const [tab, setTab] = useState<DrawerTab>("browse");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [busyId, setBusyId] = useState<string | null>(null);

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
          return [
            ...next,
            {
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
            },
          ];
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

  const onPickImport = useCallback(async (file: File) => {
    setBusyId("import");
    try {
      const imported = await catalog.importDataset(file);
      setDataflowDatasets((prev) => {
        const next = prev.filter((row) => (row?.datasetId || row?.id) !== imported.id);
        return [
          ...next,
          {
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
          },
        ];
      });
      showToast(`Imported ${file.name}.`, "success");
    } catch (err) {
      showToast((err as Error)?.message || "Could not import dataset.", "error");
    } finally {
      setBusyId(null);
    }
  }, [catalog, setDataflowDatasets, showToast]);

  const onInsert = useCallback((dataset: DatasetCatalogItem) => {
    const path = dataset.path || dataset.uri;
    if (path) void navigator.clipboard?.writeText(path);
    showToast("Drag this dataset onto a Data Loader node to apply path and loader code.", "info");
  }, [showToast]);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  return (
    <div
      className={`${styles.overlayRoot} ${presented ? styles.overlayRootPresented : ""}`}
      data-curio-dataset-catalog-drawer="true"
    >
      <button type="button" className={styles.scrim} aria-label="Close dataset catalog" onClick={onRequestClose} />
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
          {catalog.loading ? <div className={styles.empty}>Loading datasets...</div> : null}
          {!catalog.loading && !catalog.error && items.length === 0 ? (
            <div className={styles.empty}>
              {tab === "installed" || tab === "computed"
                ? "No installed or computed datasets yet."
                : "No datasets match the current filters."}
            </div>
          ) : null}
          <div className={styles.cardList}>
            {items.map((dataset) => (
              <article
                key={`${dataset.origin}:${dataset.id}`}
                className={styles.card}
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData(DATASET_DRAG_MIME, JSON.stringify(createDatasetDragPayload(dataset)));
                  event.dataTransfer.effectAllowed = "copy";
                }}
              >
                <div className={styles.avatar}>{initials(dataset.title)}</div>
                <div className={styles.cardBody}>
                  <div className={styles.cardHeader}>
                    <div>
                      <h3 className={styles.cardTitle}>{dataset.title}</h3>
                      <p className={styles.cardSource}>
                        {DATASET_FORMAT_LABEL[dataset.format]} Loader - {DATASET_ORIGIN_LABEL[dataset.origin]} - {dataset.license || "MIT"}
                      </p>
                    </div>
                    <span className={styles.formatChip}>{DATASET_FORMAT_LABEL[dataset.format]}</span>
                  </div>
                  {dataset.description ? <p className={styles.description}>{dataset.description}</p> : null}
                  <div className={styles.metaRow}>
                    {datasetMeta(dataset).map((part) => <span key={part}>{part}</span>)}
                    <span className={styles.dot} aria-hidden />
                    <span>{relativeTime(dataset.updatedAt)}</span>
                  </div>
                  <div className={styles.tagRow}>
                    {(dataset.tags.length > 0 ? dataset.tags.slice(0, 2) : [dataset.format, "data"]).map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                  <div className={styles.actions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() => {
                        navigate(`/data-hub/${encodeURIComponent(dataset.id)}`);
                        onRequestClose();
                      }}
                    >
                      Open
                    </button>
                    {dataset.installed || dataset.origin !== "hub" ? (
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => onInsert(dataset)}
                      >
                        Insert
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={styles.button}
                        disabled={busyId === dataset.id}
                        onClick={() => void onInstall(dataset)}
                      >
                        {busyId === dataset.id ? "Installing..." : "Install"}
                      </button>
                    )}
                    {dataset.origin === "computed" ? <button type="button" className={styles.button}>Publish</button> : null}
                  </div>
                </div>
              </article>
            ))}
          </div>
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
  );
};
