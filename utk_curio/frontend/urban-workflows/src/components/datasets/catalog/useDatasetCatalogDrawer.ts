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
  useDatasetCatalog,
} from "../../../services/datasetCatalog";
import { flowOutputRefFromRaw } from "../../../utils/flowOutputRef";
import { dataflowRefFromCatalogItem } from "./dataflowDatasetRef";
import type { DrawerTab } from "./datasetCatalogDrawerTypes";
import { tabOrigin } from "./datasetCatalogDrawerTypes";

export function useDatasetCatalogDrawer(presented: boolean) {
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
      list = list.filter((item) => item.origin === "computed" || Boolean(item.producerNodeId));
    }
    return list.filter(matchesSearch);
  }, [catalogItems, tab, debouncedSearch]);

  const installedCount = useMemo(
    () => catalogItems.filter((item) => item.origin !== "hub" || item.installed).length,
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

  const ensureProjectId = useCallback(async (): Promise<string | null> => {
    if (projectId) return projectId;
    try {
      const detail = await saveCurrentProject();
      return (detail as { id?: string } | undefined)?.id || null;
    } catch (err) {
      showToast(
        (err as Error)?.message || "Save the dataflow before installing datasets.",
        "error",
      );
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
          return [...next, dataflowRefFromCatalogItem(installed)];
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
        await catalog.reload();
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

  const onPickImport = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) return;
      importInFlightRef.current = true;
      setBusyId("import");
      try {
        const imported = await catalog.importDataset(file);
        setDataflowDatasets((prev) => {
          const next = prev.filter((row) => (row?.datasetId || row?.id) !== imported.id);
          return [...next, dataflowRefFromCatalogItem(imported)];
        });
        showToast(`Imported ${file.name}.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not import dataset.", "error");
      } finally {
        importInFlightRef.current = false;
        setBusyId(null);
      }
    },
    [catalog, setDataflowDatasets, showToast],
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
