import React, { useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPen } from "@fortawesome/free-solid-svg-icons";

import { scenarioCount } from "./scenarioFacts";
import styles from "./ScenarioSetGroup.module.css";

export interface ScenarioSetGroupProps {
  /** The set's name; "Not in a set yet" for scenarios of no set. */
  name: string;
  /** How many of its scenarios are listed. */
  count: number;
  /** False for the scenarios of no set, which takes no "Scenario set" label. */
  isSet?: boolean;
  /** Beside the count: Browse all's Open source project. */
  action?: React.ReactNode;
  /** Browse all: its cards are selected by a click, several with Ctrl or
   *  Cmd, so they are a list of options to pick from. */
  selectable?: boolean;
  /** In project: renames the set. *problem* says why a name cannot be used. */
  rename?: { onRename: (name: string) => void; problem: (name: string) => string | null };
  /** Spread on the section: `data-scenario-set`, `data-scenario-group`. */
  data?: Record<`data-${string}`, string>;
  children: React.ReactNode;
}

/**
 * One scenario set in the Scenario Catalog drawer, in both tabs: a panel
 * headed by the set's name, how many scenarios it holds and, in Browse all,
 * the way to its project; its scenarios' cards follow beneath, picked by a
 * click (several with Ctrl or Cmd) for a drag. In project, the set is
 * renamed in place.
 */
export function ScenarioSetGroup({
  name,
  count,
  isSet = true,
  action,
  selectable = false,
  rename,
  data,
  children,
}: ScenarioSetGroupProps) {
  const nameId = useId();

  return (
    <section className={styles.group} aria-labelledby={nameId} {...data}>
      <header className={styles.head}>
        <div className={styles.titles}>
          {isSet ? <span className={styles.eyebrow}>Scenario set</span> : null}
          {rename ? (
            <SetName id={nameId} name={name} {...rename} />
          ) : (
            <h3 id={nameId} className={styles.name}>
              {name}
            </h3>
          )}
        </div>
        <span className={styles.count} data-scenario-set-count>
          {scenarioCount(count)}
        </span>
        {action}
      </header>
      <div
        className={styles.cards}
        role={selectable ? "listbox" : undefined}
        aria-multiselectable={selectable || undefined}
        aria-labelledby={selectable ? nameId : undefined}
      >
        {children}
      </div>
    </section>
  );
}

/** The set's name, with a pencil that edits it: Enter or leaving the field
 *  keeps a usable name, Escape goes back. */
function SetName({
  id,
  name,
  onRename,
  problem,
}: {
  id: string;
  name: string;
  onRename: (name: string) => void;
  problem: (name: string) => string | null;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  if (draft === null) {
    return (
      <div className={styles.nameRow}>
        <h3 id={id} className={styles.name}>
          {name}
        </h3>
        <button
          type="button"
          className={styles.rename}
          aria-label={`Rename ${name}`}
          data-tooltip="Rename the scenario set"
          onClick={() => setDraft(name)}
        >
          <FontAwesomeIcon icon={faPen} aria-hidden />
        </button>
      </div>
    );
  }
  const trouble = draft.trim() === name ? null : problem(draft);
  const commit = () => {
    if (!trouble && draft.trim() && draft.trim() !== name) onRename(draft.trim());
    setDraft(null);
  };
  return (
    <div className={styles.nameRow}>
      <h3 id={id} className={styles.visuallyHidden}>
        {name}
      </h3>
      <input
        className={styles.nameInput}
        aria-label="Scenario set name"
        aria-invalid={trouble ? true : undefined}
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            setDraft(null);
          } else if (e.key === "Enter" && !trouble) {
            commit();
          }
        }}
      />
      {trouble ? (
        <span className={styles.problem} role="alert">
          {trouble}
        </span>
      ) : null}
    </div>
  );
}

export default ScenarioSetGroup;
