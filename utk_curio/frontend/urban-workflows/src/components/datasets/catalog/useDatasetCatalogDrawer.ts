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
  datasetDisplayTitle,
  isOsmGroupId,
  notifyDatasetCatalogRefresh,
  useDatasetCatalog,
} from "../../../services/datasetCatalog";
import { buildSaveableLiveOutputs } from "../../../utils/saveOutputDataset";
import { resolveComputedInstallTitle } from "../../../utils/palettePackageFactoryDraft";
import { permanentDeletionNotice } from "../../../services/retentionCopy";
import { dataflowRefFromCatalogItem } from "./dataflowDatasetRef";
import type { DrawerTab } from "./datasetCatalogDrawerTypes";
import { tabOrigin } from "./datasetCatalogDrawerTypes";

/** A pending confirmation (#196, #197). The hook cannot render, so it holds the
 *  question and the drawer component paints it with `ConfirmDialog`. */
export interface DatasetConfirmAction {
  title: string;
  body: string;
  confirmLabel: string;
  destructive: boolean;
  /** Returns the action's promise so callers (and tests) can await it. */
  run: () => Promise<void>;
}

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
  const [confirmAction, setConfirmAction] = useState<DatasetConfirmAction | null>(null);
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
    // No per-key bustCache: notifyDatasetCatalogRefresh invalidates the whole
    // cache before it dispatches, so every key is already gone by the time
    // this listener runs. The old argument busted one key and left the
    // palette's differently-keyed entry stale.
    const onRefresh = () => void catalog.reload();
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

  const performInstall = useCallback(
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
        // One refresh event fans out to every catalog listener — including this
        // hook's own listener, which does the bust-cache reload. Calling
        // catalog.reload here too issued the expensive multi-source listing
        // twice per action (#178).
        notifyDatasetCatalogRefresh();
        showToast(
          isGroup
            ? `Added ${installedItems.length} layers from ${dataset.title} to this dataflow.`
            : `Added ${dataset.title} to this dataflow.`,
          "success",
        );
      } catch (err) {
        showToast((err as Error)?.message || "Could not add dataset.", "error");
      } finally {
        endPendingInstall(dataset.id);
        setBusyId(null);
      }
    },
    [ensureProjectId, setDataflowDatasets, showToast, beginPendingInstall, endPendingInstall],
  );

  // #196: the Data catalog confirms an add too, so all three catalogs agree.
  // The Node catalog's richer InstallPermissionsDialog stays as it is — it has
  // permissions and dependency conflicts to disclose that a dataset does not.
  const onInstall = useCallback(
    (dataset: DatasetCatalogItem) => {
      const title = datasetDisplayTitle(dataset);
      const isGroup = isOsmGroupId(dataset.id);
      const layerCount = isGroup ? (dataset.groupLayerIds ?? []).length : 0;
      setConfirmAction({
        title: `Add ${title}?`,
        body: isGroup
          ? `Add all ${layerCount} layers from ${title} to this dataflow?`
          : `Add ${title} to this dataflow?`,
        confirmLabel: "Add to dataflow",
        destructive: false,
        run: () => performInstall(dataset),
      });
    },
    [performInstall],
  );

  const performUninstall = useCallback(
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
        // Single refresh event; this hook's own listener does the reload (#178).
        notifyDatasetCatalogRefresh();
        const title = datasetDisplayTitle(dataset);
        showToast(
          isGroup
            ? `Removed ${title} (${memberIds.length} layers) from this dataflow.`
            : `Removed ${title} from this dataflow.`,
          "success",
        );
      } catch (err) {
        showToast((err as Error)?.message || "Could not remove dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [ensureProjectId, setDataflowDatasets, showToast],
  );

  /** Would removing this from the dataflow also delete it from the account?
   *
   *  The backend deletes an ``imported.*`` upload's store folder once no other
   *  dataflow references it (``_remove_orphaned_imported_store_dir``), archived
   *  projects included. Computed and source-node datasets are never deleted
   *  this way. Usage is read BEFORE the removal, so the current dataflow is
   *  still counted - one user means this one and nothing else.
   */
  const uninstallAlsoDeletes = useCallback(
    async (dataset: DatasetCatalogItem): Promise<boolean> => {
      const dirName = String(dataset.dirName ?? "");
      if (!dirName.startsWith("imported.")) return false;
      if (dataset.origin === "computed" || dataset.origin === "source_node") return false;
      try {
        const usage = await datasetCatalogApi.datasetUsage(dataset.id);
        return usage.length <= 1;
      } catch {
        // If usage cannot be resolved the backend keeps the folder, so the
        // honest answer is "no deletion" rather than a warning that may be
        // false. The removal itself is unaffected either way.
        return false;
      }
    },
    [],
  );

  // #197 gave the other two catalogs a confirmation for this and left the Data
  // drawer performing it on a single click - the one of the three that can
  // permanently delete a file from the account while doing it.
  const onUninstall = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const title = datasetDisplayTitle(dataset);
      const alsoDeletes = await uninstallAlsoDeletes(dataset);
      setConfirmAction({
        title: `Remove ${title}?`,
        body: alsoDeletes
          ? `Remove ${title} from this dataflow?

No other dataflow uses it, so the uploaded file is also deleted from your Data Catalog. ${permanentDeletionNotice()}`
          : `Remove ${title} from this dataflow?

The dataset stays in your Data Catalog and in any other dataflow using it.`,
        confirmLabel: alsoDeletes ? "Remove and delete" : "Remove",
        destructive: true,
        run: () => performUninstall(dataset),
      });
    },
    [performUninstall, uninstallAlsoDeletes],
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
        // Single refresh event; this hook's own listener does the reload (#178).
        notifyDatasetCatalogRefresh();
        showToast("Dataset published to Data Catalog.", "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not publish dataset.", "error");
      } finally {
        setPublishingId(null);
      }
    },
    [ensureProjectId, liveOutputs, setDataflowDatasets, showToast],
  );

  const performUnpublish = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const title = datasetDisplayTitle(dataset);
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
        // Single refresh event; this hook's own listener does the reload (#178).
        notifyDatasetCatalogRefresh();
        showToast(`${title} unpublished from the Data Catalog.`, "success");
      } catch (err) {
        showToast((err as Error)?.message || "Could not unpublish dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [ensureProjectId, setDataflowDatasets, showToast],
  );

  const onUnpublish = useCallback(
    (dataset: DatasetCatalogItem) => {
      const title = datasetDisplayTitle(dataset);
      setConfirmAction({
        title: `Unpublish ${title}?`,
        body: `Unpublish ${title} from the Data Catalog?\n\nThis removes the catalog listing. Copies already added to dataflows are not removed.`,
        confirmLabel: "Unpublish",
        destructive: true,
        run: () => performUnpublish(dataset),
      });
    },
    [performUnpublish],
  );

  const performDelete = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const title = datasetDisplayTitle(dataset);
      setBusyId(dataset.id);
      try {
        const result = await datasetCatalogApi.deleteDataset(dataset.id);
        if (result?.deleted === false) {
          // Partial failure (#173): refs were stripped but locked files kept
          // the folder alive — keep the row visible and say so honestly.
          notifyDatasetCatalogRefresh();
          showToast(
            `Could not fully delete ${title}: some of its files are still in use. Close anything using them and try again.`,
            "error",
          );
          return;
        }
        const removed = new Set([dataset.id, ...(dataset.groupLayerIds ?? [])].map(String));
        setDataflowDatasets((prev) =>
          prev.filter((row) => !removed.has(String(row?.datasetId || row?.id))),
        );
        // Single refresh event; this hook's own listener does the reload (#178).
        notifyDatasetCatalogRefresh();
        const n = result?.removedFrom?.length ?? 0;
        showToast(
          n > 0
            ? `Deleted ${title} from your Data Catalog (removed from ${n} project${n === 1 ? "" : "s"}).`
            : `Deleted ${title} from your Data Catalog.`,
          "success",
        );
      } catch (err) {
        showToast((err as Error)?.message || "Could not delete dataset.", "error");
      } finally {
        setBusyId(null);
      }
    },
    [setDataflowDatasets, showToast],
  );

  const onDelete = useCallback(
    async (dataset: DatasetCatalogItem) => {
      const title = datasetDisplayTitle(dataset);
      // Delete strips the dataset's references per DATA FLOW (across all
      // projects), so warn with the affected-dataflow count fetched up front —
      // consumerNodeCount both under-warns (installed in 3 projects, wired to
      // 0 nodes) and over-warns (5 nodes in one project) (#177). Fall back to
      // the node-count wording only if the usage lookup fails.
      let usageNote = "";
      try {
        const usage = await datasetCatalogApi.datasetUsage(dataset.id);
        if (usage.length > 0) {
          const nodeCount = usage.reduce((sum, u) => sum + (u.nodeCount ?? 0), 0);
          const nodeNote =
            nodeCount > 0
              ? ` (consumed by ${nodeCount} node${nodeCount === 1 ? "" : "s"})`
              : "";
          usageNote = `\n\nIt is used in ${usage.length} dataflow${usage.length === 1 ? "" : "s"}${nodeNote}; its references there will be removed.`;
        }
      } catch {
        const usageCount = dataset.consumerNodeCount ?? 0;
        if (usageCount > 0) {
          usageNote = `\n\nIt is referenced by ${usageCount} node${usageCount === 1 ? "" : "s"} across your projects; those references will be removed.`;
        }
      }
      // The prefetch above runs *before* the dialog opens, so the body is
      // complete the moment it appears rather than filling in under the user.
      setConfirmAction({
        title: `Delete ${title}?`,
        // The every-dataflow scope is stated unconditionally. It used to depend
        // on `usageNote`, which is empty whenever the usage lookup returns
        // nothing or fails — so the case where the user knows least about the
        // blast radius was the case that said least about it.
        body:
          `Delete ${title} from your Data Catalog?\n\n` +
          `This deletes the dataset itself, and removes it from every dataflow ` +
          `that uses it, not just this one. ${permanentDeletionNotice()}` +
          usageNote,
        confirmLabel: "Delete forever",
        destructive: true,
        run: () => performDelete(dataset),
      });
    },
    [performDelete],
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
            ? `Registered ${count} datasets from ${file.name} in the Data Catalog.`
            : `Registered ${file.name} in the Data Catalog.`,
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
    confirmAction,
    dismissConfirm: useCallback(() => setConfirmAction(null), []),
  };
}
