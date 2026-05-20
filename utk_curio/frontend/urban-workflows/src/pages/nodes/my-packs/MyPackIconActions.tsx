import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faEye, faEyeSlash, faTrashCan } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../../api/packsApi";
import styles from "./MyPacks.module.css";

export interface MyPackIconActionsProps {
  pack: PackPayload;
  busy: boolean;
  /** When this equals `pack.dirName`, only the dock-eye button is disabled (per-row toggle). */
  paletteDockBusy: string | null;
  onExport: (pack: PackPayload) => void | Promise<void>;
  onUninstall: (pack: PackPayload) => void | Promise<void>;
  onPaletteDockToggle: (pack: PackPayload) => void | Promise<void>;
}

/**
 * Three-icon action column rendered on the right side of every My Packs row.
 * Provides palette-dock visibility toggle, archive export, and pack removal.
 */
export const MyPackIconActions = React.memo(function MyPackIconActions({
  pack,
  busy,
  paletteDockBusy,
  onExport,
  onUninstall,
  onPaletteDockToggle,
}: MyPackIconActionsProps) {
  const hiddenInDock = pack.paletteDock?.hiddenFromForkPaletteDock === true;
  const dockAwait = paletteDockBusy === pack.dirName;

  return (
    <div className={styles.myPackRowAside}>
      <button
        type="button"
        className={styles.myPackIconBtn}
        onClick={() => void onPaletteDockToggle(pack)}
        title={
          hiddenInDock
            ? "Show this pack in the Nodes palette dock"
            : "Hide this pack from the Nodes palette dock"
        }
        aria-label={
          hiddenInDock
            ? `Show ${pack.name} in Nodes palette dock`
            : `Hide ${pack.name} from Nodes palette dock`
        }
        aria-pressed={!hiddenInDock}
        disabled={busy || dockAwait}
      >
        <FontAwesomeIcon icon={hiddenInDock ? faEye : faEyeSlash} aria-hidden />
      </button>

      <button
        type="button"
        className={styles.myPackIconBtn}
        onClick={() => void onExport(pack)}
        title="Export pack archive"
        aria-label={`Export ${pack.name}`}
        disabled={busy}
      >
        <FontAwesomeIcon icon={faDownload} />
      </button>

      <button
        type="button"
        className={styles.myPackIconBtn}
        onClick={() => void onUninstall(pack)}
        title="Remove pack"
        aria-label={`Remove ${pack.name}`}
        disabled={busy}
      >
        <FontAwesomeIcon icon={faTrashCan} />
      </button>
    </div>
  );
});

