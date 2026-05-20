import React from "react";
import { PackPayload } from "../../../api/packsApi";
import { packInitial, primaryCategory } from "./packUtils";
import styles from "./PackCard.module.css";

/** CSS class variants cycled deterministically per pack dirName. */
const CARD_ICON_VARIANTS = [
  styles.cardIconWarm,
  styles.cardIconCool,
  styles.cardIconViolet,
] as const;

function iconVariantForPack(dirName: string): string {
  let hash = 0;
  for (let i = 0; i < dirName.length; i++) {
    hash = (hash + dirName.charCodeAt(i)) % CARD_ICON_VARIANTS.length;
  }
  return CARD_ICON_VARIANTS[hash]!;
}

export interface PackCardProps {
  pack: PackPayload;
  isInstalled: boolean;
  hasUpdate: boolean;
  /** The catalog entry for this pack, used to show the target update version. */
  catalogRow: PackPayload | undefined;
  busy: boolean;
  /** Called when the user clicks Install or Update. */
  onInstall: (pack: PackPayload) => void;
}

export const PackCard: React.FC<PackCardProps> = ({
  pack,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  onInstall,
}) => (
  <article className={styles.card}>
    <div className={`${styles.cardIcon} ${iconVariantForPack(pack.dirName)}`}>
      {packInitial(pack.name)}
    </div>

    <div className={styles.cardBody}>
      <h3 className={styles.cardTitle}>{pack.name}</h3>
      <p className={styles.cardMeta}>
        {pack.publisher || pack.packId} · v{pack.version}
        {pack.license ? ` · ${pack.license}` : ""}
      </p>
      <div className={styles.tagRow}>
        <span className={styles.tag}>
          {pack.kinds.length} node{pack.kinds.length === 1 ? "" : "s"}
        </span>
        <span className={styles.tag}>{primaryCategory(pack)}</span>
        {hasUpdate && catalogRow ? (
          <span className={`${styles.tag} ${styles.tagUpdate}`}>
            Update to {catalogRow.version}
          </span>
        ) : null}
      </div>
    </div>

    <div className={styles.cardAction}>
      {isInstalled ? (
        hasUpdate ? (
          <button
            type="button"
            className={`${styles.btnInstall} ${styles.btnInstallAccent}`}
            disabled={busy}
            onClick={() => onInstall(catalogRow ?? pack)}
          >
            Update
          </button>
        ) : (
          <span className={styles.btnInstalled}>Installed</span>
        )
      ) : (
        <button
          type="button"
          className={styles.btnInstall}
          disabled={busy}
          onClick={() => onInstall(pack)}
        >
          Install
        </button>
      )}
    </div>
  </article>
);

