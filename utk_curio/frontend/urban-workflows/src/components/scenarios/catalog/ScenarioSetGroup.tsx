import React, { useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGripVertical, faPen } from "@fortawesome/free-solid-svg-icons";

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
  /** Browse all: dragging several of its scenarios. "Pick scenarios to drag" puts it
   *  in select mode (*active*), where its cards show checkboxes and one
   *  handle drags the *checked* ones. */
  select?: {
    active: boolean;
    checked: number;
    onStart: () => void;
    onDone: () => void;
    onAll: (on: boolean) => void;
    onDragStart: (event: React.DragEvent<HTMLElement>) => void;
    onDragEnd: () => void;
  };
  /** In project: renames the set. *problem* says why a name cannot be used. */
  rename?: { onRename: (name: string) => void; problem: (name: string) => string | null };
  /** Spread on the section: `data-scenario-set`, `data-scenario-group`. */
  data?: Record<`data-${string}`, string>;
  children: React.ReactNode;
}

/**
 * One scenario set in the Scenario Catalog drawer, in both tabs: a panel
 * headed by the set's name, how many scenarios it holds and, in Browse all,
 * the way to its project and "Pick scenarios to drag", for a drag of
 * several; its scenarios' cards follow beneath. In project, the set is
 * renamed in place.
 */
export function ScenarioSetGroup({
  name,
  count,
  isSet = true,
  action,
  select,
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
      {select ? <SelectBar name={name} count={count} {...select} /> : null}
      <div className={styles.cards}>{children}</div>
    </section>
  );
}

/** "Pick scenarios to drag", or, in select mode, the handle that drags the checked
 *  scenarios, Select all or Clear, and Done. */
function SelectBar({
  name,
  count,
  active,
  checked,
  onStart,
  onDone,
  onAll,
  onDragStart,
  onDragEnd,
}: { name: string; count: number } & NonNullable<ScenarioSetGroupProps["select"]>) {
  if (!active) {
    return (
      <div className={styles.selectBar}>
        <button
          type="button"
          className={styles.selectStart}
          onClick={onStart}
          data-tooltip="Pick scenarios of this set to drag onto the canvas"
        >
          Pick scenarios to drag
        </button>
      </div>
    );
  }
  const label = checked === 0 ? "Check scenarios to drag" : `Drag ${checked} scenario${checked === 1 ? "" : "s"}`;
  return (
    <div className={`${styles.selectBar} ${styles.selectBarActive}`} data-scenario-set-selecting>
      <div
        role="button"
        tabIndex={checked === 0 ? -1 : 0}
        aria-disabled={checked === 0 || undefined}
        aria-label={checked === 0 ? label : `${label} of ${name}`}
        className={styles.dragHandle}
        draggable={checked > 0}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        data-scenario-drag-handle
      >
        <FontAwesomeIcon icon={faGripVertical} aria-hidden />
        {label}
      </div>
      <button type="button" className={styles.selectLink} onClick={() => onAll(checked < count)}>
        {checked < count ? "Select all" : "Clear"}
      </button>
      <button type="button" className={styles.selectDone} onClick={onDone}>
        Done
      </button>
    </div>
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
