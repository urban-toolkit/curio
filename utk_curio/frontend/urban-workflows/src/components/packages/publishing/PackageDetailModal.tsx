import React, { useState } from "react";
import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { packagesApi } from "../../../api/packagesApi";
import type { PackagePayload } from "../../../api/packagesApi";
import { primaryCategory } from "./packageUtils";
import styles from "../../agents/catalog/AgentDetailModal.module.css";

export interface PackageDetailModalProps {
  pkg: PackagePayload;
  /** In the user's "all projects" defaults list. */
  inAllProjects?: boolean;
  /** Listed in the shared catalog. */
  isPublished?: boolean;
  onClose: () => void;
}

/** Human-readable size for a dependency map that may be absent. */
function dependencyLines(pkg: PackagePayload): string[] {
  const deps = pkg.dependencies as unknown as Record<string, unknown> | null;
  if (!deps) return [];
  const out: string[] = [];
  for (const [group, value] of Object.entries(deps)) {
    if (value == null) continue;
    if (Array.isArray(value)) {
      if (value.length) out.push(`${group}: ${value.join(", ")}`);
    } else if (typeof value === "object") {
      const entries = Object.entries(value as Record<string, unknown>);
      if (entries.length) {
        out.push(`${group}: ${entries.map(([k, v]) => `${k} ${String(v)}`).join(", ")}`);
      }
    } else {
      out.push(`${group}: ${String(value)}`);
    }
  }
  return out;
}

/**
 * "View details" for one node package, the Node Catalog's answer to
 * ``AgentDetailModal`` and ``DatasetDetailModal``.
 *
 * The Node Catalog was the only one of the three with no detail view at all:
 * its card's "View details" re-selected the card, so when the drawer was
 * already open on that package the click did nothing at all, and below 1100px
 * (where `CatalogBrowseLayout.module.css` hides the drawer column outright)
 * there was no way to read a package's contents on any screen.
 *
 * A modal rather than a route, matching both peers - the browse pages do not
 * navigate. Everything rendered here is already on the `PackagePayload` the
 * listing returns, so this needs no new endpoint. The one thing it adds over
 * the drawer is the COMPLETE node list: the drawer caps it at
 * `TEMPLATE_PREVIEW_LIMIT` and collapses the rest into "…and N more", which is
 * exactly the detail someone opening a details view is looking for.
 */
export const PackageDetailModal: React.FC<PackageDetailModalProps> = ({
  pkg,
  inAllProjects = false,
  isPublished = false,
  onClose,
}) => {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  // `packagesApi.download` streams `GET /api/packages/<dir>/archive`, the same
  // `.curio.zip` the Node Catalog's import accepts - so a package exported from
  // one Curio installs into another. The route serves the account's installed
  // copy, or the committed catalog copy for a row the user has not added
  // (#275) - so every row this page lists can be exported.
  const onExport = async () => {
    if (exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      await packagesApi.download(pkg.dirName);
    } catch (err) {
      setExportError(
        err instanceof Error ? err.message : "Export failed.",
      );
    } finally {
      setExporting(false);
    }
  };

  const deps = dependencyLines(pkg);
  const rows: [string, React.ReactNode][] = [
    ["Identifier", pkg.packageId],
    ["Version", pkg.version],
    ["Category", primaryCategory(pkg)],
    ["Publisher", pkg.publisher || "—"],
    ["License", pkg.license || "—"],
    ["Channel", pkg.channel || "stable"],
    ["Nodes", String(pkg.templates.length)],
    ["In all projects", inAllProjects ? "Yes" : "No"],
    ["In the catalog", isPublished ? "Published" : "Not published"],
  ];

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Package details">
      <CatalogDetailHeader
        kind="package"
        title={pkg.name}
        subtitle={
          <>
            {pkg.publisher || pkg.packageId} · v{pkg.version}
              {pkg.license ? ` · ${pkg.license}` : ""}
          </>
        }
        actions={
          <button
            type="button"
            className={styles.exportButton}
            disabled={exporting}
            onClick={() => void onExport()}
          >
            {exporting ? "Exporting…" : "Export"}
          </button>
        }
      />

      <div className={styles.body}>
        {pkg.description ? <p className={styles.purpose}>{pkg.description}</p> : null}

        {exportError ? <p className={styles.purpose}>{exportError}</p> : null}

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Package info</h3>
          <dl className={styles.infoGrid}>
            {rows.map(([label, value]) => (
              <React.Fragment key={label}>
                <dt className={styles.infoLabel}>{label}</dt>
                <dd className={styles.infoValue}>{value}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>

        {pkg.templates.length > 0 ? (
          <section className={styles.section}>
            {/* The whole list, uncapped - the drawer shows only the first
                twelve, and this is the view you open to see the rest. */}
            <h3 className={styles.sectionLabel}>
              Nodes in this package ({pkg.templates.length})
            </h3>
            <ul className={styles.list}>
              {pkg.templates.map((template) => (
                <li key={template.id}>
                  {template.label || template.templateId}
                  {template.category ? ` (${template.category})` : ""}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {pkg.permissions.length > 0 ? (
          <section className={styles.section}>
            {/* Disclosed before the add, not after: the install dialog states
                these too, and someone reading the details first should not have
                to start an install to find out what the package can reach. */}
            <h3 className={styles.sectionLabel}>Permissions</h3>
            <ul className={styles.list}>
              {pkg.permissions.map((permission) => (
                <li key={permission}>{permission}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {deps.length > 0 ? (
          <section className={styles.section}>
            <h3 className={styles.sectionLabel}>Dependencies</h3>
            <ul className={styles.list}>
              {deps.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </ModalShell>
  );
};

export default PackageDetailModal;
