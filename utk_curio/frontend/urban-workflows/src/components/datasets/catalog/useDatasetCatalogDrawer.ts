import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
  type DragEvent,
} from "react";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  beginDatasetDrag,
  endDatasetDrag,
  writeDatasetDragData,
  DatasetCatalogItem,
  DatasetSortMode,
  DATASET_CATALOG_REFRESH_EVENT,
  datasetCatalogApi,
  isOsmPbfFilename,
  notifyDatasetCatalogRefresh,
  OSM_PBF_IMPORT_MESSAGE,
  useDatasetCatalog,
} from "../../../services/datasetCatalog";
import { buildSaveableLiveOutputs } from "../../../utils/saveOutputDataset";
import { resolveComputedInstallTitle } from "../../../utils/palettePackageFactoryDraft";
import { dataflowRefFromCatalogItem } from "./dataflowDatasetRef";
import type { DrawerTab } from "./datasetCatalogDrawerTypes";
import { tabOrigin } from "./datasetCatalogDrawerTypes";

export function useDatasetCatalogDrawer(presented: boolean) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const importInFlightRef = useRef(false);
  const { projectId, ensureProjectId, setDataflowDatasets, outputs, nodes, defaultSaveOutputDataset, pendingInstalls, beginPendingInstall, endPendingInstall } = useFlowContext();
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

  const liveOutputs = useMemo(() => {
    if (!presented) return undefined;
    return buildSaveableLiveOutputs(outputs, nodes, defaultSaveOutputDataset);
  }, [presented, outputs, nodes, defaultSaveOutputDataset]);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(search), 280);
    return () => window.clearTimeout(handle);
  }, [search]);

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

  useEffect(() => {
    if (!presented) return;
    const onRefresh = () => void catalog.reload({ bustCache: true });
    window.addEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(DATASET_CATALOG_REFRESH_EVENT, onRefresh);
  }, [catalog.reload, presented]);
  // Ephemeral "live outputs" — a node's freshly-computed output that hasn't been
  // installed/saved — surface as computed items with `installed` falsy because
  // the drawer query folds in session liveOutputs. They're transient and clutter
  // every list, so drop them from the drawer entirely; installed computed
  // datasets (installed === true) and hub/imported datasets are kept.
  const visibleItems = useMemo(
    () =>
      catalogItems.filter(
        (item) => !(item.origin === "computed" && item.installed !== true),
      ),
    [catalogItems],
  );

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

    let list = visibleItems;
    if (tab === "featured") {
      list = list.filter((item) => item.origin === "hub" || item.installed).slice(0, 6);
    } else if (tab === "installed") {
      // Only genuinely-installed datasets — matches the palette's
      // isUserInstalledDataset (installed === true). The old `origin !== "hub"`
      // proxy also showed never-installed and just-uninstalled computed/imported
      // rows, so an uninstalled dataset lingered here until a page refresh
      // flipped its origin back to "hub".
      list = list.filter((item) => item.installed === true);
    } else if (tab === "computed") {
      list = list.filter((item) => item.origin === "computed" || Boolean(item.producerNodeId));
    }
    return list.filter(matchesSearch);
  }, [catalogItems, tab, debouncedSearch]);

  const installedCount = useMemo(
    () => catalogItems.filter((item) => item.installed === true).length,
    [catalogItems],
  );

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
    () =>
      detailDatasetId
        ? catalogItems.find((item) => item.id === detailDatasetId) ?? null
        : null,
    [catalogItems, detailDatasetId],
  );

  const onInstall = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const id = await ensureProjectId();
      if (!id) return;
      setBusyId(dataset.id);
      beginPendingInstall({
        key: dataset.id,
        datasetId: dataset.id,
        label: dataset.title,
        producerNodeId: dataset.producerNodeId ?? undefined,
        format: dataset.format,
      });
      try {
        const installed = await datasetCatalogApi.installToDataflow(
          id,
          dataset.id,
          dataset,
          resolveComputedInstallTitle(dataset),
        );
        setDataflowDatasets((prev) => {
          const next = prev.filter((row) => (row?.datasetId || row?.id) !== installed.id);
          return [...next, dataflowRefFromCatalogItem(installed)];
        });
        // Bust the cache so the drawer refetches fresh rather than re-reading
        // the stale cached response, then let the palette (and other catalog
        // listeners) refresh so the newly installed dataset shows up immediately.
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
        showToast(`Installed ${dataset.title}.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not install dataset.", "error");
      } finally {
        endPendingInstall(dataset.id);
        setBusyId(null);
      }
    },
    [catalog, ensureProjectId, setDataflowDatasets, showToast, beginPendingInstall, endPendingInstall],
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
        // Bust the cache so the drawer's own list refetches the post-uninstall
        // state immediately rather than re-reading the stale cached response.
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
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
        const published = await datasetCatalogApi.publishDataset(datasetId, {
          dataflowId: id,
          liveOutputs,
        });
        setDataflowDatasets((prev) => {
          const next = prev.filter((row) => {
            const rowId = row?.datasetId || row?.id;
            return rowId !== datasetId && rowId !== published.id;
          });
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
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
        showToast("Dataset published to Data Catalog.", "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not publish dataset.", "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog, ensureProjectId, liveOutputs, setDataflowDatasets, showToast],
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
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
        showToast(`${dataset.title} unpublished from the Data Catalog.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not unpublish dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [catalog, ensureProjectId, setDataflowDatasets, showToast],
  );

  const onPickImport = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) return;
      // OSM PBF isn't a catalog-importable format (the backend rejects it); it
      // loads through an Autark node. Redirect explicitly instead of firing a
      // silent request that comes back as a generic "unsupported format" error.
      if (isOsmPbfFilename(file.name)) {
        showToast(OSM_PBF_IMPORT_MESSAGE, "warning");
        return;
      }
      importInFlightRef.current = true;
      setBusyId("import");
      // No catalog row exists yet for a brand-new import, so the placeholder is the
      // only in-list feedback until it lands.
      beginPendingInstall({ key: "import", label: file.name });
      try {
        await catalog.importDataset(file);
        // Register-only: importing adds a standalone account-level catalog item;
        // it is NOT attached to the open dataflow, so we do not touch
        // dataflowDatasets. A node/dataflow link is created only on explicit
        // install. Fan out so the imported dataset appears immediately across
        // catalog surfaces (palette provider + dropdown hold separate caches).
        notifyDatasetCatalogRefresh();
        showToast(`Registered ${file.name} in the data catalog.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not import dataset.", "error");
      } finally {
        endPendingInstall("import");
        importInFlightRef.current = false;
        setBusyId(null);
      }
    },
    [catalog, showToast, beginPendingInstall, endPendingInstall],
  );

  const handleDatasetDragStart = useCallback(
    (dataset: DatasetCatalogItem, event: DragEvent<HTMLElement>) => {
      writeDatasetDragData(event.dataTransfer, beginDatasetDrag(dataset));
    },
    [],
  );

  const handleDatasetDragEnd = useCallback(() => {
    endDatasetDrag();
  }, []);

  const openDatasetDetails = useCallback((dataset: DatasetCatalogItem) => {
    setDetailDatasetId(dataset.id);
  }, []);

  const closeDatasetDetails = useCallback(() => {
    setDetailDatasetId(null);
  }, []);

  return {
    fileInputRef,
    projectId,
    tab,
    setTab,
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    busyId,
    publishingId,
    detailDatasetId,
    detailFallback,
    liveOutputs,
    catalog,
    items,
    pendingInstalls,
    tabInstalledCount,
    tabComputedCount,
    startUiTransition,
    onInstall,
    onUninstall,
    onPublish,
    onUnpublish,
    onPickImport,
    handleDatasetDragStart,
    handleDatasetDragEnd,
    openDatasetDetails,
    closeDatasetDetails,
  };
}
