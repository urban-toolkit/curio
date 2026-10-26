/**
 * A node's widgets as controls that set their values (#662): a label and a
 * WidgetControl each. A pinned node's dashboard tile shows them (NodeEditor),
 * where a viewer changes every kind but the read-only ones (#1117).
 *
 * A value reaches the node when its control settles, VALUE_SETTLE_MS after the
 * last keystroke or slider step, or at once when the control is left, so a
 * slider's drag does not run the node per step.
 */
import React, { useEffect, useRef, useState } from "react";
import styles from "./WidgetTags.module.css";
import { WidgetControl } from "./WidgetControl";
import { effectiveValue, type WidgetDef, type WidgetValue } from "../../../utils/widgets/widgetModel";
import { changeableOnDashboard } from "../../../utils/widgets/dashboardControls";

/** How long a value waits for the next keystroke or slider step before it
 * reaches the node. Leaving the control sends it at once. */
export const VALUE_SETTLE_MS = 300;

type RowProps = {
  widget: WidgetDef;
  /** The widget's new value, once its control settles or is left. */
  onCommit: (name: string, value: WidgetValue) => void;
  /** On a dashboard: a read-only kind stays as it is. */
  dashboard?: boolean;
  /** Every control frozen. */
  disabled?: boolean;
};

/** One widget: its label above its control, and the row's settling value. */
export function WidgetValueRow({ widget, onCommit, dashboard = false, disabled = false }: RowProps) {
  // The value shown follows the control at once; the node hears of it when
  // the control settles.
  const committed = effectiveValue(widget);
  const committedKey = JSON.stringify(committed);
  const committedKeyRef = useRef(committedKey);
  committedKeyRef.current = committedKey;
  const [shown, setShown] = useState<WidgetValue>(committed);
  const pending = useRef<{ value: WidgetValue } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // The last value this row sent, so a value set from outside is told apart.
  const sent = useRef<string | null>(null);
  useEffect(() => {
    // A value set from outside (an agent's) replaces one still settling.
    if (pending.current !== null && committedKey !== sent.current) {
      window.clearTimeout(timer.current);
      pending.current = null;
    }
    if (pending.current === null) setShown(committed);
  }, [committedKey]);

  const onCommitRef = useRef(onCommit);
  onCommitRef.current = onCommit;
  const flush = () => {
    window.clearTimeout(timer.current);
    const change = pending.current;
    pending.current = null;
    if (!change) return;
    const key = JSON.stringify(change.value);
    if (key === committedKeyRef.current) return;
    sent.current = key;
    onCommitRef.current(widget.name, change.value);
  };
  const flushRef = useRef(flush);
  flushRef.current = flush;
  useEffect(() => () => flushRef.current(), []);

  const setValue = (value: WidgetValue) => {
    setShown(value);
    pending.current = { value };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => flushRef.current(), VALUE_SETTLE_MS);
  };

  return (
    <div className={`${styles.row} ${styles.plainRow}`} data-widget-row={widget.name} onBlur={() => flush()}>
      <span className={styles.rowLabel}>{widget.label || widget.name}</span>
      <span className={styles.rowControl}>
        <WidgetControl
          widget={widget}
          value={shown}
          disabled={disabled || (dashboard && !changeableOnDashboard(widget))}
          onChange={setValue}
        />
      </span>
    </div>
  );
}

type ControlsProps = {
  widgets: readonly WidgetDef[];
  onCommit: (name: string, value: WidgetValue) => void;
  dashboard?: boolean;
  disabled?: boolean;
  /** Above an output, at their own height: the output fills the rest. Else
   * they fill their pane, scrolling past it. */
  aboveOutput?: boolean;
};

/** A tile's controls: every widget of its node, in a panel. */
export function WidgetValueControls({ widgets, onCommit, dashboard = false, disabled = false, aboveOutput = false }: ControlsProps) {
  return (
    <div
      className={`nowheel nodrag ${styles.panel}${aboveOutput ? ` ${styles.panelAboveOutput}` : ""}`}
      data-widget-controls="true"
    >
      {widgets.map((widget) => (
        <WidgetValueRow
          key={widget.name}
          widget={widget}
          onCommit={onCommit}
          dashboard={dashboard}
          disabled={disabled}
        />
      ))}
    </div>
  );
}

export default WidgetValueControls;
