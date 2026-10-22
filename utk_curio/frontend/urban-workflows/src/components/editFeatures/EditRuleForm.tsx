/**
 * Edit by a rule in the Map Edits node's workbench (#662): the features a
 * rule matches given a value, or, in a number column, the result of an
 * expression. The rule is kept, so features that match it later change too.
 */
import React from "react";
import type { FeatureEdit, PropertyDef } from "../../utils/editFeatures/editFeatures";
import RuleBuilder, { type RuleProps } from "./RuleBuilder";
import { valueChange, type ValueChangeState } from "./ValueChange";
import { onTheMap, plural, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function EditRuleForm({
  back,
  nouns,
  pickBy,
  rule,
  where,
  defs,
  change: changeState,
  onApply,
}: {
  back: React.ReactNode;
  nouns: Nouns;
  /** Picking by a click or by a rule. */
  pickBy: React.ReactNode;
  rule: RuleProps;
  /** The rule as the log keeps it, or null while it is unfinished. */
  where: string | null;
  defs: PropertyDef[];
  change: ValueChangeState;
  /** Writes the edit on what the rule matches. */
  onApply: (edit: FeatureEdit) => void;
}) {
  const change = valueChange(defs, changeState);
  const ruleEdit = (): FeatureEdit | null => (where && !rule.problem ? change.make({ where }) : null);
  const ready = ruleEdit();
  const n = rule.matches?.length ?? 0;
  return (
    <div className={styles.form} data-testid="interaction-edit-rule">
      {back}
      <span className={styles.title}>Edit {nouns.many}</span>
      {pickBy}
      <RuleBuilder lead={`Change ${nouns.many} where`} {...rule} />
      {change.section}
      <span className={styles.formButtons}>
        <button
          type="button"
          data-testid="interaction-rule-apply"
          className={`nodrag nopan ${styles.big} ${styles.primary}`}
          disabled={!ready || n === 0}
          onClick={() => {
            if (!ready) return;
            onApply(ready);
          }}
        >
          Apply to {n > 0 ? plural(n, nouns.one, nouns.many) : nouns.many}
        </button>
      </span>
      <span className={styles.hint}>
        Kept as a rule: {nouns.many} that match it later are changed too. The match is outlined in red {onTheMap}.
      </span>
    </div>
  );
}
