import React, { useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowsRotate,
  faDownload,
  faTrashCan,
} from "@fortawesome/free-solid-svg-icons";
import { PackagePayload } from "../../../api/packagesApi";
import {
  formatForkOfSubtitle,
  partitionInstalledPackagesForCatalogList,
} from "../../../utils/forkPackageLineage";
import { CatalogPublishPill } from "../CatalogPublishPill";
import styles from "./MyPackagesList.module.css";

export interface MyPackagesListProps {
  installed: PackagePayload[];
  /** Map of dirName → catalog entry, used to detect pending updates. */
  catalogByDir: Map<string, PackagePayload>;

  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed?: boolean;
  publishingPackageKey?: string | null;
  busy?: boolean;
  onUninstall?: (pkg: PackagePayload) => void;
  onExport?: (pkg: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
  /**
   * Re-copy a package from the shared catalog over the installed copy.
   * The authoring loop for a package you are editing under `packages/`:
   * without this, edits on disk are invisible because the user store already
   * has a copy and the install path is a no-op when one exists.
   */
  onReloadFromCatalog?: (pkg: PackagePayload) => void;
  reloadingPackageKey?: string | null;
}

type RowActionProps = {
  pkg: PackagePayload;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackageKey: string | null;
  busy: boolean;
  /** True when this package exists in the catalog and may be overwritten. */
  canReload: boolean;
  reloadingPackageKey: string | null;
  onUninstall?: (pkg: PackagePayload) => void;
  onExport?: (pkg: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
  onReloadFromCatalog?: (pkg: PackagePayload) => void;
};

function PackageRowActions({
  pkg,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackageKey,
  busy,
  canReload,
  reloadingPackageKey,
  onUninstall,
  onExport,
  onPublishToCatalog,
  onReloadFromCatalog,
}: RowActionProps) {
  const reloading = reloadingPackageKey === pkg.dirName;
  return (
    <>
      {canReload && onReloadFromCatalog != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Reload this package from the catalog, picking up edits made on disk"
          aria-label={`Reload ${pkg.name} from catalog`}
          disabled={busy || reloading}
          onClick={() => onReloadFromCatalog(pkg)}
        >
          <FontAwesomeIcon icon={faArrowsRotate} spin={reloading} aria-hidden />
        </button>
      ) : null}

      {catalogPublishedDirs != null && onPublishToCatalog != null ? (
        <CatalogPublishPill
          variant="dock"
          dirName={pkg.dirName}
          published={catalogPublishedDirs.has(pkg.dirName)}
          allowPublish={catalogPublishAllowed}
          busy={publishingPackageKey === pkg.dirName}
          onPublish={onPublishToCatalog}
        />
      ) : null}

      {onExport != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Export package archive"
          aria-label={`Export ${pkg.name}`}
          disabled={busy}
          onClick={() => onExport(pkg)}
        >
          <FontAwesomeIcon icon={faDownload} aria-hidden />
        </button>
      ) : null}

      {onUninstall != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Remove package"
          aria-label={`Remove ${pkg.name}`}
          disabled={busy}
          onClick={() => onUninstall(pkg)}
        >
          <FontAwesomeIcon icon={faTrashCan} aria-hidden />
        </button>
      ) : null}
    </>
  );
}

function InstalledPackageRow({
  pkg,
  catalogByDir,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackageKey,
  busy,
  hasActions,
  onUninstall,
  onExport,
  onPublishToCatalog,
  onReloadFromCatalog,
  reloadingPackageKey,
  nested = false,
}: {
  pkg: PackagePayload;
  catalogByDir: Map<string, PackagePayload>;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackageKey: string | null;
  busy: boolean;
  hasActions: boolean;
  onUninstall?: (pkg: PackagePayload) => void;
  onExport?: (pkg: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
  onReloadFromCatalog?: (pkg: PackagePayload) => void;
  reloadingPackageKey: string | null;
  nested?: boolean;
}) {
  const catRow = catalogByDir.get(pkg.dirName);
  const hasUpdate = catRow != null && catRow.version !== pkg.version;
  // Offer Reload for anything the catalog also carries — not just when the
  // version string differs. Editing a package's source without bumping
  // `version` is the normal authoring loop, and that is exactly the case
  // where nothing else would tell the user their edit has not landed.
  const canReload = catRow != null && pkg.readOnly !== true;

  const actionProps = {
    pkg,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    busy,
    canReload,
    reloadingPackageKey,
    onUninstall,
    onExport,
    onPublishToCatalog,
    onReloadFromCatalog,
  };

  return (
    <div className={`${styles.installedRow}${nested ? ` ${styles.installedRowNested}` : ""}`}>
      <span className={styles.installedDot} aria-hidden />

      <div className={styles.installedBody}>
        <span className={styles.installedName}>{pkg.name}</span>
        <span className={styles.installedMeta}>
          v{pkg.version}
          {hasUpdate ? " · update available" : ` · ${pkg.templates.length} nodes`}
        </span>
        {pkg.lineage ? (
          <span className={styles.installedForkOf} title={formatForkOfSubtitle(pkg.lineage).title}>
            {formatForkOfSubtitle(pkg.lineage).text}
          </span>
        ) : null}
      </div>

      {hasActions ? (
        <div className={styles.installedActions}>
          <PackageRowActions {...actionProps} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * "Your packages" section in the Node Catalog Drawer.
 * Fork families render as accordions with the lineage-free root package fixed in the header.
 */
export const MyPackagesList: React.FC<MyPackagesListProps> = ({
  installed,
  catalogByDir,
  catalogPublishedDirs,
  catalogPublishAllowed = false,
  publishingPackageKey = null,
  busy = false,
  onUninstall,
  onExport,
  onPublishToCatalog,
  onReloadFromCatalog,
  reloadingPackageKey = null,
}) => {
  const rows = useMemo(() => partitionInstalledPackagesForCatalogList(installed), [installed]);

  if (installed.length === 0) return null;

  const hasActions =
    onUninstall != null ||
    onExport != null ||
    onPublishToCatalog != null ||
    onReloadFromCatalog != null;

  const rowProps = {
    catalogByDir,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    busy,
    hasActions,
    onUninstall,
    onExport,
    onPublishToCatalog,
    onReloadFromCatalog,
    reloadingPackageKey,
  };

  return (
    <>
      <p className={styles.sectionLabel}>Your packages · {installed.length} in project</p>
      <div className={styles.installedList}>
        {rows.map((row) => {
          if (row.kind === "singleton") {
            return <InstalledPackageRow key={row.package.dirName} pkg={row.package} {...rowProps} />;
          }

          const headerPack = row.rootPack;
          const headerName = headerPack?.name ?? row.rootKey;
          const headerMeta = headerPack
            ? `v${headerPack.version} · ${headerPack.templates.length} nodes`
            : `${row.members.length} fork${row.members.length === 1 ? "" : "s"}`;

          // NOTE: this key must be `pkg` — `PackageRowActions` destructures
          // `pkg`, so the previous `package:` spelling reached it as
          // `undefined` and threw on `pkg.dirName` while rendering any fork
          // family that had its root package installed.
          const headerActionProps = headerPack
            ? {
                pkg: headerPack,
                catalogPublishedDirs,
                catalogPublishAllowed,
                publishingPackageKey,
                busy,
                canReload:
                  catalogByDir.get(headerPack.dirName) != null &&
                  headerPack.readOnly !== true,
                reloadingPackageKey,
                onUninstall,
                onExport,
                onPublishToCatalog,
                onReloadFromCatalog,
              }
            : null;

          return (
            <details key={row.rootKey} className={styles.familyDetails}>
              <summary className={styles.familySummary}>
                <div className={styles.familySummaryMain}>
                  <span className={styles.installedDot} aria-hidden />
                  <div className={styles.installedBody}>
                    <span className={styles.installedName}>{headerName}</span>
                    <span className={styles.installedMeta}>{headerMeta}</span>
                  </div>
                </div>
                {headerActionProps && hasActions ? (
                  <div
                    className={styles.installedActions}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                  >
                    <PackageRowActions {...headerActionProps} />
                  </div>
                ) : (
                  <span className={styles.familyCountBadge}>{row.members.length}</span>
                )}
              </summary>
              <div className={styles.familyMemberList}>
                {row.members.map((pkg) => (
                  <InstalledPackageRow key={pkg.dirName} pkg={pkg} nested {...rowProps} />
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </>
  );
};
