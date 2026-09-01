import React from "react";
import { PackagePayload } from "../../api/packagesApi";
import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import {
  CatalogPublishPill,
  shouldShowPublishPill,
} from "../../components/packages/CatalogPublishPill";
import { primaryCategory } from "../../components/packages/publishing/packageUtils";
import browseStyles from "./CatalogBrowseLayout.module.css";
import styles from "./PackageBrowseCard.module.css";

/**
 * The card's colour is its node category — the same palette the canvas paints a
 * node's left border with, and the same one behind the category chips in the
 * filter bar. It used to be a character-sum hash of `dirName`, so the colour
 * told you nothing: three `data` packages rendered orange, violet and blue,
 * and a `computation` package shared the blue.
 */
function stripClass(styleMap: Record<string, string>, prefix: string, category: string): string {
  return styleMap[`${prefix}_${category}`] ?? styleMap[`${prefix}_package`] ?? "";
}

function relativeFromMs(ms?: number): string {
  if (ms == null || ms <= 0) return "—";
  const delta = Date.now() - ms;
  if (!Number.isFinite(delta)) return "—";
  const minutes = Math.max(1, Math.round(delta / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export interface PackageBrowseCardProps {
  pkg: PackagePayload;
  selected: boolean;
  isInstalled: boolean;
  hasUpdate: boolean;
  catalogRow: PackagePayload | undefined;
  busy: boolean;
  catalogPublishAllowed: boolean;
  isPublished?: boolean;
  publishingDir?: string | null;
  showPublish: boolean;
  onSelect: () => void;
  onInstall: (pkg: PackagePayload) => void;
  onPublish?: (dirName: string) => void;
}

export const PackageBrowseCard: React.FC<PackageBrowseCardProps> = ({
  pkg,
  selected,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  catalogPublishAllowed,
  isPublished,
  publishingDir,
  showPublish,
  onSelect,
  onInstall,
  onPublish,
}) => {
  const cat = primaryCategory(pkg);
  const cardStyles = styles as Record<string, string>;
  const cardBusy = busy;
  const isAuthorable = pkg.readOnly !== true;
  const showPublishPill = shouldShowPublishPill({
    isPublished,
    allowPublish: catalogPublishAllowed,
    canPublish: onPublish != null && isAuthorable,
  });

  return (
    <article
      className={[
        browseStyles.card,
        selected ? browseStyles.cardActive : "",
        selected ? styles.cardActive : "",
        stripClass(cardStyles, "card", cat),
      ].join(" ")}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${browseStyles.cardStrip} ${stripClass(cardStyles, "strip", cat)}`}>
        <CatalogItemStripHeader
          kind="package"
          badge={<span className={browseStyles.cardFormatBadge}>{cat}</span>}
          trailing={
            isInstalled ? <span className={browseStyles.stripBadgePopular}>✓ In defaults</span> : null
          }
        />
      </div>

      <div className={browseStyles.cardBody}>
        <h2 className={browseStyles.cardTitle}>{pkg.name}</h2>
        <p className={browseStyles.publisher}>
          {pkg.publisher || pkg.packageId} · v{pkg.version}
          {pkg.license ? ` · ${pkg.license}` : ""}
        </p>
        <p
          className={browseStyles.cardDescription}
          {...(!pkg.description ? { "aria-hidden": true } : {})}
        >
          {pkg.description || "\u00a0"}
        </p>
        <div className={browseStyles.tagRow}>
          <span className={browseStyles.tag}>
            {pkg.templates.length} node{pkg.templates.length === 1 ? "" : "s"}
          </span>
          <span className={browseStyles.tag}>{cat}</span>
          {(pkg.channel ?? "stable") !== "stable" ? (
            <span className={browseStyles.tag}>{pkg.channel}</span>
          ) : null}
          {hasUpdate && catalogRow ? (
            <span className={`${browseStyles.tag} ${styles.tagUpdate}`}>
              Update to {catalogRow.version}
            </span>
          ) : null}
        </div>
      </div>

      <div className={browseStyles.cardMeta}>
        <span className={browseStyles.metaLeft}>
          {pkg.templates.length} templates · {pkg.packageId}
        </span>
        <span className={browseStyles.metaRight}>{relativeFromMs(pkg.createdAtMs)}</span>
      </div>

      <div className={browseStyles.cardActions}>
        <div className={browseStyles.cardActionsLeft}>
          {showPublishPill ? (
            <CatalogPublishPill
              variant="hub"
              dirName={pkg.dirName}
              published={!!isPublished}
              allowPublish={catalogPublishAllowed}
              busy={publishingDir === pkg.dirName}
              onPublish={onPublish ?? (() => {})}
            />
          ) : null}
        </div>
        <div className={browseStyles.cardActionsRight}>
          {!isInstalled ? (
            <button
              type="button"
              className={styles.installButton}
              disabled={cardBusy}
              onClick={(e) => {
                e.stopPropagation();
                onInstall(pkg);
              }}
            >
              Add to all projects
            </button>
          ) : hasUpdate ? (
            <button
              type="button"
              className={styles.updateButton}
              disabled={cardBusy}
              onClick={(e) => {
                e.stopPropagation();
                onInstall(catalogRow ?? pkg);
              }}
            >
              Update
            </button>
          ) : (
            <span className={styles.installedHint}>In defaults</span>
          )}
        </div>
      </div>
    </article>
  );
};
