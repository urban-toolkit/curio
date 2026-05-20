import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPenToSquare } from "@fortawesome/free-solid-svg-icons";
import { PackPayload } from "../../../api/packsApi";
import { CatalogPublishPill } from "../../../components/packs/CatalogPublishPill";
import { formatForkOfSubtitle } from "../../../utils/forkPackLineage";
import { MyPackIconActions } from "./MyPackIconActions";
import { MyPacksCallbacks } from "./myPacksTypes";
import styles from "./MyPacks.module.css";

export interface MyPackSingletonRowProps extends MyPacksCallbacks {
  pack: PackPayload;
  nested?: boolean;
  busy: boolean;
  paletteDockBusy: string | null;
  catalogPublishedDirs: ReadonlySet<string>;
  catalogPublishAllowed: boolean;
  publishingPackKey: string | null;
}

/**
 * A single-pack row in the My Packs sidebar.
 * Displays the pack name (clickable → Node Factory fork), publish pill,
 * version / packId, optional fork-of line, and the three icon actions.
 */
export const MyPackSingletonRow: React.FC<MyPackSingletonRowProps> = ({
  pack,
  nested = false,
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
}) => (
  <div className={`${styles.myPackRow}${nested ? ` ${styles.myPackRowNested}` : ""}`}>
    <div>
      <div className={styles.myPackTitleBlock}>
        <div className={styles.myPackNameRow}>
          <button
            type="button"
            className={styles.myPackFactoryNameBtn}
            title="Fork in Node Factory (new install; source unchanged)"
            onClick={() => onOpenForkInFactory(pack)}
          >
            {pack.name}
          </button>
          <button
            type="button"
            className={styles.myPackIconBtn}
            title="Fork in Node Factory"
            aria-label={`Fork ${pack.name} in Node Factory`}
            disabled={busy}
            onClick={() => onOpenForkInFactory(pack)}
          >
            <FontAwesomeIcon icon={faPenToSquare} />
          </button>
        </div>
        <CatalogPublishPill
          variant="hub"
          dirName={pack.dirName}
          published={catalogPublishedDirs.has(pack.dirName)}
          allowPublish={catalogPublishAllowed}
          busy={publishingPackKey === pack.dirName}
          onPublish={onPublishToCatalog}
        />
      </div>
      <span className={styles.myPackVersion}>
        {pack.packId} · v{pack.version}
      </span>
      {pack.lineage ? (
        <p className={styles.hubForkOfLine}>{formatForkOfSubtitle(pack.lineage).text}</p>
      ) : null}
    </div>

    <MyPackIconActions
      pack={pack}
      busy={busy}
      paletteDockBusy={paletteDockBusy}
      onExport={onExport}
      onUninstall={onUninstall}
      onPaletteDockToggle={onPaletteDockToggle}
    />
  </div>
);

