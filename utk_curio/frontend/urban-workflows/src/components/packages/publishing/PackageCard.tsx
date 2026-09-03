import React from "react";
import { PackagePayload } from "../../../api/packagesApi";
import {
  CatalogKindIcon,
} from "../../catalog/CatalogKindVisuals";
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
  onInstall: (pkg: PackagePayload) => void;
  onUninstall?: (pkg: PackagePayload) => void;
  /** False in a dataflow that has not been saved yet. Only wording now: the
   *  control stays enabled and its click saves the dataflow before removing,
   *  because a package the account defaults seeded into a new dataflow has to
   *  be removable from it (#220). */
  hasProject?: boolean;
  onOpenDetails?: (pkg: PackagePayload) => void;
}

export const PackageCard: React.FC<PackageCardProps> = ({
  pkg,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  cardActionDir,
  onInstall,
  onUninstall,
  hasProject = true,
  onOpenDetails,
}) => {
  const cardBusy = busy || cardActionDir === pkg.dirName;
  // Author actions (Publish / Unpublish) are suppressed on read-only
  // packages (e.g. ``curio.builtin@1``, ``curio.streetvision@1``) — the
  // backend rejects modify/publish there anyway, so don't tempt users with
  // buttons that 4xx. The Published BADGE still renders (it's
  // informational, not destructive).
  // Uninstall is a project-lockfile operation, not a modification of the
  // package files, so `readOnly` doesn't gate it. Only ``curio.builtin@*``
  // is genuinely non-uninstallable (backend enforces; see
  // ``uninstall_from_project``).
  const isUninstallable = !pkg.dirName.startsWith("curio.builtin@");
  const showUninstall = isInstalled && onUninstall != null && isUninstallable;
  // Unpublish only makes sense for a package that IS in the shared catalog —
  // without the isPublished check it offered to unpublish packages that had
  // never been published.

  const cat = primaryCategory(pkg);

  return (
    <article
      className={styles.card}
      /* Stable hook for e2e locators: the CSS module class is hashed, and
         keying on the display name couples tests to copy that has been
         renamed repeatedly. Mirrors data-pkg-palette-coords. */
      data-pkg-dir={pkg.dirName}
    >
      {/* The square, and the way into the package's details beneath it - the
          same position on every drawer card. */}
      <div className={styles.cardAvatarCol}>
        {/* The square is the same affordance as the link beneath it, so it is
            a button too - on every drawer card. */}
        <button
          type="button"
          className={`${styles.cardIcon} ${styles.cardAvatarButton}`}
          title={`View ${pkg.name} details`}
          aria-label={`View ${pkg.name} details`}
          disabled={!onOpenDetails}
          onClick={() => onOpenDetails?.(pkg)}
        >
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
        </button>
        {onOpenDetails ? (
          <button
            type="button"
            className={styles.avatarDetailsLink}
            onClick={() => onOpenDetails(pkg)}
          >
            View details
          </button>
        ) : null}
      </div>

      {/* The Agent drawer's card body, which is the baseline all three now
          share: a title and ONE meta line. This carried a `CatalogItemRowHeader`
          strip, a differently-classed `<p className={cardMeta}>`, and a
          four-chip tag row on top of that - three rows of chrome around one
          package name, where the Agent card next door had one.

          Nothing informative was dropped, only re-sited: the category, the node
          count and a non-stable channel all read perfectly well as meta text,
          and the update chip stays a chip because it is the one item here that
          is actionable state rather than description. */}
      <div className={styles.cardBody}>
        <h3 className={styles.cardTitle}>{pkg.name}</h3>
        <div className={styles.cardMetaRow}>
          <span className={styles.cardMetaText}>
            {[
              pkg.publisher || pkg.packageId,
              `v${pkg.version}`,
              cat,
              `${pkg.templates.length} node${pkg.templates.length === 1 ? "" : "s"}`,
              (pkg.channel ?? "stable") !== "stable" ? pkg.channel : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
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
            title={`Add ${pkg.name} to this project`}
            onClick={() => onInstall(pkg)}
          >
            Add to project
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

        {/* Publishing is not a card action on any surface: it is an
            account-level decision about one package, and it lives in the Node
            Catalog page's detail drawer with the other decisions. */}
        {showUninstall ? (
          <div className={styles.cardSecondaryActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              /* Not gated on `hasProject`, matching its two peers. This branch
                 IS reachable before the first save: `projectInstalledDirs`
                 falls back to the account defaults when there is no project, so
                 a default package renders Remove on an unsaved dataflow - and
                 the gate then left a disabled control and nothing else, the
                 same dead end as the Agent and Data cards (#190, #199).
                 `performUninstall` saves the dataflow on the click now. */
              disabled={cardBusy}
              title={
                hasProject
                  ? `Remove ${pkg.name} from this project`
                  : `Remove ${pkg.name}; this saves the dataflow first`
              }
              onClick={() => onUninstall(pkg)}
            >
              Remove from project
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
};
