/**
 * The Parameter node (#662): one widget, shared by every node whose code names
 * it as `[!! @name !!]`. Its tag is offered under Shared in every node's
 * Widgets tab and in the strip above every code or grammar editor.
 *
 * It has no edge: a node that uses it is found by reading its code. A new
 * value marks those nodes stale, and a new name rewrites their references.
 */
import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { useFlowContext } from "../../providers/FlowProvider";
import styles from "../../components/editing/widgets/WidgetTags.module.css";
import { SharedTag } from "../../components/editing/widgets/WidgetTag";
import { WidgetControl } from "../../components/editing/widgets/WidgetControl";
import { WidgetForm } from "../../components/editing/widgets/WidgetForm";
import {
  checkWidgetValue,
  effectiveValue,
  normalizeWidgets,
  type WidgetDef,
  type WidgetValue,
} from "../../utils/widgets/widgetModel";
import { nodesUsingShared, sharedWidgetsOf, withSharedRenamed } from "../../utils/references/sharedParameters";
import { codeEditRevision, subscribeToCodeEdits } from "../../utils/references/codeEdits";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

/** How long a value waits for the next keystroke or slider step before it
 * reaches the dataflow. Leaving the control sends it at once. */
const VALUE_SETTLE_MS = 300;

function labelOf(data: any, fallback: string): string {
  try {
    return resolveNodeDisplayLabel(data) || fallback;
  } catch {
    return fallback;
  }
}

function ParameterBody({ data }: { data: any }) {
  const { nodes, updateDataNode, markNodeStale, markDirty, dashboardOn } = useFlowContext();
  const all: any[] = nodes ?? [];
  const held = normalizeWidgets(data.widgets);
  const widget: WidgetDef | null = held[0] ?? null;
  const others = sharedWidgetsOf(all.filter((n) => n.id !== data.nodeId));
  const [editing, setEditing] = useState(false);

  // Code is mirrored into node data without a state change, so the list of
  // users is read again on every code edit.
  useSyncExternalStore(subscribeToCodeEdits, codeEditRevision);
  const users = widget ? nodesUsingShared(all, widget.name) : [];

  // The value shown follows the control at once; the dataflow hears of it when
  // the control settles, so a slider drag does not re-render every node per step.
  const committed = widget ? effectiveValue(widget) : null;
  const committedKey = JSON.stringify(committed);
  const [shown, setShown] = useState<WidgetValue>(committed);
  const pending = useRef<{ value: WidgetValue } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (pending.current === null) setShown(committed);
  }, [committedKey]);

  const write = (next: WidgetDef[]) => {
    updateDataNode(data.nodeId, { ...data, widgets: next });
    markDirty?.();
  };

  const markUsersStale = (name: string) => {
    for (const node of nodesUsingShared(all, name)) markNodeStale?.(node.id);
  };

  const flush = () => {
    window.clearTimeout(timer.current);
    const change = pending.current;
    pending.current = null;
    if (!change || !widget) return;
    if (JSON.stringify(change.value) === committedKey) return;
    write([{ ...widget, value: change.value }, ...held.slice(1)]);
    markUsersStale(widget.name);
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

  const add = (def: WidgetDef) => {
    write([def]);
    setEditing(false);
  };

  const save = (previous: WidgetDef, next: WidgetDef) => {
    flush();
    // The set value survives an edit that keeps it valid.
    const keep =
      previous.value !== undefined &&
      previous.type === next.type &&
      checkWidgetValue(next, previous.value) === null;
    const edited: WidgetDef = keep ? { ...next, value: previous.value } : next;
    if (edited.name !== previous.name) {
      // The references follow the new name, in every node that names the old one.
      const renamed = withSharedRenamed(all, previous.name, edited.name);
      renamed.forEach((node, index) => {
        if (node === all[index]) return;
        updateDataNode(node.id, node.data);
        markNodeStale?.(node.id);
      });
    } else {
      markUsersStale(edited.name);
    }
    write([edited, ...held.slice(1)]);
    setEditing(false);
  };

  if (!widget || editing) {
    return (
      <div className={`nowheel nodrag ${styles.panel}`} data-parameter-panel="true">
        {!widget ? (
          <p className={styles.empty}>
            Give this parameter a name, a type and a default. Any node&apos;s code can then use it through its
            tag under Shared.
          </p>
        ) : null}
        <WidgetForm
          parameter
          initial={widget ?? undefined}
          others={others}
          onSave={(def) => (widget ? save(widget, def) : add(def))}
          onCancel={() => setEditing(false)}
        />
      </div>
    );
  }

  return (
    <div
      className={`nowheel nodrag ${styles.panel}`}
      data-parameter-panel="true"
      onBlur={() => flush()}
    >
      <div className={styles.row} data-widget-row={widget.name}>
        <span className={styles.rowLabel}>{widget.label || widget.name}</span>
        <SharedTag name={widget.name} disabled={dashboardOn} />
        <span className={styles.rowControl}>
          <WidgetControl widget={widget} value={shown} disabled={dashboardOn} onChange={setValue} />
        </span>
        {!dashboardOn ? (
          <span className={styles.rowActions}>
            <button
              type="button"
              className={styles.button}
              aria-label={`Edit parameter ${widget.name}`}
              onClick={() => {
                flush();
                setEditing(true);
              }}
            >
              Edit
            </button>
          </span>
        ) : null}
      </div>
      {held.length > 1 ? (
        <p className={styles.problem}>
          This node holds {held.length} widgets, and a Parameter node holds one. Each is shared; move the others to
          Parameter nodes of their own.
        </p>
      ) : null}
      <div className={styles.shared} data-parameter-users="true">
        <p className={styles.sharedHeading}>Used by</p>
        {users.length === 0 ? (
          <p className={styles.empty}>No node uses it yet. Drag its tag into a node&apos;s code.</p>
        ) : (
          <ul className={styles.users}>
            {users.map((node) => (
              <li key={node.id} data-parameter-user={node.id}>
                {labelOf(node.data, node.id)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export const useParameterBehavior: NodeBehaviorHook = (data) => {
  return {
    contentComponent: <ParameterBody data={data} />,
    // Nothing to run: the nodes that use it run with its value.
    disablePlay: true,
  };
};
