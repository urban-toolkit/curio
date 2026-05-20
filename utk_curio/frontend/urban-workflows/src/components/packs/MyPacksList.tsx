import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faEye, faEyeSlash, faTrashCan } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../api/packsApi";
import { CatalogPublishPill } from "./CatalogPublishPill";
import styles from "./MyPacksList.module.css";

export interface MyPacksListProps {
  installed: PackPayload[];
  /** Map of dirName → catalog entry, used to detect pending updates. */
  catalogByDir: Map<string, PackPayload>;

  // ── Optional action callbacks — renders action buttons when provided ──

  /** Set of dirNames already published to the dev catalog fixture. */
  catalogPublishedDirs?: ReadonlySet<string>;
  /** Whether the server allows publishing to the dev catalog. */
  catalogPublishAllowed?: boolean;
  /** dirName of the pack currently being published (shows spinner). */
  publishingPackKey?: string | null;
  /** dirName of the pack whose palette-dock visibility is being toggled. */
  paletteDockDirBusy?: string | null;
  /** Global busy flag — disables all actions while a request is in flight. */
  busy?: boolean;
  onUninstall?: (pack: PackPayload) => void;
  onExport?: (pack: PackPayload) => void;
  onPaletteDockToggle?: (pack: PackPayload) => void;
  onPublishToCatalog?: (dirName: string) => void;
}

/**
 * "Your packs" section shown on the Featured tab of the Node Warehouse Drawer.
 * Renders a compact row for every installed pack.
 * When action callbacks are provided each row also shows
 * publish, show/hide, export, and remove buttons — matching the Hub page.
 * Returns null when nothing is installed.
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
  if (installed.length === 0) return null;

  const hasActions =
    onUninstall != null ||
    onExport != null ||
    onPaletteDockToggle != null ||
    onPublishToCatalog != null;

  return (
    <>
      <p className={styles.sectionLabel}>Your packs · {installed.length} installed</p>
      <div className={styles.installedList}>
        {installed.map((pack) => {
          const catRow = catalogByDir.get(pack.dirName);
          const hasUpdate = catRow != null && catRow.version !== pack.version;
          const hiddenInDock = pack.paletteDock?.hiddenFromForkPaletteDock === true;
          const dockAwait = paletteDockDirBusy === pack.dirName;

          return (
            <div key={pack.dirName} className={styles.installedRow}>
              <span className={styles.installedDot} aria-hidden />

              <div className={styles.installedBody}>
                <span className={styles.installedName}>{pack.name}</span>
                <span className={styles.installedMeta}>
                  v{pack.version}
                  {hasUpdate ? " · update available" : ` · ${pack.kinds.length} nodes`}
                </span>
              </div>

              {hasActions && (
                <div className={styles.installedActions}>
                  {catalogPublishedDirs != null && onPublishToCatalog != null && (
                    <CatalogPublishPill
                      variant="dock"
                      dirName={pack.dirName}
                      published={catalogPublishedDirs.has(pack.dirName)}
                      allowPublish={catalogPublishAllowed}
                      busy={publishingPackKey === pack.dirName}
                      onPublish={onPublishToCatalog}
                    />
                  )}

                  {onPaletteDockToggle != null && (
                    <button
                      type="button"
                      className={styles.rowActionBtn}
                      title={
                        hiddenInDock
                          ? "Show in Nodes palette dock"
                          : "Hide from Nodes palette dock"
                      }
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
                  )}

                  {onExport != null && (
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
                  )}

                  {onUninstall != null && (
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
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
};
