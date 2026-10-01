import { useCallback, useEffect, useMemo, useState } from "react";
import type { PackagePayload, SortMode } from "../../services/packages";
import {
  isNewerPackageVersion,
  matchesSearch,
  primaryCategory,
  sortPackages,
  toApiPayload,
  usePackageCatalog,
  withRestartNotice,
} from "../../services/packages";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";
import { draftFromInstalledPackagePayload } from "../../utils/palettePackageFactoryDraft";
import { useToastContext } from "../../providers/ToastProvider";
import { usePackageArchiveImport } from "../../providers/packages/usePackageArchiveImport";
import type { NodeCatalogFilterTab } from "./nodeCatalogBrowseTypes";

/**
 * The Node Catalog page's view-model (memo dev/143, F3): a thin adapter over
 * `usePackageCatalog({ kind: "defaults" })` — THE catalog hook, shared with the
 * in-canvas drawer — that keeps only the page's own view state: search, sort,
 * the two filters and the selection. Its return shape is unchanged.
 */
export function useNodeCatalogBrowse() {
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<NodeCatalogFilterTab>("all");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedDirName, setSelectedDirName] = useState<string | null | undefined>(undefined);

  const publishDraft = useCallback(
    (row: PackagePayload) => toApiPayload(draftFromInstalledPackagePayload(row)) as Record<string, unknown>,
    [],
  );
  const catalogState = usePackageCatalog({
    scope: { kind: "defaults" },
    showToast,
    refreshRegistry: refreshPackageRegistry,
    publishDraft,
  });
  const {
    catalog,
    installed,
    installedByDir,
    catalogByDir,
    catalogPublishedDirs,
    defaults,
    busy,
    actionError,
    catalogPublishAllowed,
    publishingPackageKey,
    installCandidate,
    installMode,
    conflictReport,
    lastInstallSummary,
    reload,
    reportActionError: reportError,
    dismissActionError,
    dismissInstallSummary,
    probeInstall: onInstall,
    probeUpdate: onUpdate,
    confirmInstall,
    cancelInstall,
    publish: onPublish,
    unpublish,
  } = catalogState;

  const updateCandidates = useMemo(() => {
    return installed.filter((row) => {
      const catRow = catalogByDir.get(row.dirName);
      return catRow != null && isNewerPackageVersion(catRow.version, row.version);
    });
  }, [installed, catalogByDir]);

  const updateCandidateDirs = useMemo(
    () => new Set(updateCandidates.map((p) => p.dirName)),
    [updateCandidates],
  );

  const mergedRows = useMemo(() => {
    const out = new Map<string, PackagePayload>();
    for (const row of installed) out.set(row.dirName, row);
    for (const row of catalog) out.set(row.dirName, row);
    return Array.from(out.values());
  }, [catalog, installed]);

  const bySearch = useMemo(
    () => mergedRows.filter((p) => matchesSearch(p, search)),
    [mergedRows, search],
  );

  const categoryFacetBase = useMemo(() => {
    let b = bySearch;
    if (filter === "installed") {
      b = b.filter((p) => defaults.has(p.dirName));
    }
    return b;
  }, [bySearch, filter, defaults]);

  const categoryCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of categoryFacetBase) {
      const c = primaryCategory(p);
      m.set(c, (m.get(c) ?? 0) + 1);
    }
    return m;
  }, [categoryFacetBase]);

  const sortedCategories = useMemo(
    () => Array.from(categoryCounts.entries()).sort((a, b) => b[1] - a[1]),
    [categoryCounts],
  );

  const quickCategories = useMemo(
    () => sortedCategories.slice(0, 3).map(([k]) => k),
    [sortedCategories],
  );

  const filtered = useMemo(() => {
    let base = categoryFacetBase;
    if (categoryFilter) {
      base = base.filter((p) => primaryCategory(p) === categoryFilter);
    }
    return sortPackages(base, sort);
  }, [categoryFacetBase, categoryFilter, sort]);

  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedDirName(undefined);
      return;
    }
    if (selectedDirName === null) return;
    if (selectedDirName != null && filtered.some((p) => p.dirName === selectedDirName)) return;
    setSelectedDirName(undefined);
  }, [filtered, selectedDirName]);

  const selectedPkg = useMemo(() => {
    if (selectedDirName === null) return null;
    if (selectedDirName != null) {
      return filtered.find((p) => p.dirName === selectedDirName) ?? null;
    }
    return filtered[0] ?? null;
  }, [filtered, selectedDirName]);

  /**
   * Sideload a `.curio.zip` from the catalog PAGE's header, through the SAME
   * hook the Node Catalog drawer's footer uses. This was briefly a second copy
   * of the drawer's logic; it is now one pathway with one difference, expressed
   * as data: no `projectId`, because the page has no dataflow to install into.
   */
  const { importing, importArchive: onImportArchive } = usePackageArchiveImport({
    reload,
    onError: reportError,
    onImported: (pkg, notice, restart) =>
      showToast(
        withRestartNotice(notice ?? `Imported ${pkg?.name ?? "package"}.`, restart),
        notice ? "error" : "success",
      ),
  });

  /** The inverse of `onPublish`, which the page had no way to reach. */
  const onUnpublish = useCallback((dirName: string) => unpublish(dirName), [unpublish]);

  const allCount = bySearch.length;
  const installedCount = bySearch.filter((p) => defaults.has(p.dirName)).length;
  const updatesCount = bySearch.filter((p) => updateCandidateDirs.has(p.dirName)).length;

  const selectedHasUpdate =
    selectedPkg != null &&
    defaults.has(selectedPkg.dirName) &&
    updateCandidateDirs.has(selectedPkg.dirName);

  return {
    search,
    setSearch,
    sort,
    setSort,
    filter,
    setFilter,
    categoryFilter,
    setCategoryFilter,
    selectedDirName,
    setSelectedDirName,
    busy,
    actionError,
    catalogPublishAllowed,
    publishingPackageKey,
    installCandidate,
    installMode,
    conflictReport,
    lastInstallSummary,
    dismissInstallSummary,
    dismissActionError,
    installedByDir,
    catalogByDir,
    catalogPublishedDirs,
    defaults,
    filtered,
    selectedPkg,
    sortedCategories,
    quickCategories,
    allCount,
    installedCount,
    updatesCount,
    selectedHasUpdate,
    onInstall,
    onUpdate,
    importing,
    onImportArchive,
    confirmInstall,
    onPublish,
    onUnpublish,
    cancelInstall,
  };
}
