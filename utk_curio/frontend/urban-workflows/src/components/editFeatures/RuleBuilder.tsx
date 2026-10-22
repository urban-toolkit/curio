/**
 * A rule of the Map Edits node (#662): the conditions it is made of, one
 * `where` the log keeps (`ruleText`), and how many features match it now.
 * Remove and Edit pick by one.
 */
import React from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { PropertyDef } from "../../utils/editFeatures/editFeatures";
import { plural, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** A rule's test: what the column is compared by. */
export const TESTS = ["is", "is not", ">", "<", "is empty", "is not empty"] as const;
export type Test = (typeof TESTS)[number];

export interface Condition {
  column: string;
  test: Test;
  value: string;
}

const columnRef = (column: string) => (/^[A-Za-z_][A-Za-z0-9_]*$/.test(column) ? column : `\`${column}\``);
const literal = (def: PropertyDef | undefined, text: string) => {
  if (def?.type === "number" && text.trim() !== "" && Number.isFinite(Number(text))) return String(Number(text));
  if (def?.type === "boolean") return /^(true|yes)$/i.test(text) ? "true" : "false";
  return JSON.stringify(text);
};

/** The conditions as one `where` the log reads, or null while one is unfinished. */
export function ruleText(conditions: readonly Condition[], defs: readonly PropertyDef[]): string | null {
  const parts: string[] = [];
  for (const c of conditions) {
    if (!c.column) return null;
    const col = columnRef(c.column);
    const def = defs.find((d) => d.name === c.column);
    if (c.test === "is empty") parts.push(`(${col} == null or ${col} == "")`);
    else if (c.test === "is not empty") parts.push(`(${col} != null and ${col} != "")`);
    else {
      if (c.value.trim() === "") return null;
      const op = c.test === "is" ? "==" : c.test === "is not" ? "!=" : c.test;
      parts.push(`${col} ${op} ${literal(def, c.value)}`);
    }
  }
  return parts.length > 0 ? parts.join(" and ") : null;
}

/** A rule being written, and what it picks now. */
export interface RuleProps {
  conditions: Condition[];
  setConditions: (conditions: Condition[]) => void;
  defs: PropertyDef[];
  /** Why the rule cannot be read, or null. */
  problem: string | null;
  /** What the rule picks now, or null while it is unfinished. */
  matches: SelectionId[] | null;
  /** How many features the layer holds, as the log leaves it. */
  total: number;
  nouns: Nouns;
}

/** The conditions a rule is made of, with how many features match them now. */
export default function RuleBuilder({ lead, conditions, setConditions, defs, problem, matches, total, nouns }: RuleProps & { lead: string }) {
  return (
    <div className={styles.section}>
      <span className={styles.kind}>{lead}</span>
      {conditions.map((c, i) => {
        const def = defs.find((d) => d.name === c.column);
        const needsValue = c.test !== "is empty" && c.test !== "is not empty";
        const choices = def?.type === "choice" ? def.choices ?? [] : def?.type === "boolean" ? ["true", "false"] : null;
        const set = (patch: Partial<Condition>) => setConditions(conditions.map((x, j) => (j === i ? { ...x, ...patch } : x)));
        return (
          <div key={i} className={styles.ruleRow} data-testid={`interaction-rule-${i}`}>
            <span className={styles.kind}>{i === 0 ? "" : "and"}</span>
            <select className={`nodrag nopan ${styles.first}`} aria-label="Property" value={c.column} onChange={(e) => set({ column: e.target.value, value: "" })}>
              {defs.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name}
                </option>
              ))}
            </select>
            <select className="nodrag nopan" aria-label="Test" value={c.test} onChange={(e) => set({ test: e.target.value as Test })}>
              {TESTS.filter((t) => def?.type === "number" || (t !== ">" && t !== "<")).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            {!needsValue ? (
              <span />
            ) : choices ? (
              <select className="nodrag nopan" aria-label="Value" data-testid={`interaction-rule-value-${i}`} value={c.value} onChange={(e) => set({ value: e.target.value })}>
                <option value="">Choose…</option>
                {choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : (
              <input className={`nodrag nopan ${styles.input}`} aria-label="Value" data-testid={`interaction-rule-value-${i}`} value={c.value} onChange={(e) => set({ value: e.target.value })} />
            )}
            {i > 0 ? (
              <button type="button" className={`nodrag nopan ${styles.delete}`} aria-label={`Remove condition ${i + 1}`} onClick={() => setConditions(conditions.filter((_, j) => j !== i))}>
                ×
              </button>
            ) : (
              <span />
            )}
          </div>
        );
      })}
      <button type="button" className={`nodrag nopan ${styles.small} ${styles.dashed}`} onClick={() => setConditions([...conditions, { column: defs[0]?.name ?? "", test: "is", value: "" }])}>
        + condition
      </button>
      {problem ? <span className={styles.problem}>{problem}</span> : null}
      <span className={styles.matchCount} data-testid="interaction-matching">
        <b>Matches {plural(matches?.length ?? 0, nouns.one, nouns.many)}</b> <span className={styles.kind}>of {total.toLocaleString()}</span>
      </span>
    </div>
  );
}
