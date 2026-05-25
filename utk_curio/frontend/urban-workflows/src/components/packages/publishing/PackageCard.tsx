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
  onInstall: (pkg: PackagePayload) => void;
  onUninstall?: (pkg: PackagePayload) => void;
  onUnpublish?: (pkg: PackagePayload) => void;
}

export const PackageCard: React.FC<PackageCardProps> = ({
  pkg,
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
  const cardBusy = busy || cardActionDir === pkg.dirName;
  const showUninstall = isInstalled && onUninstall != null;
  const showUnpublish = catalogPublishAllowed && onUnpublish != null;

  return (
    <article className={styles.card}>
      <div className={`${styles.cardIcon} ${iconVariantForPack(pkg.dirName)}`}>
        {packageInitial(pkg.name)}
      </div>

      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{pkg.name}</h3>
        <p className={styles.cardMeta}>
          {pkg.publisher || pkg.packageId} · v{pkg.version}
          {pkg.license ? ` · ${pkg.license}` : ""}
        </p>
        <div className={styles.tagRow}>
          <span className={styles.tag}>
            {pkg.templates.length} node{pkg.templates.length === 1 ? "" : "s"}
          </span>
          <span className={styles.tag}>{primaryCategory(pkg)}</span>
          {(pkg.channel ?? "stable") !== "stable" ? (
            <span className={`${styles.tag} ${styles.tagChannel}`} title={`Release channel: ${pkg.channel}`}>
              {pkg.channel}
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
              onClick={() => onInstall(catalogRow ?? pkg)}
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
            onClick={() => onInstall(pkg)}
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
                title={`Remove ${pkg.name} from this dataflow`}
                onClick={() => onUninstall(pkg)}
              >
                Uninstall
              </button>
            ) : null}
            {showUnpublish ? (
              <button
                type="button"
                className={styles.btnSecondaryDanger}
                disabled={cardBusy}
                title={`Remove ${pkg.dirName} from the dev catalog (packages/)`}
                onClick={() => onUnpublish(pkg)}
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
