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
import type { NodeCatalogFilterTab } from "./nodeCatalogBrowseTypes";

export function useNodeCatalogBrowse() {
  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<NodeCatalogFilterTab>("all");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [selectedDirName, setSelectedDirName] = useState<string | null>(null);
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
    } else if (filter === "updates") {
      b = b.filter((p) => updateCandidateDirs.has(p.dirName));
    }
    return b;
  }, [bySearch, filter, defaults, updateCandidateDirs]);

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
      setSelectedDirName(null);
      return;
    }
    if (selectedDirName == null || !filtered.some((p) => p.dirName === selectedDirName)) {
      setSelectedDirName(filtered[0]!.dirName);
    }
  }, [filtered, selectedDirName]);

  const selectedPkg = useMemo(
    () => filtered.find((p) => p.dirName === selectedDirName) ?? filtered[0] ?? null,
    [filtered, selectedDirName],
  );

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
          ? `Installed ${installCandidate.name} for ${proj} project${proj === 1 ? "" : "s"}` +
            (proj === 0 ? " (no existing projects; will seed into new ones)" : "")
          : `Installed for ${succeeded}/${proj} projects; ${failed.length} failed: ${failed.map((f) => f.id).join(", ")}`;
      setLastInstallSummary(summary);
      await refreshPackageRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      reportError(`Couldn't install ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload, reportError]);

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
      } catch (err) {
        reportError(`Couldn't publish ${row.name}`, err);
      } finally {
        setPublishingPackageKey(null);
      }
    },
    [installedByDir, reload, reportError],
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
    confirmInstall,
    onPublish,
    cancelInstall,
  };
}
