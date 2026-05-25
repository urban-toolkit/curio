import React, { useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faTrashCan } from "@fortawesome/free-solid-svg-icons";
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
}

type RowActionProps = {
  package: PackagePayload;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackageKey: string | null;
  busy: boolean;
  onUninstall?: (pkg: PackagePayload) => void;
  onExport?: (pkg: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
};

function PackageRowActions({
  pkg,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackageKey,
  busy,
  onUninstall,
  onExport,
  onPublishToCatalog,
}: RowActionProps) {
  return (
    <>
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
  nested = false,
}: {
  package: PackagePayload;
  catalogByDir: Map<string, PackagePayload>;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackageKey: string | null;
  busy: boolean;
  hasActions: boolean;
  onUninstall?: (pkg: PackagePayload) => void;
  onExport?: (pkg: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
  nested?: boolean;
}) {
  const catRow = catalogByDir.get(pkg.dirName);
  const hasUpdate = catRow != null && catRow.version !== pkg.version;

  const actionProps = {
    pkg,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    busy,
    onUninstall,
    onExport,
    onPublishToCatalog,
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
}) => {
  const rows = useMemo(() => partitionInstalledPackagesForCatalogList(installed), [installed]);

  if (installed.length === 0) return null;

  const hasActions =
    onUninstall != null ||
    onExport != null ||
    onPublishToCatalog != null;

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
  };

  return (
    <>
      <p className={styles.sectionLabel}>Your packages · {installed.length} installed</p>
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

          const headerActionProps = headerPack
            ? {
                package: headerPack,
                catalogPublishedDirs,
                catalogPublishAllowed,
                publishingPackageKey,
                busy,
                onUninstall,
                onExport,
                onPublishToCatalog,
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
