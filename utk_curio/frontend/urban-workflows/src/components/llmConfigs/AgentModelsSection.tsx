import React, { useEffect, useRef } from "react";
import modal from "../modal-content.module.css";
import styles from "./LlmConfigs.module.css";
import type { LlmAgentRow, LlmListing } from "../../api/llmConfigsApi";

/** The agents a Solve of the Dataflow Builder always runs, by name. */
const SOLVE_RUNS = "Node Content Builder and Dataset Finder";

/** What "Default" means for this account right now. */
function defaultLabel(listing: LlmListing): string {
  const chosen = listing.configs.find((c) => c.id === listing.default);
  if (chosen) return chosen.label;
  return listing.deployment.model ? listing.deployment.label : "none";
}

function answersLine(row: LlmAgentRow): string {
  if (!row.answers.source) return row.answers.error ?? "Nothing answers it.";
  return `Runs on ${row.answers.label} · ${row.answers.model}`;
}

/**
 * API Settings, Agent configuration: the configuration each agent runs on, saved on
 * change. One row per agent the server lists (the catalog cards, published
 * definitions and the account's imports); internal agents are never listed,
 * since they always run on their caller's configuration.
 */
export const AgentModelsSection: React.FC<{
  listing: LlmListing;
  busy: boolean;
  onChoose: (agentId: string, choice: string | null) => void;
  /** Scroll to, and highlight, this agent's row. */
  focusAgentId?: string | null;
}> = ({ listing, busy, onChoose, focusAgentId = null }) => {
  const focusedRef = useRef<HTMLSelectElement | null>(null);

  useEffect(() => {
    if (!focusAgentId || !focusedRef.current) return;
    focusedRef.current.scrollIntoView?.({ block: "center" });
    focusedRef.current.focus();
  }, [focusAgentId]);

  const agents = listing.agents ?? [];
  if (agents.length === 0) return null;
  const fallback = defaultLabel(listing);

  return (
    <section className={styles.section} data-testid="agent-models-section" aria-labelledby="agent-models-heading">
      <h3 className={styles.heading} id="agent-models-heading">Agent models</h3>
      <p className={styles.intro}>
        Choose the configuration each agent runs on. Default follows your default configuration.
      </p>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Agent</th>
            <th scope="col">Configuration</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((row) => {
            const focused = row.id === focusAgentId;
            const selectId = `agent-model-${row.id}`;
            return (
              <tr key={row.id} className={focused ? styles.focusedRow : undefined} data-agent-id={row.id}>
                <td className={styles.name}>
                  <label htmlFor={selectId}>{row.name}</label>
                  {row.id === "agent.dataflow-builder" ? (
                    <span className={styles.host}>
                      Its Solve also runs {SOLVE_RUNS}, each on its own choice, else this one.
                    </span>
                  ) : null}
                </td>
                <td>
                  <select
                    id={selectId}
                    ref={focused ? focusedRef : undefined}
                    className={modal.select}
                    value={row.choice ?? ""}
                    disabled={busy}
                    onChange={(e) => onChoose(row.id, e.target.value || null)}
                  >
                    <option value="">Default ({fallback})</option>
                    {listing.configs.map((config) => (
                      <option key={config.id} value={config.id}>
                        {config.label} · {config.model}
                      </option>
                    ))}
                    {listing.deployment.model ? (
                      <option value="deployment">
                        {listing.deployment.label} · {listing.deployment.model}
                      </option>
                    ) : null}
                  </select>
                  <span className={row.answers.source ? styles.host : modal.error}>{answersLine(row)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className={styles.note}>
        An agent you attach runs on its choice here, else your default. An agent that another agent calls runs
        on its choice, else on its caller&apos;s. Curio&apos;s internal helpers always run on their caller&apos;s.
      </p>
    </section>
  );
};
