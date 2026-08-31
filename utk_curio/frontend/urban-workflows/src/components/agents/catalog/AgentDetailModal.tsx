import React from "react";
import ModalShell from "../../ModalShell";
import { CatalogKindIcon } from "../../catalog/CatalogKindVisuals";
import type { AgentCard } from "../../../api/agentsApi";
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
  const rows: [string, React.ReactNode][] = [
    ["Identifier", agent.id],
    ["Version", agent.version],
    ["Category", agent.category],
    ["Publisher", agent.provenance?.publisher ?? "curio"],
    ["Trust", agent.provenance?.trust ?? "built-in"],
    ["Attaches to", agent.hooks.length ? agent.hooks.join(", ") : "—"],
    ["In your account", agent.imported ? "Yes" : "No"],
    ["In the catalog", agent.published ? "Published" : "Not published"],
  ];

  return (
    <ModalShell onClose={onClose} size="large" layer="overlay" label="Agent details">
      <div className={styles.header}>
        <CatalogKindIcon kind="agent" size="lg" title="Agent" />
        <div>
          <h2 className={styles.title}>{agent.name}</h2>
          <p className={styles.subtitle}>
            {agent.provenance?.publisher ?? "curio"} · v{agent.version}
          </p>
        </div>
      </div>

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
