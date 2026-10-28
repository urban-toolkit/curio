import React from "react";

import { useScenarioSet, type ScenarioSetNodeEntry } from "../../../services/scenarioCatalog";
import styles from "./ScenarioSetSummary.module.css";

/**
 * A scenario set's shared context and outcomes, as a table: a row per node,
 * a column per scenario of the set, a filled circle where that scenario uses
 * the node. Fetched when shown.
 */
export function ScenarioSetSummary({ projectId, setId }: { projectId: string; setId: string }) {
  const { set, error } = useScenarioSet(projectId, setId);
  if (error) {
    return (
      <p className={styles.note} role="alert">
        {error}
      </p>
    );
  }
  if (!set) return <p className={styles.note}>Loading…</p>;
  const table = (title: string, entries: ScenarioSetNodeEntry[]) => (
    <section className={styles.part} aria-label={title}>
      <h4 className={styles.title}>{title}</h4>
      {entries.length === 0 ? (
        <p className={styles.note}>None</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col" className={styles.nodeHead}>
                Node
              </th>
              {set.scenarios.map((s) => (
                <th key={s.id} scope="col" className={styles.scenarioHead} aria-label={s.name} data-tooltip={s.name}>
                  <span className={styles.dot} style={{ background: s.color, borderColor: s.color }} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id} data-set-node={entry.id}>
                <th scope="row" className={styles.node}>
                  {entry.label ?? entry.id}
                </th>
                {set.scenarios.map((s) => {
                  const uses = entry.scenarios.includes(s.id);
                  return (
                    <td key={s.id} className={styles.cell} data-member={uses ? "true" : "false"}>
                      <span
                        className={styles.dot}
                        role="img"
                        aria-label={`${s.name} ${uses ? "uses it" : "does not use it"}`}
                        style={uses ? { background: s.color, borderColor: s.color } : { borderColor: s.color }}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
  return (
    <div className={styles.summary} data-scenario-set-summary={setId}>
      {table("Shared context", set.context)}
      {table("Outcomes", set.outcomes)}
    </div>
  );
}

export default ScenarioSetSummary;
