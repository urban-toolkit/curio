import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { packagesApi } from "../../services/packages";
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
import { DataCatalogBrowseCard } from "./DataCatalogBrowseCard";
import { DataCatalogBrowseDrawer } from "./DataCatalogBrowseDrawer";
import {
  useDatasetDetails,
  viewDatasetDetailsToast,
} from "../../components/datasets/catalog/datasetDetailsContext";
import { ORIGIN_FILTERS, quickFormatFilters } from "./dataCatalogBrowseConstants";
import { CatalogHeaderImport } from "../catalog/CatalogHeaderImport";
import { CatalogPageHeader } from "../catalog/CatalogPageHeader";
import { CatalogRail } from "../catalog/CatalogRail";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import {
  datasetCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import styles from "../catalog/CatalogBrowseLayout.module.css";

/** A failed action says why, as the Agent Catalog's do: "Couldn't X: <reason>". */
function withReason(text: string, err: unknown): string {
  const reason = err instanceof Error ? err.message.trim() : "";
  return reason ? `${text}: ${reason}` : text;
}

export const DataCatalogBrowse: React.FC = () => {
  const { projectId } = useFlowContext();
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DatasetSortMode>("recent");
  const [origin, setOrigin] = useState<DatasetOrigin | "">("");
  const [format, setFormat] = useState<DatasetFormat | "">("");
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  // `/catalog/data/<id>` is this page with that dataset's details open, so a
  // link to a dataset lands where every "View details" does.
  const { datasetId: linkedDatasetId } = useParams<{ datasetId?: string }>();
  const navigate = useNavigate();
  const { openDatasetDetails } = useDatasetDetails();
  useEffect(() => {
    if (!linkedDatasetId) return;
    openDatasetDetails(decodeURIComponent(linkedDatasetId), {
      // Back to the plain page, so a reload does not reopen what was closed.
      onClose: () => navigate("/catalog/data", { replace: true }),
    });
    // `navigate` is not a reason to reopen: only a different link is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedDatasetId, openDatasetDetails]);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [defaultsBusyId, setDefaultsBusyId] = useState<string | null>(null);
  // Right-click. The card reports the event, the grid owns the menu - the same
  // division the projects page has used all along, and which the three catalog
  // pages had no equivalent of until #285.
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    dataset: DatasetCatalogItem;
  } | null>(null);
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
    openDatasetDetails,
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
  const viewDetails = (dataset: DatasetCatalogItem) =>
    openDatasetDetails(dataset.id, {
      fallbackDataset: dataset,
      inAllProjects: defaults.has(dataset.id),
    });

  const catalogFacetDatasetTotal = useMemo(
    () => Object.values(catalog.facets.format).reduce((sum, n) => sum + n, 0),
    [catalog.facets.format],
  );

  // The rail's format rows are the formats that hold datasets, read off the
  // facet counts - never a hand-maintained list (#232). `format` is a
  // dependency so the selected row stays pinned when a search zeroes its count.
  const quickFormats = useMemo(
    () => quickFormatFilters(catalog.facets.format, format),
    [catalog.facets.format, format],
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
          viewDatasetDetailsToast(openDatasetDetails, dataset.id, {
            fallbackDataset: dataset,
            inAllProjects: true,
          }),
        );
      } catch (err) {
        showToast(withReason(`Couldn't add ${dataset.title} to all projects`, err), "error");
      } finally {
        setDefaultsBusyId(null);
      }
    },
    [catalog.reload, showToast, openDatasetDetails],
  );

  const handleRemoveFromAllProjects = useCallback(
    async (dataset: DatasetCatalogItem) => {
      setDefaultsBusyId(dataset.id);
      try {
        const resp = await datasetCatalogApi.removeDatasetFromDefaults(dataset.id);
        setDefaults(new Set(resp.datasets));
        notifyDatasetCatalogRefresh();
        await catalog.reload();
        showToast(
          `Removed ${dataset.title} from all projects.`,
          "success",
          viewDatasetDetailsToast(openDatasetDetails, dataset.id, {
            fallbackDataset: dataset,
            inAllProjects: false,
          }),
        );
      } catch (err) {
        showToast(withReason(`Couldn't remove ${dataset.title} from all projects`, err), "error");
      } finally {
        setDefaultsBusyId(null);
      }
    },
    [catalog.reload, showToast, openDatasetDetails],
  );

  const runDatasetAction = (id: CatalogCardActionId, dataset: DatasetCatalogItem) => {
    switch (id) {
      case "add-to-all-projects":
        void handleAddToAllProjects(dataset);
        return;
      case "remove-from-all-projects":
        void handleRemoveFromAllProjects(dataset);
        return;
      case "view-details":
        viewDetails(dataset);
        return;
      // A dataset is never offered the package catalog's update.
      case "update-all-projects":
        return;
    }
  };

  const handleUnpublish = useCallback(
    async (dataset: DatasetCatalogItem) => {
      setPublishingId(dataset.id);
      try {
        await datasetCatalogApi.unpublishDataset(dataset.id, {
          ...(projectId ? { dataflowId: projectId } : {}),
        });
        notifyDatasetCatalogRefresh();
        await catalog.reload();
        showToast(
          `Unpublished ${dataset.title}.`,
          "success",
          viewDatasetDetailsToast(openDatasetDetails, dataset.id, { fallbackDataset: dataset }),
        );
      } catch (err) {
        showToast(withReason(`Couldn't unpublish ${dataset.title}`, err), "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog.reload, projectId, showToast, openDatasetDetails],
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
        showToast(
          `Published ${dataset.title}.`,
          "success",
          viewDatasetDetailsToast(openDatasetDetails, dataset.id, { fallbackDataset: dataset }),
        );
      } catch (err) {
        showToast(withReason(`Couldn't publish ${dataset.title}`, err), "error");
      } finally {
        setPublishingId(null);
      }
    },
    [catalog.reload, projectId, showToast, openDatasetDetails],
  );

  return (
    <div className={[styles.page, drawerSlotOpen ? styles.pageWithDrawer : ""].filter(Boolean).join(" ")}>
      <CatalogRail
        ariaLabel="Filter datasets"
        all={{
          label: "All datasets",
          count: catalogFacetDatasetTotal,
          active: scope === "" && format === "" && origin === "",
          onClick: () => {
            setScope("");
            setFormat("");
            setOrigin("");
          },
        }}
        scope={{
          label: "In all projects",
          count: inAllProjectsCount,
          active: scope === "defaults",
          onClick: () => setScope((prev) => (prev === "defaults" ? "" : "defaults")),
        }}
        sections={[
          {
            key: "format",
            label: "By format",
            entries: quickFormats.map((key) => ({
              value: key,
              label: DATASET_FORMAT_LABEL[key],
              count: catalog.facets.format[key] ?? 0,
              active: format === key,
              onClick: () => setFormat((prev) => (prev === key ? "" : key)),
              dotClassName: styles[`dot_${key}`] ?? "",
            })),
          },
          {
            key: "origin",
            label: "By origin",
            entries: ORIGIN_FILTERS.map((key) => ({
              value: key,
              label: DATASET_ORIGIN_LABEL[key],
              count:
                key === "imported"
                  ? facetImportedTotal(catalog.facets.origin)
                  : catalog.facets.origin[key] ?? 0,
              active: origin === key,
              onClick: () => setOrigin((prev) => (prev === key ? "" : key)),
            })),
          },
        ]}
      />

      <main className={styles.browseMain}>
        <CatalogPageHeader
          kind="dataset"
          iconTitle="Dataset catalog"
          title="Data Catalog"
          count={visibleItems.length}
          intro={
            <>
              Datasets in the shared catalog. Adding one here adds it to{" "}
              <strong>all your projects</strong>, present and future; add it to a single
              project from that project&apos;s Data Catalog.
            </>
          }
          viewTools={
            <select
              className={styles.sortSelect}
              aria-label="Sort datasets"
              value={sort}
              onChange={(e) => setSort(e.target.value as DatasetSortMode)}
            >
              <option value="recent">Sort: Recent activity</option>
              <option value="name">Sort: Name</option>
            </select>
          }
        >
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
        </CatalogPageHeader>

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
              onViewDetails={() => viewDetails(dataset)}
              inAllProjects={defaults.has(dataset.id)}
              onContextMenu={(e) => {
                e.preventDefault();
                // Select first: the menu acts on this dataset, so the drawer
                // beside it should not still be describing another one.
                setSelectedId(dataset.id);
                setContextMenu({ x: e.clientX, y: e.clientY, dataset });
              }}
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
        onViewDetails={viewDetails}
        onLayoutChange={setDrawerSlotOpen}
      />

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Dataset actions"
          items={datasetCardActions({
            inAllProjects: defaults.has(contextMenu.dataset.id),
          })}
          onSelect={(id) => runDatasetAction(id as CatalogCardActionId, contextMenu.dataset)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

    </div>
  );
};

export default DataCatalogBrowse;
