/**
 * Top-level /catalog page (linked from the Projects page nav bar).
 *
 * Mental model (see docs/CATALOG.md):
 *   - Install here is *global*: it adds the package to the per-user
 *     defaults list AND walks every existing project's lockfile.
 *   - No Uninstall on this page. Removal is per-project, in the drawer.
 *   - Publish stays available (gated by `factoryCapabilities().catalogPublish`).
 *
 * Reuses the drawer's PackageCard / PackageSearchRow / InstallPermissionsDialog
 * so the package metadata and dependency-conflict UX stay consistent across
 * surfaces.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import CSS from "csstype";
import { Link, useNavigate } from "react-router-dom";
import logo from "assets/curio-2.png";

import {
  PackagePayload,
  ResolveConflict,
  packagesApi,
  refreshPackageRegistry,
} from "../../api/packagesApi";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import { PackageCard } from "../../components/packages/publishing/PackageCard";
import { PackageSearchRow } from "../../components/packages/publishing/PackageSearchRow";
import {
  matchesSearch,
  sortPackages,
} from "../../components/packages/publishing/packageUtils";
import { SortMode } from "../../components/packages/publishing/packageTypes";
import { draftFromInstalledPackagePayload } from "../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../nodes/factoryDraftModel";
import { useUserContext } from "../../providers/UserProvider";
import VersionBadge from "../../components/VersionBadge";


type FilterTab = "all" | "installed" | "updates";


export const CatalogPage: React.FC = () => {
  const { user, signout, enableUserAuth } = useUserContext();
  const navigate = useNavigate();

  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  /** User-store packages — the "implementations" set. Used to detect updates
   * and to find a package the user can publish. */
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  /** Per-user defaults — packages auto-seeded into new projects. Drives the
   * "Installed" filter on this page. */
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<FilterTab>("all");
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

  /**
   * Union of catalog + user-store rows, de-duped by dirName with the catalog
   * row winning when both exist. The merge lets the page surface
   * sideloaded-but-not-yet-published packages so the user can hit Publish on
   * them; without it the page would only show packages the catalog already knows
   * about, which would never have anything to publish.
   */
  const mergedRows = useMemo(() => {
    const out = new Map<string, PackagePayload>();
    for (const row of installed) out.set(row.dirName, row);
    for (const row of catalog) out.set(row.dirName, row);
    return Array.from(out.values());
  }, [catalog, installed]);

  const filtered = useMemo(() => {
    let base = mergedRows.filter((p) => matchesSearch(p, search));
    if (filter === "installed") {
      base = base.filter((p) => defaults.has(p.dirName));
    } else if (filter === "updates") {
      base = base.filter((p) => updateCandidateDirs.has(p.dirName));
    }
    return sortPackages(base, sort);
  }, [mergedRows, search, sort, filter, defaults, updateCandidateDirs]);

  const onInstall = useCallback(async (pkg: PackagePayload) => {
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
  }, [installed]);

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
      const summary = failed.length === 0
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

  const onPublish = useCallback(async (dirName: string) => {
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
  }, [installedByDir, reload, reportError]);

  const initials = user?.name
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "?";

  return (
    <div style={pageStyle}>
      {/* Top Nav — same shape as ProjectsList so the page sits in the global UI cleanly. */}
      <header style={topBarStyle}>
        <Link to="/projects" style={logoLinkStyle}>
          <img src={logo} alt="Curio" style={logoImgStyle} />
        </Link>
        <div style={topBarRightStyle}>
          <button style={navBtnStyle} onClick={() => navigate("/projects")}>
            Projects
          </button>
          <div style={avatarStyle}>{initials}</div>
          <div style={userInfoColumnStyle}>
            <span style={userNameStyle}>{user?.name || "User"}</span>
            {enableUserAuth && (
              <button
                style={signoutBtnStyle}
                onClick={async () => {
                  await signout();
                  navigate("/auth/signin");
                }}
              >
                Logout
              </button>
            )}
          </div>
        </div>
      </header>

      <main style={mainStyle}>
        <div style={pageHeaderStyle}>
          <h1 style={pageTitleStyle}>Node catalog</h1>
          <p style={pageSubtitleStyle}>
            Install packages for <strong>all your projects</strong>, present and future.
            Removing a package from a single project can be done in that project's node catalog.
          </p>
        </div>

        <PackageSearchRow
          search={search}
          sort={sort}
          onSearchChange={setSearch}
          onSortChange={setSort}
        />

        <div style={filterRowStyle}>
          {([
            { id: "all", label: `All (${catalog.length})` },
            { id: "installed", label: `Installed (${defaults.size})` },
            { id: "updates", label: `Updates (${updateCandidates.length})` },
          ] as { id: FilterTab; label: string }[]).map((opt) => (
            <button
              key={opt.id}
              type="button"
              style={{
                ...filterBtnStyle,
                ...(filter === opt.id ? filterBtnActiveStyle : {}),
              }}
              onClick={() => setFilter(opt.id)}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {lastInstallSummary && (
          <div style={infoBannerStyle}>
            {lastInstallSummary}
            <button
              type="button"
              style={bannerDismissStyle}
              onClick={() => setLastInstallSummary(null)}
            >
              ×
            </button>
          </div>
        )}

        {actionError && (
          <div style={errorBannerStyle} role="alert">
            {actionError}
            <button
              type="button"
              style={bannerDismissStyle}
              onClick={() => setActionError(null)}
            >
              ×
            </button>
          </div>
        )}

        {filtered.length === 0 ? (
          <p style={emptyStyle}>No packages match the current filter.</p>
        ) : (
          <div style={cardGridStyle}>
            {filtered.map((pkg) => {
              const userStoreRow = installedByDir.get(pkg.dirName);
              const isInstalledGlobally = defaults.has(pkg.dirName);
              const catalogRow = catalogByDir.get(pkg.dirName);
              const hasUpdate =
                isInstalledGlobally
                && userStoreRow != null
                && catalogRow != null
                && catalogRow.version !== userStoreRow.version;
              const isPublished = catalogPublishedDirs.has(pkg.dirName);
              // Publish action only makes sense when the user has a local copy
              // (you can't publish something you don't have on disk).
              const showPublish = userStoreRow != null;
              return (
                <PackageCard
                  key={pkg.dirName}
                  pkg={pkg}
                  isInstalled={isInstalledGlobally}
                  hasUpdate={hasUpdate}
                  catalogRow={catalogRow}
                  busy={busy}
                  cardActionDir={null}
                  catalogPublishAllowed={catalogPublishAllowed}
                  isPublished={isPublished}
                  publishingDir={publishingPackageKey}
                  onInstall={(p) => void onInstall(p)}
                  onPublish={showPublish ? onPublish : undefined}
                  /* No per-card uninstall on this page — see docs/CATALOG.md */
                />
              );
            })}
          </div>
        )}
      </main>

      <VersionBadge />

      {installCandidate ? (
        <InstallPermissionsDialog
          pkg={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={() => {
            setInstallCandidate(null);
            setConflictReport(null);
          }}
          onConfirm={() => void confirmInstall()}
        />
      ) : null}
    </div>
  );
};

export default CatalogPage;


/* ---- Styles (mirroring ProjectsList for visual consistency) ---- */

const pageStyle: CSS.Properties = {
  minHeight: "100vh",
  backgroundColor: "#f0f0f0",
  fontFamily:
    "Rubik, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif",
};

const topBarStyle: CSS.Properties = {
  height: "65px",
  backgroundColor: "#1E1F23",
  display: "flex",
  alignItems: "center",
  padding: "10px 20px 10px 10px",
  justifyContent: "space-between",
  borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
};

const logoLinkStyle: CSS.Properties = { display: "contents" };
const logoImgStyle: CSS.Properties = {
  maxHeight: "100%",
  width: "auto",
  marginLeft: "15px",
  marginRight: "15px",
  cursor: "pointer",
};

const topBarRightStyle: CSS.Properties = {
  display: "flex",
  alignItems: "center",
  gap: "8px",
};

const navBtnStyle: CSS.Properties = {
  background: "none",
  border: "1px solid #444",
  borderRadius: "4px",
  color: "#ddd",
  fontSize: "12px",
  fontWeight: 500,
  padding: "5px 12px",
  cursor: "pointer",
  marginRight: "12px",
};

const userInfoColumnStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "2px",
};

const userNameStyle: CSS.Properties = {
  color: "#fff",
  fontSize: "12px",
  fontWeight: 500,
  maxWidth: "110px",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

const avatarStyle: CSS.Properties = {
  width: "28px",
  height: "28px",
  borderRadius: "50%",
  backgroundColor: "#fff",
  color: "#0F0F11",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: "11px",
  fontWeight: 700,
  border: "1px solid #2A2A2E",
  flexShrink: 0,
};

const signoutBtnStyle: CSS.Properties = {
  background: "none",
  border: "1px solid #444",
  borderRadius: "4px",
  color: "#ddd",
  fontSize: "11px",
  fontWeight: 500,
  padding: "3px 10px",
  cursor: "pointer",
  lineHeight: 1.3,
};

const mainStyle: CSS.Properties = {
  maxWidth: "1200px",
  margin: "0 auto",
  padding: "32px 24px",
};

const pageHeaderStyle: CSS.Properties = {
  marginBottom: "20px",
};

const pageTitleStyle: CSS.Properties = {
  fontSize: "24px",
  fontWeight: 600,
  color: "#1E1F23",
  margin: 0,
  marginBottom: "6px",
};

const pageSubtitleStyle: CSS.Properties = {
  fontSize: "13px",
  color: "#6B6B76",
  margin: 0,
  maxWidth: "720px",
};

const filterRowStyle: CSS.Properties = {
  display: "flex",
  gap: "8px",
  marginTop: "16px",
  marginBottom: "20px",
};

const filterBtnStyle: CSS.Properties = {
  padding: "6px 14px",
  border: "1px solid #D0D0D5",
  background: "#fff",
  fontSize: "13px",
  fontWeight: 500,
  cursor: "pointer",
  borderRadius: "4px",
  color: "#6B6B76",
};

const filterBtnActiveStyle: CSS.Properties = {
  backgroundColor: "#1E1F23",
  color: "#fbfcf6",
  borderColor: "#1E1F23",
};

const cardGridStyle: CSS.Properties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
  gap: "16px",
};

const emptyStyle: CSS.Properties = {
  color: "#9E9E9E",
  fontSize: "14px",
  textAlign: "center",
  padding: "40px 0",
};

const infoBannerStyle: CSS.Properties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  background: "#E7F1FF",
  color: "#1E1F23",
  border: "1px solid #B4D2FA",
  borderRadius: "6px",
  padding: "10px 14px",
  margin: "0 0 16px",
  fontSize: "13px",
};

const errorBannerStyle: CSS.Properties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  background: "#FFE3DA",
  color: "#7B2D14",
  border: "1px solid #F2A48A",
  borderRadius: "6px",
  padding: "10px 14px",
  margin: "0 0 16px",
  fontSize: "13px",
};

const bannerDismissStyle: CSS.Properties = {
  background: "none",
  border: "none",
  color: "inherit",
  fontSize: "18px",
  cursor: "pointer",
  marginLeft: "12px",
  lineHeight: 1,
};
