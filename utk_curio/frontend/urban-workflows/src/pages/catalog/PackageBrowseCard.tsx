import React from "react";
import { PackagePayload } from "../../api/packagesApi";
import { CatalogItemStripHeader } from "../../components/catalog/CatalogKindVisuals";
import { CatalogPublishPill } from "../../components/packages/CatalogPublishPill";
import { primaryCategory } from "../../components/packages/publishing/packageUtils";
import styles from "./PackageBrowseCard.module.css";

type StripVariant = "warm" | "cool" | "violet";

const STRIP_VARIANTS: StripVariant[] = ["warm", "cool", "violet"];

function stripVariantForPack(dirName: string): StripVariant {
  let hash = 0;
  for (let i = 0; i < dirName.length; i++) {
    hash = (hash + dirName.charCodeAt(i)) % STRIP_VARIANTS.length;
  }
  return STRIP_VARIANTS[hash]!;
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
  const strip = stripVariantForPack(pkg.dirName);
  const cat = primaryCategory(pkg);
  const cardBusy = busy;
  const isAuthorable = pkg.readOnly !== true;
  const showPublishPill = isPublished === true || (onPublish != null && catalogPublishAllowed && isAuthorable);

  return (
    <article
      className={[
        styles.card,
        selected ? styles.cardActive : "",
        styles[`card_${strip}`],
      ].join(" ")}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onSelect();
      }}
    >
      <div className={`${styles.cardStrip} ${styles[`strip_${strip}`]}`}>
        <CatalogItemStripHeader
          kind="package"
          badge={<span className={styles.kindBadge}>{cat}</span>}
          trailing={
            <>
              {isInstalled ? <span className={styles.stripBadge}>✓ DEFAULTS</span> : null}
              {selected ? <span className={styles.selectedDot} /> : null}
            </>
          }
        />
      </div>

      <div className={styles.cardBody}>
        <h2 className={styles.cardTitle}>{pkg.name}</h2>
        <p className={styles.publisher}>
          {pkg.publisher || pkg.packageId} · v{pkg.version}
          {pkg.license ? ` · ${pkg.license}` : ""}
        </p>
        <p
          className={styles.cardDescription}
          {...(!pkg.description ? { "aria-hidden": true } : {})}
        >
          {pkg.description || "\u00a0"}
        </p>
        <div className={styles.tagRow}>
          <span className={styles.tag}>
            {pkg.templates.length} node{pkg.templates.length === 1 ? "" : "s"}
          </span>
          <span className={`${styles.tag} ${styles.tagAccent}`}>{cat}</span>
          {(pkg.channel ?? "stable") !== "stable" ? (
            <span className={styles.tag}>{pkg.channel}</span>
          ) : null}
          {hasUpdate && catalogRow ? (
            <span className={`${styles.tag} ${styles.tagUpdate}`}>
              Update to {catalogRow.version}
            </span>
          ) : null}
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.metaLeft}>
          {pkg.templates.length} templates · {pkg.packageId}
        </span>
        <span className={styles.metaRight}>{relativeFromMs(pkg.createdAtMs)}</span>
      </div>

      <div className={styles.cardActions}>
        <div className={styles.cardActionsLeft}>
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
        <div className={styles.cardActionsRight}>
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
              Install
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
