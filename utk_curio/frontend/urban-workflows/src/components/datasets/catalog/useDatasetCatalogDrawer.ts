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
  isOsmGroupId,
  notifyDatasetCatalogRefresh,
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
    // Fold an OSM import's per-layer datasets into one bundle-shaped group card
    // + tabbed detail. The palette (separate hook) keeps individual layers.
    groupOsm: true,
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
  // Computed node outputs are account-level Data Catalog assets: once generated
  // they are saved to the user's store (a real ``dirName``) and shown here as
  // available — not installed — items so they can be installed into a project
  // later. Only a genuinely *ephemeral* live output — a session-only row folded
  // in from ``liveOutputs`` that has NOT been persisted (no store folder) — is
  // transient noise and dropped. Persisted computed datasets (with a
  // ``dirName``), installed datasets, and hub/imported datasets are all kept.
  const visibleItems = useMemo(
    () =>
      catalogItems.filter(
        (item) =>
          !(item.origin === "computed" && item.installed !== true && !item.dirName),
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
      visibleItems.filter((item) => item.origin === "computed" || Boolean(item.producerNodeId))
        .length,
    [visibleItems],
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
        const isGroup = isOsmGroupId(dataset.id);
        // An OSM group's id is synthetic — install each real per-layer dataset
        // so their dataflow refs (which feed the saved spec) stay accurate.
        const memberIds = isGroup ? dataset.groupLayerIds ?? [] : [dataset.id];
        const installedItems: DatasetCatalogItem[] = [];
        for (const memberId of memberIds) {
          installedItems.push(
            await datasetCatalogApi.installToDataflow(
              id,
              memberId,
              isGroup ? undefined : dataset,
              isGroup ? undefined : resolveComputedInstallTitle(dataset),
            ),
          );
        }
        setDataflowDatasets((prev) => {
          const installedIds = new Set(installedItems.map((it) => it.id));
          const next = prev.filter(
            (row) => !installedIds.has(String(row?.datasetId || row?.id)),
          );
          return [...next, ...installedItems.map(dataflowRefFromCatalogItem)];
        });
        // Bust the cache so the drawer refetches fresh rather than re-reading
        // the stale cached response, then let the palette (and other catalog
        // listeners) refresh so the newly installed dataset shows up immediately.
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
        showToast(
          isGroup
            ? `Installed ${installedItems.length} layers from ${dataset.title}.`
            : `Installed ${dataset.title}.`,
          "success",
        );
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
        const isGroup = isOsmGroupId(dataset.id);
        const memberIds = isGroup ? dataset.groupLayerIds ?? [] : [dataset.id];
        for (const memberId of memberIds) {
          try {
            await datasetCatalogApi.uninstallFromDataflow(id, memberId);
          } catch {
            // A layer that wasn't installed is fine during a group uninstall.
            if (!isGroup) throw new Error("Could not remove dataset.");
          }
        }
        setDataflowDatasets((prev) => {
          const removed = new Set(memberIds.map(String));
          return prev.filter((row) => !removed.has(String(row?.datasetId || row?.id)));
        });
        // Bust the cache so the drawer's own list refetches the post-uninstall
        // state immediately rather than re-reading the stale cached response.
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
        showToast(
          isGroup
            ? `Removed ${dataset.title} (${memberIds.length} layers) from this dataflow.`
            : `Removed ${dataset.title} from this dataflow.`,
          "success",
        );
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

  const onDelete = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const usageCount = dataset.consumerNodeCount ?? 0;
      const usageNote =
        usageCount > 0
          ? `\n\nIt is referenced by ${usageCount} node${usageCount === 1 ? "" : "s"} across your projects; those references will be removed.`
          : "";
      const confirmed = window.confirm(
        `Delete ${dataset.title} from your Data Catalog?\n\nThis permanently removes the dataset. It is not just uninstalled from this project.${usageNote}`,
      );
      if (!confirmed) return;
      setBusyId(dataset.id);
      try {
        const result = await datasetCatalogApi.deleteDataset(dataset.id);
        const removed = new Set([dataset.id, ...(dataset.groupLayerIds ?? [])].map(String));
        setDataflowDatasets((prev) =>
          prev.filter((row) => !removed.has(String(row?.datasetId || row?.id))),
        );
        await catalog.reload({ bustCache: true });
        notifyDatasetCatalogRefresh();
        const n = result?.removedFrom?.length ?? 0;
        showToast(
          n > 0
            ? `Deleted ${dataset.title} from your Data Catalog (removed from ${n} project${n === 1 ? "" : "s"}).`
            : `Deleted ${dataset.title} from your Data Catalog.`,
          "success",
        );
      } catch (err) {
        showToast((err as Error)?.message || "Could not delete dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [catalog, setDataflowDatasets, showToast],
  );

  const onPickImport = useCallback(
    async (file: File) => {
      if (importInFlightRef.current) return;
      importInFlightRef.current = true;
      setBusyId("import");
      // No catalog row exists yet for a brand-new import, so the placeholder is the
      // only in-list feedback until it lands.
      beginPendingInstall({ key: "import", label: file.name });
      try {
        const imported = await catalog.importDataset(file);
        // Register-only: importing adds standalone account-level catalog items;
        // they are NOT attached to the open dataflow, so we do not touch
        // dataflowDatasets. A node/dataflow link is created only on explicit
        // install. Fan out so the imported dataset(s) appear immediately across
        // catalog surfaces (palette provider + dropdown hold separate caches).
        notifyDatasetCatalogRefresh();
        // An OSM PBF registers one dataset per layer; report the count.
        const count = imported?.importedDatasetCount ?? 1;
        showToast(
          count > 1
            ? `Registered ${count} datasets from ${file.name} in the data catalog.`
            : `Registered ${file.name} in the data catalog.`,
          "success",
        );
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
    onDelete,
    onPickImport,
    handleDatasetDragStart,
    handleDatasetDragEnd,
    openDatasetDetails,
    closeDatasetDetails,
  };
}
