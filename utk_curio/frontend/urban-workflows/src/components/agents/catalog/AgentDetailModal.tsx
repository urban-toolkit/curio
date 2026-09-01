import React, { useEffect, useState } from "react";
import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { agentsApi } from "../../../api/agentsApi";
import type { AgentCard } from "../../../api/agentsApi";
import { triggerBlobDownload } from "../../../utils/triggerBlobDownload";
import styles from "./AgentDetailModal.module.css";

export interface AgentDetailModalProps {
  agent: AgentCard;
  onClose: () => void;
}

/**
 * "View details" for one agent, the Agent Catalog's answer to
 * ``DatasetDetailModal``.
 *
 * A modal rather than a route, matching the Data Catalog and the constraint
 * ``catalog/agentDetailEntryPoints.test.ts`` pins: the browse page does not
 * navigate. It is also what makes the control work below 1100px, where
 * ``CatalogBrowseLayout.module.css`` hides the side drawer outright and a
 * selection therefore has nowhere to show.
 *
 * Everything here is already on the ``AgentCard`` the listing returns - there is
 * no per-agent GET on the backend and this needs none.
 */
export const AgentDetailModal: React.FC<AgentDetailModalProps> = ({ agent, onClose }) => {
  // The definition behind the card: its manifest and the prompt texts. The card
  // itself carries none of this - `AgentCard` is a summary - so the details
  // screen described an agent's behaviour without ever showing the prompts that
  // ARE its behaviour.
  const [bundle, setBundle] = useState<{
    manifest: Record<string, unknown>;
    prompts: Record<string, string>;
  } | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBundle(null);
    setBundleError(null);
    agentsApi
      .readDefinition(agent.dirName)
      .then((b) => {
        if (!cancelled) setBundle(b);
      })
      .catch(() => {
        // A built-in that has never been materialized into this account's store
        // has no readable definition. That is not an error worth shouting
        // about - the rest of the screen is still accurate - so the prompts
        // section simply says so.
        if (!cancelled) setBundleError("Prompts are not available for this agent.");
      });
    return () => {
      cancelled = true;
    };
  }, [agent.dirName]);

  const onExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const b = bundle ?? (await agentsApi.readDefinition(agent.dirName));
      // One file, not a manifest plus loose prompt files in two directories.
      // `AgentImportModal` accepts this bundle, so an agent exported from one
      // Curio imports into another in a single pick.
      const blob = new Blob([JSON.stringify(b, null, 2)], { type: "application/json" });
      triggerBlobDownload(blob, `${agent.dirName}.curio-agent.json`);
    } catch {
      setBundleError("Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const rows: [string, React.ReactNode][] = [
    ["Identifier", agent.id],
    ["Version", agent.version],
    ["Category", agent.category],
    ["Publisher", agent.provenance?.publisher ?? "curio"],
    ["Trust", agent.provenance?.trust ?? "built-in"],
    ["Attaches to", agent.hooks.length ? agent.hooks.join(", ") : "—"],
    ["In all projects", agent.imported ? "Yes" : "No"],
    ["In the catalog", agent.published ? "Published" : "Not published"],
  ];

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Agent details">
      <CatalogDetailHeader
        kind="agent"
        title={agent.name}
        subtitle={
          <>
            {agent.provenance?.publisher ?? "curio"} · v{agent.version}
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
        {agent.purpose ? <p className={styles.purpose}>{agent.purpose}</p> : null}


        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Agent info</h3>
          <dl className={styles.infoGrid}>
            {rows.map(([label, value]) => (
              <React.Fragment key={label}>
                <dt className={styles.infoLabel}>{label}</dt>
                <dd className={styles.infoValue}>{value}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>

        {agent.capabilities.length > 0 ? (
          <section className={styles.section}>
            <h3 className={styles.sectionLabel}>Capabilities</h3>
            <ul className={styles.list}>
              {agent.capabilities.map((capability) => (
                <li key={capability}>{capability}</li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>
            Prompts{bundle ? ` (${Object.keys(bundle.prompts).length})` : ""}
          </h3>
          {bundleError ? (
            <p className={styles.purpose}>{bundleError}</p>
          ) : !bundle ? (
            <p className={styles.purpose}>Loading…</p>
          ) : Object.keys(bundle.prompts).length === 0 ? (
            <p className={styles.purpose}>This agent ships no prompt files.</p>
          ) : (
            Object.entries(bundle.prompts).map(([name, text]) => (
              <details key={name} className={styles.promptBlock}>
                {/* Collapsed by default: a prompt runs to hundreds of lines and
                    would otherwise bury every section under it. */}
                <summary className={styles.promptName}>{name}</summary>
                <pre className={styles.promptText}>{text}</pre>
              </details>
            ))
          )}
        </section>

        {agent.requiresAgents.length > 0 ? (
          <section className={styles.section}>
            {/* Disclosed before the click, the same as the drawer next door:
                adding this agent adds these too. */}
            <h3 className={styles.sectionLabel}>Requires</h3>
            <ul className={styles.list}>
              {agent.requiresAgents.map((requirement) => (
                <li key={requirement.id}>
                  {requirement.name}
                  {requirement.visible ? "" : " (unavailable)"}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </ModalShell>
  );
};

export default AgentDetailModal;
