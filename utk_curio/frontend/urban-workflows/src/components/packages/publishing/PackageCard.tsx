import React from "react";
import { PackagePayload } from "../../../api/packagesApi";
import {
  CatalogCategoryBadge,
  CatalogItemRowHeader,
  CatalogKindIcon,
} from "../../catalog/CatalogKindVisuals";
import { CatalogPublishPill, shouldShowPublishPill } from "../CatalogPublishPill";
import { packageInitial,primaryCategory } from "./packageUtils";
import styles from "./PackageCard.module.css";

/**
 * The icon tile is coloured by the package's node category, so it matches both
 * the chip you filtered with and the left border the canvas paints on a node of
 * that category. It used to be a character-sum hash of `dirName`, which meant
 * three `data` packages could render in three unrelated colours while a
 * `computation` package borrowed one of them.
 */
function iconVariantForCategory(category: string): string {
  return (styles as Record<string, string>)[`cardIcon_${category}`] ?? styles.cardIcon_package;
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
  /** Whether shared-catalog writes are allowed on this server. */
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
  // Author actions (Publish / Unpublish) are suppressed on read-only
  // packages (e.g. ``curio.builtin@1``, ``curio.streetvision@1``) — the
  // backend rejects modify/publish there anyway, so don't tempt users with
  // buttons that 4xx. The Published BADGE still renders (it's
  // informational, not destructive).
  const isAuthorable = pkg.readOnly !== true;
  // Uninstall is a project-lockfile operation, not a modification of the
  // package files, so `readOnly` doesn't gate it. Only ``curio.builtin@*``
  // is genuinely non-uninstallable (backend enforces; see
  // ``uninstall_from_project``).
  const isUninstallable = !pkg.dirName.startsWith("curio.builtin@");
  const showUninstall = isInstalled && onUninstall != null && isUninstallable;
  // Unpublish only makes sense for a package that IS in the shared catalog —
  // without the isPublished check it offered to unpublish packages that had
  // never been published.
  const showUnpublish =
    isPublished === true && catalogPublishAllowed && onUnpublish != null && isAuthorable;
  const showPublishPill = shouldShowPublishPill({
    isPublished,
    allowPublish: catalogPublishAllowed,
    canPublish: onPublish != null && isAuthorable,
  });

  const cat = primaryCategory(pkg);

  return (
    <article
      className={styles.card}
      /* Stable hook for e2e locators: the CSS module class is hashed, and
         keying on the display name couples tests to copy that has been
         renamed repeatedly. Mirrors data-pkg-palette-coords. */
      data-pkg-dir={pkg.dirName}
    >
      <div className={`${styles.cardIcon}`}>
        <CatalogKindIcon
          className={`${styles.cardIcon} ${styles.cardIconPackage} ${iconVariantForCategory(cat)} `}
          kind="package" 
          size="md"
          title="Node package" 
        >
          <span className={styles.cardIconText}>
            {packageInitial(pkg.name)}
          </span>
        </CatalogKindIcon>
      </div>

      <div className={styles.cardBody}>
        <CatalogItemRowHeader
          kind="package"
          badge={<CatalogCategoryBadge label={cat} accentKey={cat} />}
        />
        <h3 className={styles.cardTitle}>{pkg.name}</h3>
        <p className={styles.cardMeta}>
          {pkg.publisher || pkg.packageId} · v{pkg.version}
          {pkg.license ? ` · ${pkg.license}` : ""}
        </p>
        <div className={styles.tagRow}>
          <span className={styles.tag}>
            {pkg.templates.length} node{pkg.templates.length === 1 ? "" : "s"}
          </span>
          <span className={styles.tag}>{cat}</span>
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
      
      {/* Actions */}
      <div className={styles.cardAction}>
        {!isInstalled ? (
          <button
            type="button"
            className={styles.btnInstall}
            disabled={cardBusy}
            onClick={() => onInstall(pkg)}
          >
            Add to dataflow
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
                title={`Remove ${pkg.name} from this dataflow`}
                onClick={() => onUninstall(pkg)}
              >
                Remove from dataflow
              </button>
            ) : null}
            {showUnpublish ? (
              <button
                type="button"
                className={styles.btnSecondary}
                disabled={cardBusy}
                title={`Remove ${pkg.dirName} from the shared catalog (packages/)`}
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
