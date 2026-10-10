/**
 * The Interaction node's body (#662; it was Edit Features): the layer to edit
 * and the column that identifies its features, the layer drawn on a map as
 * the edit log leaves it (`applyEdits`), and the ways to add to the log:
 *
 * - double-click features to pick them; `Delete` removes them, `Esc` clears
 *   the pick, `↑`/`↓` raise or lower the nudged column, `Cmd/Ctrl+Z` and
 *   `Shift+Cmd/Ctrl+Z` undo and redo (while the node has the focus);
 * - Remove, Restore, Scale and Set value on the pick, and a table of the
 *   picked features whose cells write a value;
 * - a condition (`height > 100`) and what to do to every feature it holds for.
 *
 * Each entry of the log can be switched off or deleted. A change of the log
 * makes the node and every node after it stale; Update results runs them.
 *
 * A layer with no column that identifies its features (no `osm_id` or
 * `building_id`, and no column whose values differ in every feature) is
 * refused: a feature's place in a layer is not an id.
 */
import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { useFlowContext } from "../../providers/FlowProvider";
import { readAutkInput, autkSourcesFrom } from "../../utils/autkInput";
import type { SelectionId } from "../../utils/references/selectionTags";
import { descendantsOf } from "../../utils/graphDescendants";
import { applyEdits } from "../../utils/editFeatures/applyEdits";
import { evaluate, exprProblem, parseExpr, truthy } from "../../utils/editFeatures/editExpr";
import {
  addPicked,
  defaultKey,
  describeEdit,
  featureColumns,
  keyColumns,
  keyRefusal,
  normalizeEditFeatures,
  pickedIds,
  typedValue,
  withEdit,
  withEditEnabled,
  withNudge,
  withoutEdit,
  type EditFeaturesSettings,
  type EditOp,
  type FeatureEdit,
} from "../../utils/editFeatures/editFeatures";
import styles from "./EditFeatures.module.css";

/** Why the Layer and Id menus are held while the log has edits: the edits
 * name features of that layer by that column. */
const HELD = "The edits name features of this layer by this column: delete them to pick another.";

/** The map's code loads with the first layer to draw. */
const EditFeaturesMap = React.lazy(() => import("./EditFeaturesMap"));

/** How long the map waits after an edit before it draws the layer again. */
const PREVIEW_DELAY_MS = 300;

/** One layer of the input, by the table name its map reads it as. */
export interface InputLayer {
  /** The table name: the layer's own name, or `input_0` for an unnamed one. */
  table: string;
  /** The layer's own name, when the input names it. */
  name: string | null;
  layerType?: string;
  fc: { features?: any[] };
}

/** The layers of *input*, read as the Autark map reads them. */
function useInputLayers(input: unknown): InputLayer[] | null {
  const [layers, setLayers] = useState<InputLayer[] | null>(null);
  useEffect(() => {
    let current = true;
    if (input == null || input === "") {
      setLayers([]);
      return;
    }
    setLayers(null);
    readAutkInput(input)
      .then((read) => {
        const named = new Map(read.frames.map((frame) => [frame.name, frame]));
        const { sources } = autkSourcesFrom(read, {}, { alias: false });
        return sources.map((source) => ({
          table: source.outputTableName,
          name: named.has(source.outputTableName) ? source.outputTableName : null,
          layerType: source.layerType,
          fc: source.geojsonObject as { features?: any[] },
        }));
      })
      .catch(() => [] as InputLayer[])
      .then((found) => {
        if (current) setLayers(found);
      });
    return () => {
      current = false;
    };
  }, [input]);
  return layers;
}

/** The layer to edit: the one the settings name, else the first that has an id column. */
function chosenLayer(layers: InputLayer[], settings: EditFeaturesSettings | undefined): InputLayer | undefined {
  if (settings?.layer) {
    const named = layers.find((layer) => layer.name === settings.layer);
    if (named) return named;
  }
  return layers.find((layer) => keyColumns(layer.fc).length > 0) ?? layers[0];
}

/** The document the map draws: every layer, the one to edit on top and pickable. */
export function editMapDocument(layers: readonly InputLayer[], table: string): string {
  const refs: Record<string, unknown>[] = layers.filter((layer) => layer.table !== table).map((layer) => ({ dataRef: layer.table }));
  refs.push({ dataRef: table, isPick: true });
  return JSON.stringify({ map: { layerRefs: refs } }, null, 2);
}

function Select({
  label,
  value,
  options,
  disabled,
  onChange,
  testId,
  title,
}: {
  label: string;
  value: string | undefined;
  options: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
  testId: string;
  title?: string;
}) {
  return (
    <label className={styles.field}>
      {label}
      <select
        className="nodrag nopan"
        aria-label={label}
        data-testid={testId}
        title={title}
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * The input as the map draws it: the edited layer as the log leaves it, the
 * others as they came, each under the table name the map's document reads.
 */
function previewInput(layers: readonly InputLayer[], edited: InputLayer, fc: { features?: any[] }): unknown {
  if (layers.length === 1) {
    return { dataType: "geodataframe", data: fc, ...(edited.name ? { layerName: edited.name } : {}), ...(edited.layerType ? { layerType: edited.layerType } : {}) };
  }
  return {
    dataType: "outputs",
    data: layers.map((layer) => ({
      dataType: "geodataframe",
      data: layer === edited ? fc : layer.fc,
      layerName: layer.table,
      ...(layer.layerType ? { layerType: layer.layerType } : {}),
    })),
  };
}

/** The columns holding numbers in *fc*. */
function numberColumns(fc: { features?: any[] } | undefined, columns: readonly string[]): string[] {
  const features = (fc?.features ?? []).slice(0, 50);
  return columns.filter((c) => features.some((f) => typeof f?.properties?.[c] === "number"));
}

/** A step that suits *column*: a floor for a height, one for a count. */
const defaultStep = (column: string | undefined) => (column && /height/i.test(column) ? 3 : 1);

const WHERE_OPS: EditOp[] = ["remove", "scale", "offset", "set", "expr", "restore"];

export function EditFeaturesBody({
  nodeId,
  runError = null,
  onChange,
}: {
  nodeId: string;
  /** Why the node's last run failed. */
  runError?: string | null;
  /** Writes new settings, and the code they make, onto the node. */
  onChange: (next: EditFeaturesSettings | undefined) => void;
}) {
  const flow = useFlowContext() as any;
  const live = (flow?.nodes ?? []).find((n: any) => n.id === nodeId)?.data;
  const input = live?.input;
  const settings = normalizeEditFeatures(live?.editFeatures);
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";
  const layers = useInputLayers(input);
  const layer = layers ? chosenLayer(layers, settings) : undefined;
  const keys = useMemo(() => (layer ? keyColumns(layer.fc) : []), [layer]);
  const key = settings?.key && keys.includes(settings.key) ? settings.key : defaultKey(keys) ?? keys[0];
  const columns = useMemo(() => (layer ? featureColumns(layer.fc).filter((c) => c !== "interacted") : []), [layer]);
  const numbers = useMemo(() => numberColumns(layer?.fc, columns).filter((c) => c !== key), [layer, columns, key]);
  const [picked, setPicked] = useState<SelectionId[]>([]);
  const [column, setColumn] = useState<string | undefined>(undefined);
  const [valueText, setValueText] = useState("");
  const [valueProblem, setValueProblem] = useState<string | null>(null);
  const [nudged, setNudged] = useState<string | undefined>(undefined);
  const [step, setStep] = useState<string>("");
  const [factor, setFactor] = useState("0.5");
  const [where, setWhere] = useState("");
  const [whereOp, setWhereOp] = useState<EditOp>("remove");
  const [whereColumn, setWhereColumn] = useState<string | undefined>(undefined);
  const [whereValue, setWhereValue] = useState("");
  const [redo, setRedo] = useState<FeatureEdit[]>([]);
  const bodyRef = useRef<HTMLDivElement>(null);

  // A pick names features of one layer by one key: a new choice starts anew.
  useEffect(() => setPicked([]), [layer?.table, key]);
  const nudgeColumn = nudged && numbers.includes(nudged) ? nudged : numbers.find((c) => /height/i.test(c)) ?? numbers[0];
  const stepValue = Number(step) > 0 ? Number(step) : defaultStep(nudgeColumn);

  // The layer as the log leaves it, drawn a moment after the last edit.
  const edited = useMemo(() => (layer ? applyEdits(layer.fc, settings, key) : null), [layer, JSON.stringify(settings), key]);
  const [shown, setShown] = useState<typeof edited>(edited);
  useEffect(() => {
    if (shown === null || edited === null) { setShown(edited); return; }
    const timer = setTimeout(() => setShown(edited), PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edited]);
  const shownFc = shown?.fc ?? layer?.fc;
  const mapInput = useMemo(
    () => (layers && layer && shownFc ? (settings?.edits?.length ? previewInput(layers, layer, shownFc) : input) : input),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [shownFc, layers, layer, input],
  );

  const descendants = useMemo(() => descendantsOf(nodeId, flow?.edges ?? []), [nodeId, flow?.edges]);
  const status: Record<string, string> = flow?.nodeExecStatus ?? {};
  const stale = [nodeId, ...descendants].filter((id) => status[id] === "stale").length;

  const write = (next: EditFeaturesSettings | undefined, keepRedo = false) => {
    const base: EditFeaturesSettings = { ...(next ?? {}), ...(key ? { key } : {}) };
    if (layer?.name) base.layer = layer.name;
    else delete base.layer;
    if (!keepRedo) setRedo([]);
    onChange(base);
  };

  const onPicked = (op: EditOp, extra: Partial<FeatureEdit> = {}) => {
    if (picked.length === 0) return;
    write(withEdit(settings, { op, ids: picked, ...extra } as FeatureEdit));
    if (op === "remove" || op === "restore") setPicked([]);
  };

  const setValue = () => {
    if (picked.length === 0 || !column) return;
    const value = typedValue(valueText, layer?.fc, column);
    if (value === undefined) {
      setValueProblem(`${column} holds numbers; type a number.`);
      return;
    }
    setValueProblem(null);
    onPicked("set", { column, value });
  };

  const nudge = (sign: 1 | -1) => {
    if (picked.length === 0 || !nudgeColumn) return;
    write(withNudge(settings, { op: "offset", ids: picked, column: nudgeColumn, value: sign * stepValue }));
  };

  const scale = () => {
    const by = Number(factor);
    if (picked.length === 0 || !nudgeColumn || !Number.isFinite(by)) return;
    onPicked("scale", { column: nudgeColumn, value: by });
  };

  const undo = () => {
    const edits = settings?.edits ?? [];
    if (edits.length === 0) return;
    setRedo((r) => [...r, edits[edits.length - 1]]);
    write(withoutEdit(settings, edits.length - 1), true);
  };
  const redoOne = () => {
    const last = redo[redo.length - 1];
    if (!last) return;
    setRedo((r) => r.slice(0, -1));
    write(withEdit(settings, last), true);
  };

  // A condition: whether it reads, and how many features it holds for now.
  const whereProblem = where.trim() ? exprProblem(where) : null;
  const matching = useMemo(() => {
    if (!where.trim() || whereProblem || !shownFc) return null;
    const condition = parseExpr(where);
    return (shownFc.features ?? []).filter((f: any) => truthy(evaluate(condition, f?.properties ?? {}))).length;
  }, [where, whereProblem, shownFc]);
  const applyWhere = () => {
    if (!where.trim() || whereProblem) return;
    const edit: FeatureEdit = { op: whereOp, where: where.trim() };
    if (whereOp === "scale" || whereOp === "offset") {
      const n = Number(whereValue);
      if (!whereColumn || !Number.isFinite(n) || whereValue.trim() === "") return;
      Object.assign(edit, { column: whereColumn, value: n });
    } else if (whereOp === "set") {
      if (!whereColumn) return;
      const value = typedValue(whereValue, layer?.fc, whereColumn);
      if (value === undefined) return;
      Object.assign(edit, { column: whereColumn, value });
    } else if (whereOp === "expr") {
      if (!whereColumn || exprProblem(whereValue)) return;
      Object.assign(edit, { column: whereColumn, value: whereValue.trim() });
    }
    write(withEdit(settings, edit));
  };

  const onPick = (details: Record<string, any>) => {
    if (!shownFc || !key) return;
    const ids = pickedIds(details, shownFc, key);
    if (ids.length > 0) setPicked((current) => addPicked(current, ids));
    bodyRef.current?.focus({ preventScroll: true });
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!editable) return;
    const target = event.target as HTMLElement;
    if (target !== bodyRef.current && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
    const mod = event.metaKey || event.ctrlKey;
    let handled = true;
    if ((event.key === "Delete" || event.key === "Backspace") && picked.length > 0) onPicked("remove");
    else if (event.key === "Escape") setPicked([]);
    else if (event.key === "ArrowUp" && picked.length > 0) nudge(1);
    else if (event.key === "ArrowDown" && picked.length > 0) nudge(-1);
    else if (mod && event.key.toLowerCase() === "z" && event.shiftKey) redoOne();
    else if (mod && event.key.toLowerCase() === "z") undo();
    else handled = false;
    // The canvas would delete the node on Delete, and pan on the arrows.
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  const edits = settings?.edits ?? [];
  let stage: React.ReactNode;
  if (input == null || input === "") {
    stage = <NodeEmptyState reason="disconnected" hint="Connect a layer, or the layers an Autark node hands on, to edit its features." />;
  } else if (layers === null) {
    stage = <NodeEmptyState reason="not-run" hint="Reading the input." />;
  } else if (!layer) {
    stage = <NodeEmptyState reason="not-tabular" hint="The input carries no layer with features to edit." />;
  } else if (keys.length === 0) {
    stage = (
      <p className={styles.problem} data-edit-refusal="true">
        {keyRefusal(keys, layer.name ?? "This layer")}
      </p>
    );
  } else {
    stage = (
      <Suspense fallback={<NodeEmptyState reason="not-run" hint="Loading the map." />}>
        <EditFeaturesMap nodeId={nodeId} input={mapInput} docText={editMapDocument(layers, layer.table)} onPick={onPick} />
      </Suspense>
    );
  }

  const editable = writable && !!layer && keys.length > 0;
  // The picked features as the log leaves them, one row per id.
  const pickedRows = useMemo(() => {
    if (!key || !shownFc) return [];
    const want = new Set(picked.map(String));
    const seen = new Set<string>();
    const rows: Record<string, any>[] = [];
    for (const f of shownFc.features ?? []) {
      const id = String(f?.properties?.[key]);
      if (!want.has(id) || seen.has(id)) continue;
      seen.add(id);
      rows.push(f.properties ?? {});
      if (rows.length >= 12) break;
    }
    return rows;
  }, [picked, shownFc, key]);
  const tableColumns = [nudgeColumn, ...numbers.filter((c) => c !== nudgeColumn), ...columns.filter((c) => c !== key && !numbers.includes(c))]
    .filter((c): c is string => !!c)
    .slice(0, 5);
  const cellEdit = (id: SelectionId, c: string, text: string, before: unknown) => {
    const value = typedValue(text, layer?.fc, c);
    if (value === undefined || value === before) return;
    write(withEdit(settings, { op: "set", ids: [id], column: c, value }));
  };

  const button = (label: string, onClick: () => void, opts: { testId?: string; disabled?: boolean; title?: string; className?: string } = {}) => (
    <button
      type="button"
      className={`nodrag nopan ${styles.button} ${opts.className ?? ""}`}
      data-testid={opts.testId}
      disabled={opts.disabled}
      title={opts.title}
      onClick={onClick}
    >
      {label}
    </button>
  );

  return (
    <div className={styles.body} data-edit-body={nodeId} ref={bodyRef} tabIndex={0} onKeyDown={onKeyDown}>
      {layers && layer ? (
        <div className={styles.bar}>
          {layers.length > 1 ? (
            <Select
              label="Layer"
              testId="edit-features-layer"
              value={layer.table}
              options={layers.map((l) => l.table)}
              disabled={!writable || edits.length > 0}
              title={edits.length > 0 ? HELD : undefined}
              onChange={(table) => {
                const next = layers.find((l) => l.table === table);
                const nextKeys = next ? keyColumns(next.fc) : [];
                const nextKey = defaultKey(nextKeys) ?? nextKeys[0];
                onChange(normalizeEditFeatures({ ...(settings ?? {}), layer: next?.name ?? undefined, key: nextKey }));
              }}
            />
          ) : null}
          {keys.length > 0 ? (
            <Select
              label="Id"
              testId="edit-features-key"
              value={key}
              options={keys}
              disabled={!writable || edits.length > 0}
              title={edits.length > 0 ? HELD : undefined}
              onChange={(nextKey) => write({ ...(settings ?? {}), key: nextKey })}
            />
          ) : null}
          {descendants.length > 0 && writable ? (
            button(
              stale > 0 ? `Update results (${descendants.length})` : "Update results",
              () => flow?.playNodesUpTo?.([nodeId, ...descendants]),
              {
                testId: "interaction-update",
                className: stale > 0 ? styles.update : "",
                disabled: !!flow?.isRunActive,
                title: `Run this node and the ${descendants.length} node${descendants.length === 1 ? "" : "s"} after it with the edits`,
              },
            )
          ) : null}
        </div>
      ) : null}
      {key === "building_id" && keys.length > 0 ? (
        <p className={styles.note} data-edit-building-note="true">
          A building&apos;s parts share its building_id, so an edit applies to the whole building, every part.
        </p>
      ) : null}
      <div className={styles.stage}>{stage}</div>
      {edited?.problem ? <p className={styles.problem} data-edit-preview-problem="true">{edited.problem}</p> : null}
      {editable ? (
        <div className={styles.actions}>
          <span className={styles.picked} data-edit-picked={picked.join(" ")}>
            {picked.length === 0
              ? "Double-click features to pick them; then Delete removes them and ↑/↓ raise or lower them."
              : `Picked: ${key} ${picked.map(String).join(", ")}`}
          </span>
          {button("Remove", () => onPicked("remove"), { testId: "edit-features-remove", disabled: picked.length === 0, title: "Delete" })}
          {button("Restore", () => onPicked("restore"), { testId: "edit-features-restore", disabled: picked.length === 0 })}
          {button("Clear pick", () => setPicked([]), { testId: "edit-features-clear", disabled: picked.length === 0, title: "Esc" })}
          {nudgeColumn ? (
            <span className={styles.setValue}>
              <Select label="Nudge" testId="interaction-nudge-column" value={nudgeColumn} options={numbers} onChange={(c) => setNudged(c)} />
              <input
                className={`nodrag nopan ${styles.input}`}
                aria-label="Step"
                data-testid="interaction-step"
                value={step}
                placeholder={String(defaultStep(nudgeColumn))}
                onChange={(event) => setStep(event.target.value)}
              />
              {button("▲", () => nudge(1), { testId: "interaction-raise", disabled: picked.length === 0, title: "↑" })}
              {button("▼", () => nudge(-1), { testId: "interaction-lower", disabled: picked.length === 0, title: "↓" })}
              <input
                className={`nodrag nopan ${styles.input}`}
                aria-label="Factor"
                data-testid="interaction-factor"
                value={factor}
                onChange={(event) => setFactor(event.target.value)}
              />
              {button(`× ${nudgeColumn}`, scale, { testId: "interaction-scale", disabled: picked.length === 0 })}
            </span>
          ) : null}
          <span className={styles.setValue}>
            <Select label="Set" testId="edit-features-column" value={column} options={["", ...columns]} onChange={(c) => setColumn(c || undefined)} />
            <input
              className={`nodrag nopan ${styles.input}`}
              aria-label="Value"
              data-testid="edit-features-value"
              value={valueText}
              placeholder="value"
              onChange={(event) => setValueText(event.target.value)}
            />
            {button("Set value", setValue, { testId: "edit-features-set", disabled: picked.length === 0 || !column })}
          </span>
          {valueProblem ? <span className={styles.problem}>{valueProblem}</span> : null}
          {pickedRows.length > 0 && tableColumns.length > 0 ? (
            <table className={`nodrag nopan nowheel ${styles.table}`} data-testid="interaction-table">
              <thead>
                <tr>
                  <th>{key}</th>
                  {tableColumns.map((c) => <th key={c}>{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {pickedRows.map((row) => (
                  <tr key={String(row[key as string])}>
                    <td>{String(row[key as string])}</td>
                    {tableColumns.map((c) => (
                      <td key={c}>
                        <input
                          className={`nodrag nopan ${styles.cell}`}
                          aria-label={`${c} of ${row[key as string]}`}
                          defaultValue={row[c] === null || row[c] === undefined ? "" : String(row[c])}
                          key={`${c}:${String(row[c])}`}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") (event.target as HTMLInputElement).blur();
                            event.stopPropagation();
                          }}
                          onBlur={(event) => cellEdit(row[key as string], c, event.target.value, row[c])}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <span className={styles.setValue} data-testid="interaction-where-row">
            <label className={styles.field}>
              Where
              <input
                className={`nodrag nopan ${styles.input} ${styles.where}`}
                aria-label="Where"
                data-testid="interaction-where"
                value={where}
                placeholder="height > 100"
                onChange={(event) => setWhere(event.target.value)}
              />
            </label>
            <Select label="" testId="interaction-where-op" value={whereOp} options={WHERE_OPS} onChange={(op) => setWhereOp(op as EditOp)} />
            {whereOp !== "remove" && whereOp !== "restore" ? (
              <>
                <Select label="" testId="interaction-where-column" value={whereColumn} options={["", ...(whereOp === "scale" || whereOp === "offset" ? numbers : columns)]} onChange={(c) => setWhereColumn(c || undefined)} />
                <input
                  className={`nodrag nopan ${styles.input}`}
                  aria-label="By"
                  data-testid="interaction-where-value"
                  value={whereValue}
                  placeholder={whereOp === "scale" ? "0.5" : whereOp === "offset" ? "-6" : whereOp === "expr" ? "levels * 3.2" : "value"}
                  onChange={(event) => setWhereValue(event.target.value)}
                />
              </>
            ) : null}
            {button("Apply", applyWhere, { testId: "interaction-where-apply", disabled: !where.trim() || !!whereProblem })}
            {whereProblem ? <span className={styles.problem}>{whereProblem}</span> : matching !== null ? <span className={styles.matching} data-testid="interaction-matching">{matching} match</span> : null}
          </span>
        </div>
      ) : null}
      {runError ? (
        <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
          {runError}
        </p>
      ) : null}
      {writable && (edits.length > 0 || redo.length > 0) ? (
        <div className={styles.bar}>
          {button("Undo", undo, { testId: "interaction-undo", disabled: edits.length === 0, title: "Cmd/Ctrl+Z" })}
          {button("Redo", redoOne, { testId: "interaction-redo", disabled: redo.length === 0, title: "Shift+Cmd/Ctrl+Z" })}
          {edited ? <span className={styles.matching}>{edited.counts.remove} removed, {edited.counts.set} changed</span> : null}
        </div>
      ) : null}
      <ol className={`nodrag nopan nowheel ${styles.edits}`} data-edit-list={edits.length}>
        {edits.length === 0 ? <li className={styles.empty}>No edits yet: the input is handed on as it came.</li> : null}
        {edits.map((edit, index) => (
          <li key={`${index}:${edit.op}`} className={styles.edit} data-edit-op={edit.op} data-edit-enabled={edit.enabled === false ? "false" : "true"}>
            {writable ? (
              <input
                type="checkbox"
                className="nodrag nopan"
                aria-label={`Use edit ${index + 1}`}
                checked={edit.enabled !== false}
                onChange={(event) => write(withEditEnabled(settings, index, event.target.checked), true)}
              />
            ) : null}
            <span className={edit.enabled === false ? styles.off : undefined}>{describeEdit(edit, settings?.key)}</span>
            {writable ? (
              <button
                type="button"
                className={`nodrag nopan ${styles.delete}`}
                aria-label={`Delete edit ${index + 1}`}
                onClick={() => write(withoutEdit(settings, index))}
              >
                ×
              </button>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
