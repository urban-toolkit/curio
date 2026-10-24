/**
 * What an edit by a rule, or of several picked features, does in the Map
 * Editor node (#662): in which column, how, by what (ops of
 * `curio_edit_features`): set a value, or, in a number column, the result of
 * an expression.
 */
import React from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { EditValue, FeatureEdit, PropertyDef } from "../../utils/editFeatures/editFeatures";
import { exprProblem } from "../../utils/editFeatures/editExpr";
import { formValue } from "../../utils/editFeatures/layerModel";
import { SelectInput, TextInput } from "./fields";
import styles from "./EditFeatures.module.css";

export type RuleOp = "set" | "expr";
const RULE_OPS: { op: RuleOp; label: string }[] = [
  { op: "set", label: "Set to" },
  // As the list names the edit: "Compute height as height * 0.5".
  { op: "expr", label: "Compute as" },
];

/** The change being written: its column, how and by what, each with its setter. */
export interface ValueChangeState {
  op: RuleOp;
  setOp: (op: RuleOp) => void;
  column: string;
  setColumn: (column: string) => void;
  value: string;
  setValue: (value: string) => void;
}

/**
 * The change's form (*section*), and *make*, which gives the edit on what
 * *base* picks, or null while the change is unfinished.
 */
export function valueChange(
  defs: PropertyDef[],
  { op: ruleOp, setOp: setRuleOp, column: ruleColumn, setColumn: setRuleColumn, value: ruleValue, setValue: setRuleValue }: ValueChangeState,
) {
  // Any column can be set to a value; a number column also to an expression.
  const columns = defs;
  const column = columns.find((d) => d.name === ruleColumn) ?? columns[0];
  const ops = RULE_OPS.filter(({ op }) => op === "set" || column?.type === "number");
  const op: RuleOp = ops.some((o) => o.op === ruleOp) ? ruleOp : "set";
  const choices = op === "set" && column ? (column.type === "choice" ? column.choices ?? [] : column.type === "boolean" ? ["true", "false"] : null) : null;
  const valueProblem =
    op === "expr"
      ? ruleValue.trim() === ""
        ? "Give an expression."
        : exprProblem(ruleValue)
      : ruleValue.trim() !== "" && column && formValue(column, ruleValue) === undefined
        ? `Give a ${column.type === "number" ? "number" : "value"} for ${column.name}.`
        : null;
  const make = (base: { where: string } | { ids: SelectionId[] }): FeatureEdit | null => {
    if (!column || valueProblem) return null;
    const edit = { op, ...base, column: column.name };
    if (op === "expr") return { ...edit, value: ruleValue.trim() };
    const value = ruleValue.trim() === "" ? null : formValue(column, ruleValue);
    return value === undefined ? null : { ...edit, value: value as EditValue };
  };
  const section = (
    <div className={styles.section}>
      <span className={styles.hint}>Then</span>
      {columns.length === 0 ? <span className={styles.hint}>This layer has no property to change.</span> : null}
      <div className={styles.ruleRow}>
        <span />
        <SelectInput label="Change" testId="interaction-rule-column" value={column?.name ?? ""} onChange={setRuleColumn}>
          {columns.map((d) => (
            <option key={d.name} value={d.name}>
              {d.name}
            </option>
          ))}
        </SelectInput>
        <SelectInput label="How" testId="interaction-rule-op" value={op} disabled={ops.length === 1} onChange={(next) => setRuleOp(next as RuleOp)}>
          {ops.map((o) => (
            <option key={o.op} value={o.op}>
              {o.label}
            </option>
          ))}
        </SelectInput>
        {choices ? (
          <SelectInput label="By" testId="interaction-rule-set-value" value={ruleValue} onChange={setRuleValue}>
            <option value="">Empty</option>
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </SelectInput>
        ) : (
          <TextInput label="By" testId="interaction-rule-set-value" value={ruleValue} placeholder={op === "expr" ? `${column?.name ?? "height"} * 0.8` : "empty"} onChange={setRuleValue} />
        )}
        <span />
      </div>
      {valueProblem ? <span className={styles.problem}>{valueProblem}</span> : null}
    </div>
  );
  return { make, section };
}
