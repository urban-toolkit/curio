import React, { useMemo } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faEye, faEyeSlash, faTrashCan } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../api/packsApi";
import {
  formatForkOfSubtitle,
  partitionInstalledPacksForWarehouseList,
} from "../../utils/forkPackLineage";
import { CatalogPublishPill } from "./CatalogPublishPill";
import styles from "./MyPacksList.module.css";

export interface MyPacksListProps {
  installed: PackPayload[];
  /** Map of dirName → catalog entry, used to detect pending updates. */
  catalogByDir: Map<string, PackPayload>;

  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed?: boolean;
  publishingPackKey?: string | null;
  paletteDockDirBusy?: string | null;
  busy?: boolean;
  onUninstall?: (pack: PackPayload) => void;
  onExport?: (pack: PackPayload) => void;
  onPaletteDockToggle?: (pack: PackPayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
}

type RowActionProps = {
  pack: PackPayload;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackKey: string | null;
  paletteDockDirBusy: string | null;
  busy: boolean;
  onUninstall?: (pack: PackPayload) => void;
  onExport?: (pack: PackPayload) => void;
  onPaletteDockToggle?: (pack: PackPayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
};

function PackRowActions({
  pack,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackKey,
  paletteDockDirBusy,
  busy,
  onUninstall,
  onExport,
  onPaletteDockToggle,
  onPublishToCatalog,
}: RowActionProps) {
  const hiddenInDock = pack.paletteDock?.hiddenFromForkPaletteDock === true;
  const dockAwait = paletteDockDirBusy === pack.dirName;

  return (
    <>
      {catalogPublishedDirs != null && onPublishToCatalog != null ? (
        <CatalogPublishPill
          variant="dock"
          dirName={pack.dirName}
          published={catalogPublishedDirs.has(pack.dirName)}
          allowPublish={catalogPublishAllowed}
          busy={publishingPackKey === pack.dirName}
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
              ? `Show ${pack.name} in Nodes palette dock`
              : `Hide ${pack.name} from Nodes palette dock`
          }
          aria-pressed={!hiddenInDock}
          disabled={busy || dockAwait}
          onClick={() => onPaletteDockToggle(pack)}
        >
          <FontAwesomeIcon icon={hiddenInDock ? faEye : faEyeSlash} aria-hidden />
        </button>
      ) : null}

      {onExport != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Export pack archive"
          aria-label={`Export ${pack.name}`}
          disabled={busy}
          onClick={() => onExport(pack)}
        >
          <FontAwesomeIcon icon={faDownload} aria-hidden />
        </button>
      ) : null}

      {onUninstall != null ? (
        <button
          type="button"
          className={styles.rowActionBtn}
          title="Remove pack"
          aria-label={`Remove ${pack.name}`}
          disabled={busy}
          onClick={() => onUninstall(pack)}
        >
          <FontAwesomeIcon icon={faTrashCan} aria-hidden />
        </button>
      ) : null}
    </>
  );
}

function InstalledPackRow({
  pack,
  catalogByDir,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackKey,
  paletteDockDirBusy,
  busy,
  hasActions,
  onUninstall,
  onExport,
  onPaletteDockToggle,
  onPublishToCatalog,
  nested = false,
}: {
  pack: PackPayload;
  catalogByDir: Map<string, PackPayload>;
  catalogPublishedDirs?: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackKey: string | null;
  paletteDockDirBusy: string | null;
  busy: boolean;
  hasActions: boolean;
  onUninstall?: (pack: PackPayload) => void;
  onExport?: (pack: PackPayload) => void;
  onPaletteDockToggle?: (pack: PackPayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
  nested?: boolean;
}) {
  const catRow = catalogByDir.get(pack.dirName);
  const hasUpdate = catRow != null && catRow.version !== pack.version;

  const actionProps = {
    pack,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackKey,
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
        <span className={styles.installedName}>{pack.name}</span>
        <span className={styles.installedMeta}>
          v{pack.version}
          {hasUpdate ? " · update available" : ` · ${pack.kinds.length} nodes`}
        </span>
        {pack.lineage ? (
          <span className={styles.installedForkOf} title={formatForkOfSubtitle(pack.lineage).title}>
            {formatForkOfSubtitle(pack.lineage).text}
          </span>
        ) : null}
      </div>

      {hasActions ? (
        <div className={styles.installedActions}>
          <PackRowActions {...actionProps} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * "Your packs" section in the Node Warehouse Drawer.
 * Fork families render as accordions with the lineage-free root pack fixed in the header.
 */
export const MyPacksList: React.FC<MyPacksListProps> = ({
  installed,
  catalogByDir,
  catalogPublishedDirs,
  catalogPublishAllowed = false,
  publishingPackKey = null,
  paletteDockDirBusy = null,
  busy = false,
  onUninstall,
  onExport,
  onPaletteDockToggle,
  onPublishToCatalog,
}) => {
  const rows = useMemo(() => partitionInstalledPacksForWarehouseList(installed), [installed]);

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
    publishingPackKey,
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
      <p className={styles.sectionLabel}>Your packs · {installed.length} installed</p>
      <div className={styles.installedList}>
        {rows.map((row) => {
          if (row.kind === "singleton") {
            return <InstalledPackRow key={row.pack.dirName} pack={row.pack} {...rowProps} />;
          }

          const headerPack = row.rootPack;
          const headerName = headerPack?.name ?? row.rootKey;
          const headerMeta = headerPack
            ? `v${headerPack.version} · ${headerPack.kinds.length} nodes`
            : `${row.members.length} fork${row.members.length === 1 ? "" : "s"}`;

          const headerActionProps = headerPack
            ? {
                pack: headerPack,
                catalogPublishedDirs,
                catalogPublishAllowed,
                publishingPackKey,
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
                    <PackRowActions {...headerActionProps} />
                  </div>
                ) : (
                  <span className={styles.familyCountBadge}>{row.members.length}</span>
                )}
              </summary>
              <div className={styles.familyMemberList}>
                {row.members.map((pack) => (
                  <InstalledPackRow key={pack.dirName} pack={pack} nested {...rowProps} />
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </>
  );
};
