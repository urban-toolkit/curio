import React from "react";
import { PackagePayload } from "../../api/packagesApi";
import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
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
  onSelect: () => void;
  onViewDetails?: () => void;
}

export const PackageBrowseCard: React.FC<PackageBrowseCardProps> = ({
  pkg,
  selected,
  isInstalled,
  hasUpdate,
  catalogRow,
  onSelect,
  onViewDetails,
}) => {
  const cat = primaryCategory(pkg);
  const cardStyles = styles as Record<string, string>;

  return (
    <article
      className={[
        browseStyles.card,
        selected ? browseStyles.cardActive : "",
        selected ? styles.cardActive : "",
        stripClass(cardStyles, "card", cat),
      ].join(" ")}
      // Same cross-surface identity attribute the drawer's PackageCard carries.
      data-pkg-dir={pkg.dirName}
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
            isInstalled ? <span className={browseStyles.stripBadgePopular}>✓ In all projects</span> : null
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
          <span className={browseStyles.tag} data-curio-tag-chip="true">
            {pkg.templates.length} node{pkg.templates.length === 1 ? "" : "s"}
          </span>
          <span className={browseStyles.tag} data-curio-tag-chip="true">{cat}</span>
          {(pkg.channel ?? "stable") !== "stable" ? (
            <span className={browseStyles.tag} data-curio-tag-chip="true">{pkg.channel}</span>
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
        {/* Identity and one way in. Publishing is an account-level decision
            about one package and belongs in the detail drawer beside the other
            decisions, not on every tile in the grid. */}
        <div className={browseStyles.cardActionsLeft} />
        <div className={browseStyles.cardActionsRight}>
          <button
            className={browseStyles.linkButton}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              // The modal, not the drawer. This used to call `onSelect`, so on
              // a card whose drawer was already open the click did nothing.
              (onViewDetails ?? onSelect)();
            }}
          >
            View details
          </button>
        </div>
      </div>
    </article>
  );
};
