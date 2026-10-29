import React, { useId } from "react";

import { scenarioCount } from "./scenarioFacts";
import styles from "./ScenarioSetGroup.module.css";

export interface ScenarioSetGroupProps {
  /** The set's name; "Not in a set yet" for scenarios of no set. */
  name: string;
  /** How many of its scenarios are listed. */
  count: number;
  /** False for the scenarios of no set, which takes no "Scenario set" label. */
  isSet?: boolean;
  /** Spread on the section: `data-scenario-set`, `data-scenario-group`. */
  data?: Record<`data-${string}`, string>;
  children: React.ReactNode;
}

/**
 * One scenario set in the Scenario Catalog drawer, in both tabs: a panel
 * headed by the set's name and how many scenarios it holds, with its
 * scenarios' cards inside it.
 */
export function ScenarioSetGroup({ name, count, isSet = true, data, children }: ScenarioSetGroupProps) {
  const nameId = useId();
  return (
    <section className={styles.group} aria-labelledby={nameId} {...data}>
      <header className={styles.head}>
        <div className={styles.titles}>
          {isSet ? <span className={styles.eyebrow}>Scenario set</span> : null}
          <h3 id={nameId} className={styles.name}>
            {name}
          </h3>
        </div>
        <span className={styles.count} data-scenario-set-count>
          {scenarioCount(count)}
        </span>
      </header>
      <div className={styles.cards}>{children}</div>
    </section>
  );
}

export default ScenarioSetGroup;
