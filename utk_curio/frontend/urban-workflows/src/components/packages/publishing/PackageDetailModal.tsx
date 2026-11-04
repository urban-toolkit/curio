import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { DetailLink } from "../../datasets/catalog/DetailLink";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import { isModelPackage, packagesApi, primaryCategory } from "../../../services/packages";
import type { PackagePayload } from "../../../services/packages";
import { modelInfoRows } from "../../models/catalog/modelFacts";
import styles from "../../agents/catalog/AgentDetailModal.module.css";
import browseStyles from "../../../pages/catalog/CatalogBrowseLayout.module.css";

export interface PackageDetailModalProps {
  pkg: PackagePayload;
  /** In the user's "all projects" defaults list. Left out, the modal reads
   *  the list itself rather than claiming "No". */
  inAllProjects?: boolean;
  /** Listed in the shared catalog. */
  isPublished?: boolean;
  /** The dataflow behind the modal has changes not yet saved, so a link that
   *  leaves it asks first. Set only on the canvas. */
  unsavedChanges?: boolean;
  /** A dataflow bound to its doc: a link that leaves it waits for the server
   *  to have its last change, and asks only when it cannot. Set only on the
   *  canvas. */
  whenChangesKept?: () => Promise<boolean>;
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

function samePath(a: string, b: string): boolean {
  const decode = (p: string) => {
    try {
      return decodeURIComponent(p);
    } catch {
      return p;
    }
  };
  return decode(a) === decode(b);
}

/**
 * Where a model downloaded from the Discovery Catalog came from, linked. A
 * link out opens a page, so the modal closes on the way, and leaving a
 * dataflow with unsaved changes asks first, as the dataset details do. Its
 * own component, so only a modal that shows it needs a router.
 */
function DownloadedFrom({
  source,
  unsavedChanges,
  whenChangesKept,
  onClose,
}: {
  source: { sourceId: string; sourceName?: string; resourceId?: string };
  unsavedChanges: boolean;
  whenChangesKept?: () => Promise<boolean>;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { leave, dialog: leaveDialog } = useLeaveGuard(unsavedChanges, LEAVE_DATAFLOW, {
    layer: "overlay",
    settle: whenChangesKept,
  });
  const followLink = (to: string) => {
    if (samePath(to, pathname)) {
      onClose();
      return;
    }
    leave(() => {
      onClose();
      navigate(to);
    });
  };
  const rows: [string, React.ReactNode][] = [
    [
      "Source",
      <DetailLink to={`/catalog/discovery/${encodeURIComponent(source.sourceId)}`} onFollow={followLink}>
        {source.sourceName || source.sourceId}
      </DetailLink>,
    ],
  ];
  if (source.resourceId) rows.push(["Resource", source.resourceId]);
  return (
    <>
      <InfoSection label="Downloaded from" rows={rows} />
      {leaveDialog}
    </>
  );
}

/** A rows section of the modal: a label over a grid of label/value pairs. */
function InfoSection({ label, rows }: { label: string; rows: [string, React.ReactNode][] }) {
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionLabel}>{label}</h3>
      <dl className={styles.infoGrid}>
        {rows.map(([rowLabel, value]) => (
          <React.Fragment key={rowLabel}>
            <dt className={styles.infoLabel}>{rowLabel}</dt>
            <dd className={styles.infoValue}>{value}</dd>
          </React.Fragment>
        ))}
      </dl>
    </section>
  );
}

/**
 * "View details" for one package, the Node Catalog's answer to
 * ``AgentDetailModal`` and ``DatasetDetailModal``, and the Model Catalog's
 * too: a model package (kind `model`) shows its model's fields, its code's
 * and its weights' licenses (with the weights' license text), the node a drop
 * creates, whether its weights download on first use, and where a downloaded
 * model came from.
 *
 * The Node Catalog was the only one of the three with no detail view at all:
 * its card's "View details" re-selected the card, so when the drawer was
 * already open on that package the click did nothing at all, and below 1100px
 * (where `CatalogBrowseLayout.module.css` hides the drawer column outright)
 * there was no way to read a package's contents on any screen.
 *
 * A modal rather than a route, matching both peers - the browse pages do not
 * navigate. Everything rendered here is already on the `PackagePayload` the
 * listing returns, but the weights' license text, read on request. The one
 * thing it adds over the drawer is the COMPLETE node list: the drawer caps it
 * at `TEMPLATE_PREVIEW_LIMIT` and collapses the rest into "…and N more", which
 * is exactly the detail someone opening a details view is looking for. Every
 * package lists the modules it ships, which its nodes import.
 */
export const PackageDetailModal: React.FC<PackageDetailModalProps> = ({
  pkg,
  inAllProjects,
  isPublished,
  unsavedChanges = false,
  whenChangesKept,
  onClose,
}) => {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [license, setLicense] = useState<string | null>(null);
  const [licenseLoading, setLicenseLoading] = useState(false);
  const [licenseError, setLicenseError] = useState<string | null>(null);
  // The Node Catalog page holds the defaults list and passes it. The canvas
  // drawer keeps none (#204), so from there the modal asks, and says nothing
  // until it knows: it used to fall back to "No" and "Not published" for every
  // package opened from the canvas.
  const [fetchedInAllProjects, setFetchedInAllProjects] = useState<boolean | undefined>();
  useEffect(() => {
    if (inAllProjects !== undefined) return;
    let cancelled = false;
    void packagesApi
      .getDefaults()
      .then((resp) => {
        if (!cancelled) setFetchedInAllProjects(resp.packages.includes(pkg.dirName));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [inAllProjects, pkg.dirName]);
  const inAll = inAllProjects ?? fetchedInAllProjects;

  // `packagesApi.download` streams `GET /api/packages/<dir>/archive`, the same
  // `.curio.zip` the Node Catalog's import accepts - so a package exported from
  // one Curio installs into another. The route serves the account's installed
  // copy, or the committed catalog copy for a row the user has not added
  // (#275) - so every row this page lists can be exported. A model package's
  // archive carries its weights.
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

  const showLicense = async () => {
    if (licenseLoading) return;
    setLicenseLoading(true);
    setLicenseError(null);
    try {
      setLicense(await packagesApi.weightsLicense(pkg.dirName));
    } catch (err) {
      setLicenseError(err instanceof Error && err.message ? err.message : "Could not load the license.");
    } finally {
      setLicenseLoading(false);
    }
  };

  const model = isModelPackage(pkg) ? pkg : null;
  const deps = dependencyLines(pkg);
  const modules = pkg.modules ?? [];
  // A model package's code license sits beside its weights' license, in the
  // Model section.
  const rows: [string, React.ReactNode][] = [
    ["Identifier", pkg.packageId],
    ["Version", pkg.version],
    ["Category", primaryCategory(pkg)],
    ["Publisher", pkg.publisher || "—"],
    ...(model ? [] : [["License", pkg.license || "—"] as [string, React.ReactNode]]),
    ["Channel", pkg.channel || "stable"],
    ["Nodes", String(pkg.templates.length)],
  ];
  if (inAll !== undefined) {
    rows.push(["In all projects", inAll ? "Yes" : "No"]);
  }
  if (isPublished !== undefined) {
    rows.push(["In the catalog", isPublished ? "Published" : "Not published"]);
  }

  const weightsLicense = model ? (
    <>
      {model.model.license || "Unknown"}
      {model.model.licenseFile && license == null ? (
        <>
          {" "}
          <button
            type="button"
            className={styles.inlineLink}
            disabled={licenseLoading}
            onClick={() => void showLicense()}
          >
            {licenseLoading ? "Loading…" : "View license"}
          </button>
        </>
      ) : null}
    </>
  ) : null;
  const source = model?.model.discoverySource as
    | { sourceId?: string; sourceName?: string; resourceId?: string }
    | undefined;

  return (
    <ModalShell
      onClose={onClose}
      size="xlarge"
      layer="overlay"
      label={model ? "Model details" : "Package details"}
    >
      <CatalogDetailHeader
        kind={model ? "model" : "package"}
        title={pkg.name}
        subtitle={
          <>
            {pkg.publisher || pkg.packageId} · v{pkg.version}
              {pkg.license && !model ? ` · ${pkg.license}` : ""}
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

      <div className={styles.body} data-pkg-dir={pkg.dirName}>
        {pkg.description ? <p className={styles.purpose}>{pkg.description}</p> : null}

        {exportError ? <p className={styles.purpose}>{exportError}</p> : null}

        {model ? (
          <>
            <InfoSection
              label="Model"
              rows={modelInfoRows(model, weightsLicense).map(({ label, value }) => [label, value])}
            />
            {licenseError ? (
              <p className={styles.purpose} role="alert">
                {licenseError}
              </p>
            ) : null}
            {license != null ? (
              <pre className={styles.promptText} data-curio-model-license="true">
                {license}
              </pre>
            ) : null}
            {model.model.labels.length > 0 ? (
              <section className={styles.section}>
                <h3 className={styles.sectionLabel}>Labels ({model.model.labels.length})</h3>
                {/* Plain chips, the drawer's tag treatment: a label is a name,
                    and no chip in the catalogs is tinted (#193). */}
                <div className={browseStyles.drawerTagsRow} data-curio-model-labels="true">
                  {model.model.labels.map((label) => (
                    <span key={label} className={browseStyles.drawerTag}>
                      {label}
                    </span>
                  ))}
                </div>
              </section>
            ) : null}
            {source?.sourceId ? (
              <DownloadedFrom
                source={{ ...source, sourceId: source.sourceId }}
                unsavedChanges={unsavedChanges}
                whenChangesKept={whenChangesKept}
                onClose={onClose}
              />
            ) : null}
          </>
        ) : null}

        <InfoSection label="Package info" rows={rows} />

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

        {modules.length > 0 ? (
          <section className={styles.section}>
            {/* What the package's nodes import, and what a node of another
                package may import once this one is a dependency. */}
            <h3 className={styles.sectionLabel}>Modules ({modules.length})</h3>
            <ul className={styles.list}>
              {modules.map((name) => (
                <li key={name}>
                  <code>{name}</code>
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
