import React from "react";
import { PackagePayload } from "../../../api/packagesApi";
import { packageInitial, primaryCategory } from "./packageUtils";
import styles from "./PackageCard.module.css";

/** CSS class variants cycled deterministically per package dirName. */
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

export interface PackageCardProps {
  package: PackagePayload;
  isInstalled: boolean;
  hasUpdate: boolean;
  /** The catalog entry for this package, used to show the target update version. */
  catalogRow: PackagePayload | undefined;
  busy: boolean;
  /** When set, this card's secondary actions show a busy state. */
  cardActionDir?: string | null;
  /** Whether dev catalog fixture writes are allowed on this server. */
  catalogPublishAllowed: boolean;
  onInstall: (package: PackagePayload) => void;
  onUninstall?: (package: PackagePayload) => void;
  onUnpublish?: (package: PackagePayload) => void;
}

export const PackageCard: React.FC<PackageCardProps> = ({
  package,
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
  const cardBusy = busy || cardActionDir === package.dirName;
  const showUninstall = isInstalled && onUninstall != null;
  const showUnpublish = catalogPublishAllowed && onUnpublish != null;

  return (
    <article className={styles.card}>
      <div className={`${styles.cardIcon} ${iconVariantForPack(package.dirName)}`}>
        {packageInitial(package.name)}
      </div>

      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{package.name}</h3>
        <p className={styles.cardMeta}>
          {package.publisher || package.packageId} · v{package.version}
          {package.license ? ` · ${package.license}` : ""}
        </p>
        <div className={styles.tagRow}>
          <span className={styles.tag}>
            {package.kinds.length} node{package.kinds.length === 1 ? "" : "s"}
          </span>
          <span className={styles.tag}>{primaryCategory(package)}</span>
          {(package.channel ?? "stable") !== "stable" ? (
            <span className={`${styles.tag} ${styles.tagChannel}`} title={`Release channel: ${package.channel}`}>
              {package.channel}
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
              onClick={() => onInstall(catalogRow ?? package)}
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
            onClick={() => onInstall(package)}
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
                title={`Remove ${package.name} from this workspace`}
                onClick={() => onUninstall(package)}
              >
                Uninstall
              </button>
            ) : null}
            {showUnpublish ? (
              <button
                type="button"
                className={styles.btnSecondaryDanger}
                disabled={cardBusy}
                title={`Remove ${package.dirName} from the dev catalog (packages/)`}
                onClick={() => onUnpublish(package)}
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
