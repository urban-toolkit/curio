import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../../api/packsApi";
import { CatalogPublishPill } from "../../../components/packs/CatalogPublishPill";
import { MyPackIconActions } from "./MyPackIconActions";
import { MyPackSingletonRow } from "./MyPackSingletonRow";
import { MyPacksCallbacks } from "./myPacksTypes";
import styles from "./MyPacks.module.css";

export interface HubInstalledForkRailGroupProps extends MyPacksCallbacks {
  rootKey: string;
  rootPack: PackPayload | null;
  members: PackPayload[];
  busy: boolean;
  paletteDockBusy: string | null;
  catalogPublishedDirs: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackKey: string | null;
}

/**
 * Fork-family accordion in the My Packs sidebar.
 * The lineage-free root pack is fixed in the header; fork members expand below.
 */
export const HubInstalledForkRailGroup = React.memo(function HubInstalledForkRailGroup({
  rootKey,
  rootPack,
  members,
  busy,
  paletteDockBusy,
  catalogPublishedDirs,
  catalogPublishAllowed,
  publishingPackKey,
  onExport,
  onUninstall,
  onPaletteDockToggle,
  onPublishToCatalog,
  onOpenForkInFactory,
}: HubInstalledForkRailGroupProps) {
  const headerName = rootPack?.name ?? rootKey;
  const headerMeta = rootPack
    ? `${rootPack.packId} · v${rootPack.version} · ${rootPack.kinds.length} nodes`
    : `${members.length} fork${members.length === 1 ? "" : "s"}`;

  return (
    <details className={styles.familyDetails}>
      <summary className={styles.familySummary}>
        <div className={styles.familySummaryMain}>
          <span className={styles.familyDot} aria-hidden />
          <div className={styles.familySummaryBody}>
            {rootPack ? (
              <>
                <div className={styles.myPackTitleBlock}>
                  <div className={styles.myPackNameRow}>
                    <button
                      type="button"
                      className={styles.myPackFactoryNameBtn}
                      title="Fork in Node Factory (new install; source unchanged)"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenForkInFactory(rootPack);
                      }}
                    >
                      {headerName}
                    </button>
                    <button
                      type="button"
                      className={styles.myPackIconBtn}
                      title="Fork in Node Factory"
                      aria-label={`Fork ${rootPack.name} in Node Factory`}
                      disabled={busy}
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenForkInFactory(rootPack);
                      }}
                    >
                      <FontAwesomeIcon icon={faPenToSquare} />
                    </button>
                  </div>
                  <CatalogPublishPill
                    variant="hub"
                    dirName={rootPack.dirName}
                    published={catalogPublishedDirs.has(rootPack.dirName)}
                    allowPublish={catalogPublishAllowed}
                    busy={publishingPackKey === rootPack.dirName}
                    onPublish={onPublishToCatalog}
                  />
                </div>
                <span className={styles.myPackVersion}>{headerMeta}</span>
              </>
            ) : (
              <>
                <span className={styles.familySummaryName}>{headerName}</span>
                <span className={styles.myPackVersion}>{headerMeta}</span>
              </>
            )}
          </div>
        </div>

        {rootPack ? (
          <div
            className={styles.familySummaryActions}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <MyPackIconActions
              pack={rootPack}
              busy={busy}
              paletteDockBusy={paletteDockBusy}
              onExport={onExport}
              onUninstall={onUninstall}
              onPaletteDockToggle={onPaletteDockToggle}
            />
          </div>
        ) : (
          <span className={styles.familyCountBadge}>{members.length}</span>
        )}
      </summary>

      <div className={styles.familyMemberList}>
        {members.map((pack) => (
          <MyPackSingletonRow
            key={pack.dirName}
            pack={pack}
            nested
            busy={busy}
            paletteDockBusy={paletteDockBusy}
            catalogPublishedDirs={catalogPublishedDirs}
            catalogPublishAllowed={catalogPublishAllowed}
            publishingPackKey={publishingPackKey}
            onExport={onExport}
            onUninstall={onUninstall}
            onPaletteDockToggle={onPaletteDockToggle}
            onPublishToCatalog={onPublishToCatalog}
            onOpenForkInFactory={onOpenForkInFactory}
          />
        ))}
      </div>
    </details>
  );
});
