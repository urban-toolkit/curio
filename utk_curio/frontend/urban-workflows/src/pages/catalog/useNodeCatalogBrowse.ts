import { useCallback, useEffect, useMemo, useState } from "react";
import type { PackageKind, PackagePayload, SortMode } from "../../services/packages";
import {
  MODEL_RUNTIME_LABEL,
  MODEL_TYPE_LABEL,
  catalogAndOwnPackages,
  isNewerPackageVersion,
  matchesSearch,
  primaryCategory,
  sortPackages,
  usePackageCatalog,
  withRestartNotice,
} from "../../services/packages";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";
import { useToastContext } from "../../providers/ToastProvider";
import { usePackageArchiveImport } from "../../providers/packages/usePackageArchiveImport";
import type { NodeCatalogFilterTab } from "./nodeCatalogBrowseTypes";

/** One way the rail narrows the grid: a package's category for the Node
 *  Catalog; a model's type and runtime for the Model Catalog. */
export interface CatalogFacet {
  key: string;
  label: string;
  valueOf: (pkg: PackagePayload) => string;
  labelOf: (value: string) => string;
  /** The rows in a fixed order, so a value with nothing in it reads zero;
   *  left out, the values present, by count. */
  order?: string[];
  /** Rows carry a dot keyed like the card strips. */
  dotted?: boolean;
}

export const CATALOG_FACETS: Record<PackageKind, CatalogFacet[]> = {
  node: [
    { key: "category", label: "By category", valueOf: primaryCategory, labelOf: (value) => value, dotted: true },
  ],
  model: [
    {
      key: "type",
      label: "By type",
      valueOf: (pkg) => pkg.model?.type ?? "",
      labelOf: (value) => MODEL_TYPE_LABEL[value as keyof typeof MODEL_TYPE_LABEL] ?? value,
      order: Object.keys(MODEL_TYPE_LABEL),
    },
    {
      key: "runtime",
      label: "By runtime",
      valueOf: (pkg) => pkg.model?.runtime ?? "",
      labelOf: (value) => MODEL_RUNTIME_LABEL[value as keyof typeof MODEL_RUNTIME_LABEL] ?? value,
      order: Object.keys(MODEL_RUNTIME_LABEL),
    },
  ],
};

/** One facet as the rail shows it: its rows with their counts. */
export interface CatalogFacetRows {
  facet: CatalogFacet;
  rows: [string, number][];
}

/**
 * The Node Catalog page's view-model (memo dev/143, F3): a thin adapter over
 * `usePackageCatalog({ kind: "defaults" })` — THE catalog hook, shared with the
 * in-canvas drawer — that keeps only the page's own view state: search, sort,
 * the filters and the selection.
 *
 * The Model Catalog page is the same page over model packages
 * (`packageKind: "model"`), its rail narrowing by type and runtime.
 */
export function useNodeCatalogBrowse(packageKind: PackageKind = "node") {
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<NodeCatalogFilterTab>("all");
  const [facetFilters, setFacetFilters] = useState<Record<string, string>>({});
  const [selectedDirName, setSelectedDirName] = useState<string | null | undefined>(undefined);
  const facets = CATALOG_FACETS[packageKind];

  const catalogState = usePackageCatalog({
    scope: { kind: "defaults" },
    packageKind,
    showToast,
    refreshRegistry: refreshPackageRegistry,
  });
  const {
    catalog,
    installed,
    installedByDir,
    catalogByDir,
    catalogPublishedDirs,
    defaults,
    loaded,
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
    removeFromAccount: onRemoveFromAccount,
  } = catalogState;

  /**
   * Remove from account is offered for a package of the account's own, in its
   * store and in no catalog (imported, made or downloaded), that no dataflow
   * uses, as the store listing says. A shipped package, the copy of a catalog
   * row, never offers it.
   */
  const canRemoveFromAccount = useCallback(
    (pkg: PackagePayload) =>
      !catalogByDir.has(pkg.dirName) && installedByDir.get(pkg.dirName)?.inUse === false,
    [catalogByDir, installedByDir],
  );

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

  const mergedRows = useMemo(() => catalogAndOwnPackages(catalog, installed), [catalog, installed]);

  const bySearch = useMemo(
    () => mergedRows.filter((p) => matchesSearch(p, search)),
    [mergedRows, search],
  );

  const facetBase = useMemo(() => {
    let b = bySearch;
    if (filter === "installed") {
      b = b.filter((p) => defaults.has(p.dirName));
    }
    return b;
  }, [bySearch, filter, defaults]);

  // The counts come from the rows on screen, so a search can take the selected
  // value's count to zero; it stays on the rail so it can be cleared.
  const facetRows = useMemo<CatalogFacetRows[]>(
    () =>
      facets.map((facet) => {
        const counts = new Map<string, number>();
        for (const p of facetBase) {
          const value = facet.valueOf(p);
          if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
        }
        let rows: [string, number][] = facet.order
          ? facet.order.map((value) => [value, counts.get(value) ?? 0])
          : Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
        const selected = facetFilters[facet.key];
        if (selected && !rows.some(([value]) => value === selected)) rows = [...rows, [selected, 0]];
        return { facet, rows };
      }),
    [facets, facetBase, facetFilters],
  );

  const filtered = useMemo(() => {
    const base = facetBase.filter((p) =>
      facets.every((facet) => !facetFilters[facet.key] || facet.valueOf(p) === facetFilters[facet.key]),
    );
    return sortPackages(base, sort);
  }, [facets, facetBase, facetFilters, sort]);

  /** Click a rail row to filter, click it again to clear it. */
  const toggleFacet = useCallback((key: string, value: string) => {
    setFacetFilters((prev) => ({ ...prev, [key]: prev[key] === value ? "" : value }));
  }, []);
  const clearFilters = useCallback(() => {
    setFilter("all");
    setFacetFilters({});
  }, []);

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
    facetFilters,
    facetRows,
    toggleFacet,
    clearFilters,
    selectedDirName,
    setSelectedDirName,
    loaded,
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
    mergedRows,
    filtered,
    selectedPkg,
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
    canRemoveFromAccount,
    onRemoveFromAccount,
    cancelInstall,
  };
}
