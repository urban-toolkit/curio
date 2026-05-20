import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEye, faEyeSlash } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../../api/packsApi";
import { InstalledHubEntry, MyPacksCallbacks } from "./myPacksTypes";
import { MyPackSingletonRow } from "./MyPackSingletonRow";
import { HubInstalledForkRailGroup } from "./HubInstalledForkRailGroup";
import styles from "./MyPacks.module.css";

export interface MyPacksSidebarProps extends MyPacksCallbacks {
  installed: PackPayload[];
  /** Pre-sorted list of singleton and fork-family entries for the rail. */
  hubRailInstalledOrdered: InstalledHubEntry[];
  busy: boolean;
  forkParentsPaletteBusy: boolean;
  paletteDockDirBusy: string | null;
  /** Set of dirNames for fork parent packs referenced by the installed list. */
  installedForkParentCoordsSize: number;
  forkParentsRevealedInDockPalette: boolean;
  catalogPublishedDirs: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackKey: string | null;
  hubForkManualByRoot: Record<string, string>;
  setHubForkManualByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  onToggleForkSourcesInDockPalette: () => void;
}

/**
 * The "My packs" fixed sidebar panel on the right side of the Nodes Hub.
 *
 * Renders a header with an optional fork-source palette-dock toggle,
 * then a list of installed packs as either singleton rows or fork-family
 * groups, sorted newest-first.
 */
export const MyPacksSidebar: React.FC<MyPacksSidebarProps> = ({
  installed,
  hubRailInstalledOrdered,
  busy,
  forkParentsPaletteBusy,
  paletteDockDirBusy,
  installedForkParentCoordsSize,
  forkParentsRevealedInDockPalette,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackKey,
  hubForkManualByRoot,
  setHubForkManualByRoot,
  onToggleForkSourcesInDockPalette,
  onExport,
  onUninstall,
  onPaletteDockToggle,
  onPublishToCatalog,
  onOpenForkInFactory,
}) => (
  <aside className={styles.myPacks} aria-label="Your installed packs">
    <div className={styles.myPacksHeaderRow}>
      <h2 id="hub-my-packs-heading" className={styles.myPacksTitle}>
        My packs
      </h2>

      {installed.length > 0 && installedForkParentCoordsSize > 0 ? (
        <button
          type="button"
          className={styles.myPacksDockToggleBtn}
          onClick={onToggleForkSourcesInDockPalette}
          disabled={busy || forkParentsPaletteBusy || paletteDockDirBusy != null}
          title={
            forkParentsRevealedInDockPalette
              ? "Hide fork source packs from the Nodes palette dock"
              : "Show fork source packs in the Nodes palette dock"
          }
          aria-label={
            forkParentsRevealedInDockPalette
              ? "Hide fork source packs from Nodes palette dock"
              : "Show fork source packs in Nodes palette dock"
          }
          aria-pressed={forkParentsRevealedInDockPalette}
        >
          <FontAwesomeIcon
            icon={forkParentsRevealedInDockPalette ? faEyeSlash : faEye}
            aria-hidden
          />
        </button>
      ) : null}
    </div>

    {installed.length === 0 ? (
      <div className={styles.empty}>You haven&apos;t installed any packs yet.</div>
    ) : (
      <>
        {hubRailInstalledOrdered.map((entry) =>
          entry.kind === "singleton" ? (
            <MyPackSingletonRow
              key={entry.pack.dirName}
              pack={entry.pack}
              busy={busy}
              paletteDockBusy={paletteDockDirBusy}
              catalogPublishedDirs={catalogPublishedDirs}
              catalogPublishAllowed={catalogPublishAllowed}
              publishingPackKey={publishingPackKey}
              onExport={onExport}
              onUninstall={onUninstall}
              onPaletteDockToggle={onPaletteDockToggle}
              onPublishToCatalog={onPublishToCatalog}
              onOpenForkInFactory={onOpenForkInFactory}
            />
          ) : (
            <HubInstalledForkRailGroup
              key={entry.family.rootKey}
              family={entry.family}
              manualForkDirByRoot={hubForkManualByRoot}
              setManualForkDirByRoot={setHubForkManualByRoot}
              busy={busy}
              paletteDockBusy={paletteDockDirBusy}
              catalogPublishedDirs={catalogPublishedDirs}
              catalogPublishAllowed={catalogPublishAllowed}
              publishingPackKey={publishingPackKey}
              onExport={onExport}
              onUninstall={onUninstall}
              onPaletteDockToggle={onPaletteDockToggle}
              onPublishToCatalog={onPublishToCatalog}
              onOpenForkInFactory={onOpenForkInFactory}
            />
          ),
        )}
      </>
    )}
  </aside>
);


