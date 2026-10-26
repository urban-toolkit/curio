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
import { WidgetValueRow } from "../../components/editing/widgets/WidgetValueControls";
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
import { registerNodeSettingWriter } from "../../utils/nodeSettingsWriters";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

function labelOf(data: any, fallback: string): string {
  try {
    return resolveNodeDisplayLabel(data) || fallback;
  } catch {
    return fallback;
  }
}

function ParameterBody({ data }: { data: any }) {
  const { nodes, updateDataNode, markNodeStale, markDirty, requestAutoRun, dashboardOn } = useFlowContext();
  const all: any[] = nodes ?? [];
  const held = normalizeWidgets(data.widgets);
  const widget: WidgetDef | null = held[0] ?? null;
  const others = sharedWidgetsOf(all.filter((n) => n.id !== data.nodeId));
  const [editing, setEditing] = useState(false);

  // Code is mirrored into node data without a state change, so the list of
  // users is read again on every code edit.
  useSyncExternalStore(subscribeToCodeEdits, codeEditRevision);
  const users = widget ? nodesUsingShared(all, widget.name) : [];

  // The control's row holds a value until it settles (WidgetValueRow), so a
  // slider drag does not re-render every node per step.
  const committedKey = JSON.stringify(widget ? effectiveValue(widget) : null);

  const write = (next: WidgetDef[]) => {
    updateDataNode(data.nodeId, { ...data, widgets: next });
    // A value tried on a dashboard never changes the dataflow (#1117).
    if (!dashboardOn) markDirty?.();
  };

  const markUsersStale = (name: string) => {
    for (const node of nodesUsingShared(all, name)) markNodeStale?.(node.id);
  };

  /** The widget's new value reaches the dataflow: the nodes that use it are
   * out of date, and with auto-run on they run, as they do on a dashboard,
   * where the run is a viewer's (#1117). */
  const commit = (value: WidgetValue) => {
    if (!widget) return;
    if (JSON.stringify(value) === committedKey) return;
    write([{ ...widget, value }, ...held.slice(1)]);
    markUsersStale(widget.name);
    // #845: with auto-run on, the nodes that use it run on their own.
    requestAutoRun?.(nodesUsingShared(all, widget.name).map((node) => node.id));
  };

  // An agent's applied change gives the widget a new value as its control
  // does (utils/nodeSettingsWriters), in place of one still settling, which
  // its row then drops.
  const takeValueRef = useRef<(values: Record<string, unknown>) => void>(() => undefined);
  takeValueRef.current = (values) => {
    if (!widget || !Object.prototype.hasOwnProperty.call(values, widget.name)) return;
    commit(values[widget.name] as WidgetValue);
  };
  useEffect(
    () => registerNodeSettingWriter(data.nodeId, "widgets", (values) => takeValueRef.current(values)),
    [data.nodeId],
  );

  const add = (def: WidgetDef) => {
    write([def]);
    setEditing(false);
  };

  // The row is gone while the form shows, and sent what it held as it went.
  const save = (previous: WidgetDef, next: WidgetDef) => {
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
    <div className={`nowheel nodrag ${styles.panel}`} data-parameter-panel="true">
      {/* A viewer changes a pinned control, except a read-only kind (#1117). */}
      <WidgetValueRow
        widget={widget}
        dashboard={dashboardOn}
        onCommit={(_name, value) => commit(value)}
        tag={<SharedTag name={widget.name} disabled={dashboardOn} />}
        actions={(flush) =>
          !dashboardOn ? (
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
          ) : null
        }
      />
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
