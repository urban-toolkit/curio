import React from "react";
import { PackagePayload } from "../../api/packagesApi";
import { CatalogDrawerTitle, CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import { CatalogPublishPill } from "../../components/packages/CatalogPublishPill";
import { primaryCategory } from "../../components/packages/publishing/packageUtils";
import browseStyles from "./CatalogBrowseLayout.module.css";

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

export interface PackageBrowseDrawerProps {
  pkg: PackagePayload | null;
  isInstalled: boolean;
  hasUpdate: boolean;
  catalogRow: PackagePayload | undefined;
  busy: boolean;
  catalogPublishAllowed: boolean;
  isPublished?: boolean;
  publishingDir?: string | null;
  showPublish: boolean;
  onInstall: (pkg: PackagePayload) => void;
  onPublish?: (dirName: string) => void;
}

export const PackageBrowseDrawer: React.FC<PackageBrowseDrawerProps> = ({
  pkg,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  catalogPublishAllowed,
  isPublished,
  publishingDir,
  showPublish,
  onInstall,
  onPublish,
}) => {
  if (!pkg) {
    return (
      <aside className={browseStyles.browseDrawer}>
        <div className={browseStyles.drawerHeader}>
          <CatalogDrawerTitle kind="package" title="Package details" />
          <button className={browseStyles.drawerClose} type="button">✕</button>
        </div>
        <div className={browseStyles.drawerEmpty}>Select a package to see details</div>
      </aside>
    );
  }

  const cat = primaryCategory(pkg);
  const isAuthorable = pkg.readOnly !== true;
  const showPublishPill = isPublished === true || (onPublish != null && catalogPublishAllowed && isAuthorable);

  return (
    <aside className={browseStyles.browseDrawer}>
      <div className={browseStyles.drawerHeader}>
        <CatalogDrawerTitle kind="package" title="Package details" />
        <button className={browseStyles.drawerClose} type="button" aria-label="Close">✕</button>
      </div>

      <div className={browseStyles.drawerKindHero}>
        <CatalogKindIcon kind="package" size="lg" title="Node package" />
      </div>

      <div className={browseStyles.drawerDatasetName}>
        <h2>{pkg.name}</h2>
        <div className={browseStyles.drawerBadgesRow}>
          <span className={`${browseStyles.drawerFormatBadge} ${browseStyles.dfmt_parquet}`}>
            {cat}
          </span>
          <span className={browseStyles.drawerHubBadge}>Node pack</span>
          {isInstalled ? (
            <span className={`${browseStyles.drawerFormatBadge} ${browseStyles.dfmt_geojson}`}>✓ In defaults</span>
          ) : null}
        </div>
      </div>

      <div className={browseStyles.drawerPublisher}>
        <span className={browseStyles.drawerPublisherText}>
          {pkg.publisher || pkg.packageId} · v{pkg.version}
        </span>
      </div>

      <div className={browseStyles.drawerMeta}>
        <span>
          {pkg.templates.length} nodes · {pkg.packageId}
        </span>
        <span className={browseStyles.drawerMetaRight}>{relativeFromMs(pkg.createdAtMs)}</span>
      </div>

      {pkg.description ? (
        <div className={browseStyles.drawerSection}>
          <p className={browseStyles.drawerDescription}>{pkg.description}</p>
        </div>
      ) : null}

      <div className={browseStyles.drawerSection}>
        <p className={browseStyles.drawerSectionLabel}>Package info</p>
        <div className={browseStyles.infoRow}>
          <span className={browseStyles.infoRowLabel}>Channel</span>
          <span className={browseStyles.infoRowValue}>{pkg.channel ?? "stable"}</span>
        </div>
        <div className={browseStyles.infoRow}>
          <span className={browseStyles.infoRowLabel}>Templates</span>
          <span className={browseStyles.infoRowValue}>{pkg.templates.length}</span>
        </div>
        {pkg.license ? (
          <div className={browseStyles.infoRow}>
            <span className={browseStyles.infoRowLabel}>License</span>
            <span className={browseStyles.infoRowValue}>{pkg.license}</span>
          </div>
        ) : null}
      </div>

      <div className={browseStyles.drawerSection}>
        <p className={browseStyles.drawerSectionLabel}>Nodes in pack</p>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "#555" }}>
          {pkg.templates.slice(0, 12).map((t) => (
            <li key={t.id}>{t.label}</li>
          ))}
          {pkg.templates.length > 12 ? (
            <li style={{ color: "#999" }}>…and {pkg.templates.length - 12} more</li>
          ) : null}
        </ul>
      </div>

      <div className={browseStyles.drawerCtas}>
        {!isInstalled ? (
          <button
            type="button"
            className={browseStyles.addToPaletteBtn}
            disabled={busy}
            onClick={() => onInstall(pkg)}
          >
            Install to all projects
          </button>
        ) : hasUpdate ? (
          <button
            type="button"
            className={browseStyles.addToPaletteBtn}
            disabled={busy}
            onClick={() => onInstall(catalogRow ?? pkg)}
          >
            Update all projects
          </button>
        ) : (
          <p className={browseStyles.drawerDescription} style={{ textAlign: "center" }}>
            This package is in your defaults list for new and existing projects.
          </p>
        )}
        {showPublishPill ? (
          <div style={{ display: "flex", justifyContent: "center" }}>
            <CatalogPublishPill
              variant="hub"
              dirName={pkg.dirName}
              published={!!isPublished}
              allowPublish={catalogPublishAllowed}
              busy={publishingDir === pkg.dirName}
              onPublish={onPublish ?? (() => {})}
            />
          </div>
        ) : null}
      </div>
    </aside>
  );
};
