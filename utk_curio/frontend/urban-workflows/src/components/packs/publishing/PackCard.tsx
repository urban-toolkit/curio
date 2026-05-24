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
  /** When set, this card's secondary actions show a busy state. */
  cardActionDir?: string | null;
  /** Whether dev catalog fixture writes are allowed on this server. */
  catalogPublishAllowed: boolean;
  onInstall: (pack: PackPayload) => void;
  onUninstall?: (pack: PackPayload) => void;
  onUnpublish?: (pack: PackPayload) => void;
}

export const PackCard: React.FC<PackCardProps> = ({
  pack,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  cardActionDir,
  catalogPublishAllowed,
  onInstall,
  onUninstall,
  onUnpublish,
}) => {
  const cardBusy = busy || cardActionDir === pack.dirName;
  const showUninstall = isInstalled && onUninstall != null;
  const showUnpublish = catalogPublishAllowed && onUnpublish != null;

  return (
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
          {(pack.channel ?? "stable") !== "stable" ? (
            <span className={`${styles.tag} ${styles.tagChannel}`} title={`Release channel: ${pack.channel}`}>
              {pack.channel}
            </span>
          ) : null}
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
              disabled={cardBusy}
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
            disabled={cardBusy}
            onClick={() => onInstall(pack)}
          >
            Install
          </button>
        )}

        {(showUninstall || showUnpublish) && (
          <div className={styles.cardSecondaryActions}>
            {showUninstall ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${pack.name} from this workspace`}
                onClick={() => onUninstall(pack)}
              >
                Uninstall
              </button>
            ) : null}
            {showUnpublish ? (
              <button
                type="button"
                className={styles.btnSecondaryDanger}
                disabled={cardBusy}
                title={`Remove ${pack.dirName} from the dev catalog (packs/)`}
                onClick={() => onUnpublish(pack)}
              >
                Unpublish
              </button>
            ) : null}
          </div>
        )}
      </div>
    </article>
  );
};
