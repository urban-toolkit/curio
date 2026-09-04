import { useCallback, useEffect, useMemo, useState } from "react";
import {
  PackagePayload,
  ResolveConflict,
  packagesApi,
  refreshPackageRegistry,
} from "../../api/packagesApi";
import {
  matchesSearch,
  primaryCategory,
  sortPackages,
} from "../../components/packages/publishing/packageUtils";
import type { SortMode } from "../../components/packages/publishing/packageTypes";
import { draftFromInstalledPackagePayload } from "../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../nodes/factoryDraftModel";
import { useToastContext } from "../../providers/ToastProvider";
import { usePackageArchiveImport } from "../../components/packages/publishing/usePackageArchiveImport";
import type { NodeCatalogFilterTab } from "./nodeCatalogBrowseTypes";
import { dependencyFailureNotice } from "../../utils/packageDependencyNotice";

export function useNodeCatalogBrowse() {
  const { showToast } = useToastContext();
  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<NodeCatalogFilterTab>("all");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedDirName, setSelectedDirName] = useState<string | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const [publishingPackageKey, setPublishingPackageKey] = useState<string | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackagePayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const [lastInstallSummary, setLastInstallSummary] = useState<string | null>(null);

  const reportError = useCallback((label: string, err: unknown) => {
    const status = (err as { status?: number } | null)?.status;
    const body = (err as { body?: { error?: string } } | null)?.body;
    const message = (err as { message?: string } | null)?.message;
    const detail = body?.error ?? message ?? (status ? `HTTP ${status}` : "unknown error");
    setActionError(`${label}: ${detail}`);
  }, []);

  const reload = useCallback(async () => {
    const [cat, mine, cap, defaultsResp] = await Promise.all([
      packagesApi.catalog(),
      packagesApi.listInstalled(),
      packagesApi.factoryCapabilities(),
      packagesApi.getDefaults(),
    ]);
    setCatalog(cat.packages);
    setInstalled(mine.packages);
    setCatalogPublishAllowed(cap.catalogPublish);
    setDefaults(new Set(defaultsResp.packages));
  }, []);

  useEffect(() => {
    void reload().catch((err) => reportError("Couldn't load catalog", err));
  }, [reload, reportError]);

  const installedByDir = useMemo(
    () => new Map(installed.map((p) => [p.dirName, p])),
    [installed],
  );
  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);
  const catalogPublishedDirs = useMemo(() => new Set(catalog.map((p) => p.dirName)), [catalog]);

  const updateCandidates = useMemo(() => {
    return installed.filter((row) => {
      const catRow = catalogByDir.get(row.dirName);
      return catRow != null && catRow.version !== row.version;
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

  const onInstall = useCallback(
    async (pkg: PackagePayload) => {
      setInstallCandidate(pkg);
      try {
        const probe = await packagesApi.resolve([
          ...installed.map((p) => p.dirName),
          pkg.dirName,
        ]);
        setConflictReport(probe.conflicts);
      } catch (err) {
        const status = (err as { status?: number }).status;
        if (status === 409) {
          const body = (err as { body?: { conflicts: ResolveConflict[] } }).body;
          setConflictReport(body?.conflicts ?? []);
        } else {
          setInstallCandidate(null);
        }
      }
    },
    [installed],
  );

  const confirmInstall = useCallback(async () => {
    if (!installCandidate) return;
    setBusy(true);
    setActionError(null);
    setLastInstallSummary(null);
    try {
      const result = await packagesApi.installToDefaults(installCandidate.dirName);
      const succeeded = result.projects.filter((p) => p.ok).length;
      const failed = result.projects.filter((p) => !p.ok);
      const proj = result.projects.length;
      const summary =
        failed.length === 0
          ? `Added ${installCandidate.name} to ${proj} project${proj === 1 ? "" : "s"}` +
            (proj === 0 ? " (no existing projects; will seed into new ones)" : "")
          : `Added to ${succeeded}/${proj} projects; ${failed.length} failed: ${failed.map((f) => f.id).join(", ")}`;
      setLastInstallSummary(summary);
      // The blue summary banner says how many projects were patched, which is
      // not the same question. A library that installed and cannot be imported
      // makes every one of those projects reference a package whose nodes will
      // raise, so it gets the error channel rather than a line in a notice
      // about counts.
      const notice = dependencyFailureNotice(
        `Added ${installCandidate.name}`, result,
      );
      if (notice) showToast(notice, "error");
      await refreshPackageRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      reportError(`Couldn't add ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload, reportError, showToast]);

  const onPublish = useCallback(
    async (dirName: string) => {
      const row = installedByDir.get(dirName);
      if (!row) return;
      setPublishingPackageKey(dirName);
      setActionError(null);
      try {
        const draft = draftFromInstalledPackagePayload(row);
        await packagesApi.factoryPublishCatalog({
          ...(toApiPayload(draft) as Record<string, unknown>),
          replace: true,
        });
        await reload();
        showToast(`Published ${row.name}.`, "success");
      } catch (err) {
        reportError(`Couldn't publish ${row.name}`, err);
      } finally {
        setPublishingPackageKey(null);
      }
    },
    [installedByDir, reload, reportError, showToast],
  );

  /**
   * Sideload a `.curio.zip` from the catalog PAGE's header, through the SAME
   * hook the Node Catalog drawer's footer uses. This was briefly a second copy
   * of the drawer's logic; it is now one pathway with one difference, expressed
   * as data: no `projectId`, because the page has no dataflow to install into.
   */
  const { importing, importArchive: onImportArchive } = usePackageArchiveImport({
    reload,
    onError: reportError,
    onImported: (pkg, notice) =>
      showToast(notice ?? `Imported ${pkg?.name ?? "package"}.`,
                notice ? "error" : "success"),
  });

  /** The inverse of `onPublish`, which the page had no way to reach. Publishing
   *  was a one-way door on this surface: the card offered Publish, and once
   *  taken there was no Unpublish anywhere on the page to undo it. */
  const onUnpublish = useCallback(
    async (dirName: string) => {
      const row = installedByDir.get(dirName) ?? catalogByDir.get(dirName);
      setPublishingPackageKey(dirName);
      setActionError(null);
      try {
        await packagesApi.unpublishFromCatalog(dirName);
        await reload();
        showToast(`Unpublished ${row?.name ?? dirName}.`, "success");
      } catch (err) {
        reportError(`Couldn't unpublish ${row?.name ?? dirName}`, err);
      } finally {
        setPublishingPackageKey(null);
      }
    },
    [installedByDir, catalogByDir, reload, reportError, showToast],
  );

  const dismissInstallSummary = useCallback(() => setLastInstallSummary(null), []);
  const dismissActionError = useCallback(() => setActionError(null), []);
  const cancelInstall = useCallback(() => {
    setInstallCandidate(null);
    setConflictReport(null);
  }, []);

  const allCount = bySearch.length;
  const installedCount = bySearch.filter((p) => defaults.has(p.dirName)).length;
  const updatesCount = bySearch.filter((p) => updateCandidateDirs.has(p.dirName)).length;

  const selectedHasUpdate =
    selectedPkg != null &&
    defaults.has(selectedPkg.dirName) &&
    installedByDir.get(selectedPkg.dirName) != null &&
    catalogByDir.get(selectedPkg.dirName) != null &&
    catalogByDir.get(selectedPkg.dirName)!.version !==
      installedByDir.get(selectedPkg.dirName)!.version;

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
    importing,
    onImportArchive,
    confirmInstall,
    onPublish,
    onUnpublish,
    cancelInstall,
  };
}
