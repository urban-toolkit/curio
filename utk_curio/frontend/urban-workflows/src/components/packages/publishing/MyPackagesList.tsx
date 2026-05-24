import React, { useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faEye, faEyeSlash, faTrashCan } from "@fortawesome/free-solid-svg-icons";
import { PackagePayload } from "../../../api/packagesApi";
import {
  formatForkOfSubtitle,
  partitionInstalledPackagesForWarehouseList,
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
  paletteDockDirBusy?: string | null;
  busy?: boolean;
  onUninstall?: (package: PackagePayload) => void;
  onExport?: (package: PackagePayload) => void;
  onPaletteDockToggle?: (package: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
}

type RowActionProps = {
  package: PackagePayload;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackageKey: string | null;
  paletteDockDirBusy: string | null;
  busy: boolean;
  onUninstall?: (package: PackagePayload) => void;
  onExport?: (package: PackagePayload) => void;
  onPaletteDockToggle?: (package: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
};

function PackageRowActions({
  package,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackageKey,
  paletteDockDirBusy,
  busy,
  onUninstall,
  onExport,
  onPaletteDockToggle,
  onPublishToCatalog,
}: RowActionProps) {
  const hiddenInDock = package.paletteDock?.hiddenFromForkPaletteDock === true;
  const dockAwait = paletteDockDirBusy === package.dirName;

  return (
    <>
      {catalogPublishedDirs != null && onPublishToCatalog != null ? (
        <CatalogPublishPill
          variant="dock"
          dirName={package.dirName}
          published={catalogPublishedDirs.has(package.dirName)}
          allowPublish={catalogPublishAllowed}
          busy={publishingPackageKey === package.dirName}
          onPublish={onPublishToCatalog}
        />
      ) : null}

      {onPaletteDockToggle != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title={hiddenInDock ? "Show in Nodes palette dock" : "Hide from Nodes palette dock"}
          aria-label={
            hiddenInDock
              ? `Show ${package.name} in Nodes palette dock`
              : `Hide ${package.name} from Nodes palette dock`
          }
          aria-pressed={!hiddenInDock}
          disabled={busy || dockAwait}
          onClick={() => onPaletteDockToggle(package)}
        >
          <FontAwesomeIcon icon={hiddenInDock ? faEye : faEyeSlash} aria-hidden />
        </button>
      ) : null}

      {onExport != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Export package archive"
          aria-label={`Export ${package.name}`}
          disabled={busy}
          onClick={() => onExport(package)}
        >
          <FontAwesomeIcon icon={faDownload} aria-hidden />
        </button>
      ) : null}

      {onUninstall != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Remove package"
          aria-label={`Remove ${package.name}`}
          disabled={busy}
          onClick={() => onUninstall(package)}
        >
          <FontAwesomeIcon icon={faTrashCan} aria-hidden />
        </button>
      ) : null}
    </>
  );
}

function InstalledPackageRow({
  package,
  catalogByDir,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackageKey,
  paletteDockDirBusy,
  busy,
  hasActions,
  onUninstall,
  onExport,
  onPaletteDockToggle,
  onPublishToCatalog,
  nested = false,
}: {
  package: PackagePayload;
  catalogByDir: Map<string, PackagePayload>;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackageKey: string | null;
  paletteDockDirBusy: string | null;
  busy: boolean;
  hasActions: boolean;
  onUninstall?: (package: PackagePayload) => void;
  onExport?: (package: PackagePayload) => void;
  onPaletteDockToggle?: (package: PackagePayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
  nested?: boolean;
}) {
  const catRow = catalogByDir.get(package.dirName);
  const hasUpdate = catRow != null && catRow.version !== package.version;

  const actionProps = {
    package,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    paletteDockDirBusy,
    busy,
    onUninstall,
    onExport,
    onPaletteDockToggle,
    onPublishToCatalog,
  };

  return (
    <div className={`${styles.installedRow}${nested ? ` ${styles.installedRowNested}` : ""}`}>
      <span className={styles.installedDot} aria-hidden />

      <div className={styles.installedBody}>
        <span className={styles.installedName}>{package.name}</span>
        <span className={styles.installedMeta}>
          v{package.version}
          {hasUpdate ? " · update available" : ` · ${package.kinds.length} nodes`}
        </span>
        {package.lineage ? (
          <span className={styles.installedForkOf} title={formatForkOfSubtitle(package.lineage).title}>
            {formatForkOfSubtitle(package.lineage).text}
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
 * "Your packages" section in the Node Warehouse Drawer.
 * Fork families render as accordions with the lineage-free root package fixed in the header.
 */
export const MyPackagesList: React.FC<MyPackagesListProps> = ({
  installed,
  catalogByDir,
  catalogPublishedDirs,
  catalogPublishAllowed = false,
  publishingPackageKey = null,
  paletteDockDirBusy = null,
  busy = false,
  onUninstall,
  onExport,
  onPaletteDockToggle,
  onPublishToCatalog,
}) => {
  const rows = useMemo(() => partitionInstalledPackagesForWarehouseList(installed), [installed]);

  if (installed.length === 0) return null;

  const hasActions =
    onUninstall != null ||
    onExport != null ||
    onPaletteDockToggle != null ||
    onPublishToCatalog != null;

  const rowProps = {
    catalogByDir,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    paletteDockDirBusy,
    busy,
    hasActions,
    onUninstall,
    onExport,
    onPaletteDockToggle,
    onPublishToCatalog,
  };

  return (
    <>
      <p className={styles.sectionLabel}>Your packages · {installed.length} installed</p>
      <div className={styles.installedList}>
        {rows.map((row) => {
          if (row.kind === "singleton") {
            return <InstalledPackageRow key={row.package.dirName} package={row.package} {...rowProps} />;
          }

          const headerPack = row.rootPack;
          const headerName = headerPack?.name ?? row.rootKey;
          const headerMeta = headerPack
            ? `v${headerPack.version} · ${headerPack.kinds.length} nodes`
            : `${row.members.length} fork${row.members.length === 1 ? "" : "s"}`;

          const headerActionProps = headerPack
            ? {
                package: headerPack,
                catalogPublishedDirs,
                catalogPublishAllowed,
                publishingPackageKey,
                paletteDockDirBusy,
                busy,
                onUninstall,
                onExport,
                onPaletteDockToggle,
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
                {row.members.map((package) => (
                  <InstalledPackageRow key={package.dirName} package={package} nested {...rowProps} />
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </>
  );
};
