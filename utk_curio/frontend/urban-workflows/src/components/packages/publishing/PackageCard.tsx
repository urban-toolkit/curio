import React from "react";
import { PackagePayload } from "../../../api/packagesApi";
import { CatalogPublishPill } from "../CatalogPublishPill";
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
  pkg: PackagePayload;
  isInstalled: boolean;
  hasUpdate: boolean;
  /** The catalog entry for this package, used to show the target update version. */
  catalogRow: PackagePayload | undefined;
  busy: boolean;
  /** When set, this card's secondary actions show a busy state. */
  cardActionDir?: string | null;
  /** Whether dev catalog fixture writes are allowed on this server. */
  catalogPublishAllowed: boolean;
  /** True when the package exists in the shared catalog (drives the Published badge). */
  isPublished?: boolean;
  /** When set, this card's Publish pill shows a busy state. */
  publishingDir?: string | null;
  onInstall: (pkg: PackagePayload) => void;
  onUninstall?: (pkg: PackagePayload) => void;
  onUnpublish?: (pkg: PackagePayload) => void;
  /** Supplied on the /catalog page surface; when omitted, the Publish pill is hidden. */
  onPublish?: (dirName: string) => void;
}

export const PackageCard: React.FC<PackageCardProps> = ({
  pkg,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  cardActionDir,
  catalogPublishAllowed,
  isPublished,
  publishingDir,
  onInstall,
  onUninstall,
  onUnpublish,
  onPublish,
}) => {
  const cardBusy = busy || cardActionDir === pkg.dirName;
  // Author actions are suppressed on read-only packages (e.g. ``curio.builtin``)
  // — the backend rejects publish/uninstall there anyway, so don't tempt
  // users with buttons that 4xx. The Published BADGE still renders (it's
  // informational, not destructive).
  const isAuthorable = pkg.readOnly !== true;
  const showUninstall = isInstalled && onUninstall != null && isAuthorable;
  const showUnpublish = catalogPublishAllowed && onUnpublish != null && isAuthorable;
  const showPublishButton = onPublish != null && catalogPublishAllowed && isAuthorable;
  // The pill renders for two distinct cases:
  //   - The package is already published — show the "Published" badge (purely
  //     informational; no click handler needed, so onPublish may be omitted).
  //   - The user has a local copy AND the operator allows publish AND the
  //     package isn't read-only — show the "Publish" button.
  const showPublishPill = isPublished === true || showPublishButton;

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
        {!isInstalled ? (
          <button
            type="button"
            className={styles.btnInstall}
            disabled={cardBusy}
            onClick={() => onInstall(pkg)}
          >
            Install
          </button>
        ) : hasUpdate ? (
          <button
            type="button"
            className={`${styles.btnInstall} ${styles.btnInstallAccent}`}
            disabled={cardBusy}
            onClick={() => onInstall(catalogRow ?? pkg)}
          >
            Update
          </button>
        ) : null}

        {(showUninstall || showUnpublish || showPublishPill) && (
          <div className={styles.cardSecondaryActions}>
            {showUninstall ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${pkg.name} from this project`}
                onClick={() => onUninstall(pkg)}
              >
                Uninstall
              </button>
            ) : null}
            {showUnpublish ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${pkg.dirName} from the dev catalog (packages/)`}
                onClick={() => onUnpublish(pkg)}
              >
                Unpublish
              </button>
            ) : null}
            {showPublishPill ? (
              <CatalogPublishPill
                variant="hub"
                dirName={pkg.dirName}
                published={!!isPublished}
                allowPublish={catalogPublishAllowed}
                busy={publishingDir === pkg.dirName}
                // Badge case (published=true) ignores onPublish; supply a no-op
                // so the published-but-not-locally-installed path still renders.
                onPublish={onPublish ?? (() => {})}
              />
            ) : null}
          </div>
        )}
      </div>
    </article>
  );
};
