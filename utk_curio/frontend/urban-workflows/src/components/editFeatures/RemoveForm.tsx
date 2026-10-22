/**
 * Remove in the Map Edits node's workbench (#662): the features picked on
 * the map, or those a rule matches, which the rule keeps matching later.
 */
import React from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { FeatureEdit } from "../../utils/editFeatures/editFeatures";
import RuleBuilder, { type RuleProps } from "./RuleBuilder";
import { PickBy, onTheMap, plural, type Nouns, type PickMode } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function RemoveForm({
  back,
  nouns,
  removeBy,
  setRemoveBy,
  picked,
  rule,
  where,
  onRemove,
}: {
  back: React.ReactNode;
  nouns: Nouns;
  removeBy: PickMode;
  setRemoveBy: (by: PickMode) => void;
  /** The features picked. */
  picked: SelectionId[];
  rule: RuleProps;
  /** The rule as the log keeps it, or null while it is unfinished. */
  where: string | null;
  /** Writes the removal. */
  onRemove: (edit: FeatureEdit) => void;
}) {
  const n = removeBy === "rule" ? rule.matches?.length ?? 0 : picked.length;
  return (
    <div className={styles.form}>
      {back}
      <span className={styles.title}>Remove {nouns.many}</span>
      <PickBy current={removeBy} choose={setRemoveBy} testId="interaction-remove-by-rule" />
      {removeBy === "click" ? (
        <span className={styles.lead}>
          {picked.length === 0
            ? `Click ${nouns.many} ${onTheMap} to pick them. Shift-click adds one.`
            : `${plural(picked.length, nouns.one, nouns.many)} picked.`}
        </span>
      ) : (
        <RuleBuilder lead={`Remove ${nouns.many} where`} {...rule} />
      )}
      <span className={styles.formButtons}>
        <button
          type="button"
          data-testid="interaction-remove-picked"
          className={`nodrag nopan ${styles.danger}`}
          disabled={n === 0}
          onClick={() => onRemove(removeBy === "rule" && where ? { op: "remove", where } : { op: "remove", ids: picked })}
        >
          Remove {n > 0 ? plural(n, nouns.one, nouns.many) : nouns.many}
        </button>
      </span>
      <span className={styles.hint}>
        {removeBy === "rule"
          ? `Kept as a rule: ${nouns.many} that match it later are removed too. The ${nouns.many} it matches are outlined, dashed, ${onTheMap}.`
          : "Each removal is an entry in the list of edits below. Switch it off or delete it to bring the features back."}
      </span>
    </div>
  );
}
