import React from "react";
import { PackagePayload } from "../../api/packagesApi";
import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import {
  catalogIsFresh,
  catalogRelativeTime,
} from "../../components/catalog/catalogTimeFormat";
import { CatalogBrowseDrawerShell } from "./CatalogBrowseDrawerShell";
import {
  CatalogBrowseDrawerBody,
  CatalogDrawerList,
  CatalogDrawerSection,
} from "./CatalogBrowseDrawerBody";
import {
  CatalogPublishPill,
  shouldShowPublishPill,
} from "../../components/packages/CatalogPublishPill";
import { primaryCategory } from "../../components/packages/publishing/packageUtils";
import browseStyles from "./CatalogBrowseLayout.module.css";

/** Cap the "Nodes in pack" list; the remainder collapses into a "…and N more" row. */
const TEMPLATE_PREVIEW_LIMIT = 12;

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
  onClose: () => void;
  onLayoutChange?: (slotOpen: boolean) => void;
}

export const PackageBrowseDrawer: React.FC<PackageBrowseDrawerProps> = ({
  pkg,
  onClose,
  onLayoutChange,
  ...rest
}) => (
  <CatalogBrowseDrawerShell presented={pkg != null} onLayoutChange={onLayoutChange}>
    {pkg ? <PackageBrowseDrawerContent pkg={pkg} onClose={onClose} {...rest} /> : null}
  </CatalogBrowseDrawerShell>
);

type PackageBrowseDrawerContentProps = Omit<PackageBrowseDrawerProps, "pkg"> & {
  pkg: PackagePayload;
};

const PackageBrowseDrawerContent: React.FC<PackageBrowseDrawerContentProps> = ({
  pkg,
  isInstalled,
  hasUpdate,
  catalogRow,
  busy,
  catalogPublishAllowed,
  isPublished,
  publishingDir,
  onInstall,
  onPublish,
  onClose,
}) => {
  const cat = primaryCategory(pkg);
  const showPublishPill = shouldShowPublishPill({
    isPublished,
    allowPublish: catalogPublishAllowed,
    canPublish: onPublish != null && pkg.readOnly !== true,
  });
  const shown = pkg.templates.slice(0, TEMPLATE_PREVIEW_LIMIT);
  const hidden = pkg.templates.length - shown.length;

  return (
    <CatalogBrowseDrawerBody
      kind="package"
      headerTitle="Package details"
      onClose={onClose}
      hero={
        <div className={browseStyles.drawerKindHero}>
          <CatalogKindIcon kind="package" size="lg" title="Node package" />
        </div>
      }
      title={pkg.name}
      badges={
        <>
          <span className={browseStyles.drawerCategoryBadge}>{cat}</span>
          {isInstalled ? (
            <span className={browseStyles.drawerInstalledBadge}>✓ In defaults</span>
          ) : null}
        </>
      }
      subtitle={`${pkg.publisher || pkg.packageId} · v${pkg.version}`}
      metaLeft={`${pkg.templates.length} nodes · ${pkg.packageId}`}
      metaRight={catalogRelativeTime(pkg.createdAtMs)}
      fresh={catalogIsFresh(pkg.createdAtMs)}
      description={pkg.description}
      infoLabel="Package info"
      infoRows={[
        { label: "Channel", value: pkg.channel ?? "stable" },
        { label: "Templates", value: pkg.templates.length },
        pkg.license ? { label: "License", value: pkg.license } : null,
      ]}
      sections={
        <CatalogDrawerSection label="Nodes in pack">
          <CatalogDrawerList
            items={shown.map((t) => <li key={t.id}>{t.label}</li>)}
            moreLabel={hidden > 0 ? `…and ${hidden} more` : null}
          />
        </CatalogDrawerSection>
      }
      primaryAction={
        !isInstalled ? (
          <button
            type="button"
            className={browseStyles.addToPaletteBtn}
            disabled={busy}
            onClick={() => onInstall(pkg)}
          >
            Add to all projects
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
        )
      }
      publishPill={
        showPublishPill ? (
          <CatalogPublishPill
            variant="hub"
            dirName={pkg.dirName}
            published={!!isPublished}
            allowPublish={catalogPublishAllowed}
            busy={publishingDir === pkg.dirName}
            onPublish={onPublish ?? (() => {})}
          />
        ) : null
      }
    />
  );
};
