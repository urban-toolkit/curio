/**
 * The Interaction node's body (#662; its type id is still
 * `curio.builtin/edit-features`): the layer to edit and the column that
 * identifies its features, the input drawn on a map whose features are picked
 * with a double-click, the ways to add to the edit log (the node's setting,
 * `utils/editFeatures/editFeatures`), and the log itself:
 *
 * - on what is picked: Remove (or Delete), Clear pick (or Escape), a
 *   raise or a lower of a number column by a step (or the up and down
 *   arrows), a scale by a factor, Set value, and a table of the picked
 *   features whose cells take a new value;
 * - on the features a condition picks (`height > 100`): any of the edits,
 *   including a column computed by an expression (`levels * 3.2`);
 * - each entry of the log can be switched off or deleted; Undo and Redo (or
 *   Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z) take back the last one and make it again;
 * - Commit edits runs the node and every node below it, so their results
 *   have the edits; the log's foot says whether they do.
 *
 * The table and the condition's count read the layer as the log leaves it
 * (`applyEdits`); the map draws the node's input.
 *
 * A layer with no column that identifies its features (no `osm_id` or
 * `building_id`, and no column whose values differ in every feature) is
 * refused: a feature's place in a layer is not an id.
 *
 * Its Edit view (`LayerWorkbench`) lists every layer the input carries, by
 * the geometry of its features, with the node's own new layers, and draws the
 * picked one on a flat edit map where features are added, reshaped, moved,
 * given new values and removed. An edit on a layer other than the node's
 * names that layer, and the settings name its id column (`keys`). The Map
 * view keeps the Autark map and the tools above, on the node's layer.
 *
 * Linked to an Autark map by an interaction edge (the in/out dots, as two
 * Autark views are linked), the node is the map's panel: its layers are its
 * own inputs, which it also feeds the map, the picking and drawing happen on
 * the map (`MapEditOverlay`), and the map draws the layers with the edits
 * before Commit edits (`utils/editFeatures/mapLayerEdits`).
 */
import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { useFlowContext } from "../../providers/FlowProvider";
import { autoRunTargets } from "../../providers/flow/useAutoRun";
import { readAutkInput, autkSourcesFrom } from "../../utils/autkInput";
import type { SelectionId } from "../../utils/references/selectionTags";
import { applyEdits, type EditCounts } from "../../utils/editFeatures/applyEdits";
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
import { normalizeEdit, type NewLayerDef, type PropertyDef } from "../../utils/editFeatures/editFeatures";
import LayerWorkbench, { crsName, type WorkbenchLayer } from "./LayerWorkbench";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { circlesInto, circleTitles, mapFedBy, nodeName } from "../../utils/editFeatures/mapLayerEdits";
import styles from "./EditFeatures.module.css";

/** Why the Layer and Id menus are held while the log has edits: the edits
 * name features of that layer by that column. */
const HELD = "The edits name features of this layer by this column: delete them to pick another.";

/** The map's code loads with the first layer to draw. */
const EditFeaturesMap = React.lazy(() => import("./EditFeaturesMap"));

/** What a condition can do to the features it picks, in the order offered. */
const WHERE_OPS: EditOp[] = ["remove", "scale", "offset", "set", "expr"];

/** The tag an edit wears in the log. */
const OP_TAG: Record<EditOp, string> = {
  add: "add",
  remove: "remove",
  restore: "restore",
  set: "edit",
  scale: "edit",
  offset: "edit",
  expr: "edit",
  geometry: "shape",
  add_column: "property",
};

/** How many picked features the table lists, and how many of their columns. */
const TABLE_ROWS = 12;
const TABLE_COLUMNS = 5;

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

/** The circle an edge goes into: `in` is 0, `in_<k>` is k. */
function circleOf(handle: unknown): number {
  const m = /^in_(\d+)$/.exec(String(handle ?? ""));
  return m ? Number(m[1]) : 0;
}

/**
 * What to call the input's unnamed layers, by the table name the map gives
 * them (`input_0`, `input_0_1`, ...): the title of the node each came from.
 * An Autark map hands on its inputs as they came, so the n-th layer is the
 * map's n-th input.
 */
export function upstreamLabels(nodeId: string, nodes: any[], edges: any[]): Record<string, string> {
  const into = (id: string) => edges.filter((e) => e.target === id).sort((a, b) => circleOf(a.targetHandle) - circleOf(b.targetHandle));
  const titleOf = (id: string) => nodeName(nodes.find((n) => n.id === id));
  const feed = into(nodeId)[0];
  if (!feed) return {};
  const source = nodes.find((n) => n.id === feed.source);
  const isMap = !!source && getUnversionedFlowNodeType(source) === "curio.builtin/autk-grammar";
  const sources = isMap ? into(feed.source).map((e) => e.source) : [feed.source];
  const out: Record<string, string> = {};
  sources.forEach((id, n) => {
    const title = titleOf(id);
    // One table per circle, input_<n>; or the n-th more of one input, input_0_<n>.
    if (title) {
      out[`input_${n}`] = title;
      if (n > 0) out[`input_0_${n}`] = title;
    }
  });
  return out;
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

type Row = Record<string, unknown>;

/** The layer's features' properties as the log leaves them (null for a removed one), or why the log cannot apply. */
function editedRows(
  fc: { features?: any[] } | undefined,
  settings: EditFeaturesSettings | undefined,
  key: string | undefined,
): { rows: (Row | null)[]; counts: EditCounts; problem: string | null } {
  const input: Row[] = (fc?.features ?? []).map((feature) => (feature?.properties ?? {}) as Row);
  const none = { remove: 0, set: 0, restore: 0 };
  if (!key || !settings?.edits?.length) return { rows: input, counts: none, problem: null };
  try {
    const { state, counts } = applyEdits(input, settings.edits, key);
    return { rows: state, counts, problem: null };
  } catch (error) {
    return { rows: input, counts: none, problem: error instanceof Error ? error.message : String(error) };
  }
}

/** The columns of *columns* that hold numbers in the first features of *fc*. */
function numberColumns(fc: { features?: any[] } | undefined, columns: readonly string[]): string[] {
  const features = (fc?.features ?? []).slice(0, 50);
  return columns.filter((column) => features.some((feature) => typeof feature?.properties?.[column] === "number"));
}

/** The step an arrow press moves *column* by: a floor, 3 m, for a height, else 1. */
const defaultStep = (column: string | undefined) => (column && /height/i.test(column) ? 3 : 1);

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

function Button({
  children,
  onClick,
  testId,
  disabled,
  title,
  className,
}: {
  children: React.ReactNode;
  onClick: () => void;
  testId?: string;
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`nodrag nopan ${styles.button}${className ? ` ${className}` : ""}`}
      data-testid={testId}
      disabled={disabled}
      title={title}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

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
  // Linked to an Autark map by an interaction edge, the node edits on that
  // map; its layers are its own inputs either way.
  const mapId = mapFedBy(nodeId, flow?.nodes ?? [], flow?.edges ?? []);
  const mapNode = mapId ? (flow?.nodes ?? []).find((n: any) => n.id === mapId) : undefined;
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
  const [step, setStep] = useState("");
  const [factor, setFactor] = useState("0.5");
  const [where, setWhere] = useState("");
  const [whereOp, setWhereOp] = useState<EditOp>("remove");
  const [whereColumn, setWhereColumn] = useState<string | undefined>(undefined);
  const [whereValue, setWhereValue] = useState("");
  // The entries Undo took back, the last one first to be made again.
  const [redo, setRedo] = useState<FeatureEdit[]>([]);
  const bodyRef = useRef<HTMLDivElement>(null);

  // A pick names features of one layer by one key: a new choice starts anew.
  useEffect(() => setPicked([]), [layer?.table, key]);

  const nudgeColumn = nudged && numbers.includes(nudged) ? nudged : numbers.find((c) => /height/i.test(c)) ?? numbers[0];
  const stepValue = Number(step) > 0 ? Number(step) : defaultStep(nudgeColumn);

  // The layer as the log leaves it: what the table and a condition's count read.
  const logKey = JSON.stringify(settings?.edits ?? []);
  // The tools of the Map view read the node's layer: only the edits on it.
  const nodeEdits = useMemo(
    () => (settings?.edits ?? []).filter((e) => !e.layer || e.layer === (settings?.layer ?? layer?.name ?? undefined)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [logKey, settings?.layer, layer?.name],
  );
  const edited = useMemo(
    () => editedRows(layer?.fc, settings ? { ...settings, edits: nodeEdits } : settings, key),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layer, nodeEdits, key],
  );
  const [view, setView] = useState<"edit" | "map">("edit");

  // Every layer the Edit view offers: the input's, each with its id column,
  // then the node's own.
  const labels = useMemo(() => {
    // Fed by several nodes, each circle's layer is named after its circle.
    if (circlesInto(nodeId, flow?.edges ?? []) <= 1) return upstreamLabels(nodeId, flow?.nodes ?? [], flow?.edges ?? []);
    const titles = circleTitles(nodeId, flow?.nodes ?? [], flow?.edges ?? []);
    return Object.fromEntries(Object.entries(titles).map(([k, title]) => [`input_${k}`, title]));
  }, [nodeId, flow?.nodes, flow?.edges]);
  const workbenchLayers = useMemo<WorkbenchLayer[]>(() => {
    const input = (layers ?? []).map((l) => {
      const name = l.name ?? l.table;
      const label = l.name ? l.name : labels[l.table] ?? l.table;
      const ids = keyColumns(l.fc);
      const saved = settings?.keys?.[name] ?? (name === settings?.layer ? settings?.key : undefined);
      const layerKey = saved && ids.includes(saved) ? saved : defaultKey(ids) ?? ids[0];
      return { name, label, table: l.table, fc: l.fc as WorkbenchLayer["fc"], key: layerKey };
    });
    const first = input[0]?.fc;
    const made = (settings?.newLayers ?? []).map((def) => ({
      name: def.name,
      label: def.name,
      fc: { type: "FeatureCollection", features: [], ...(first?.crs ? { crs: first.crs } : {}) } as WorkbenchLayer["fc"],
      key: "id",
      newLayer: def,
    }));
    return [...input, ...made];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers, labels, settings?.keys, settings?.layer, settings?.key, JSON.stringify(settings?.newLayers ?? [])]);

  /** *more* written into the log as edits of *target*: the node's layer's
   * plainly, another layer's naming it, with its id column in `keys`. */
  const writeOn = (more: FeatureEdit[], target: WorkbenchLayer) => {
    let next: EditFeaturesSettings = { ...(settings ?? {}) };
    const tagged: FeatureEdit[] = [];
    for (const raw of more) {
      let edit = raw;
      if (target.newLayer) edit = { ...raw, layer: target.name };
      else {
        if (!next.layer) {
          next.layer = target.name;
          if (target.key) next.key = target.key;
        }
        if (target.name !== next.layer) {
          edit = { ...raw, layer: target.name };
          if (target.key) next.keys = { ...(next.keys ?? {}), [target.name]: target.key };
        }
      }
      if (normalizeEdit(edit)) tagged.push(edit);
    }
    if (tagged.length === 0) return;
    if (tagged.some((e) => e.geometry) && !next.crs) next.crs = crsName(target.newLayer ? workbenchLayers.find((l) => !l.newLayer)?.fc : target.fc);
    for (const edit of tagged) next = withEdit(next, edit);
    setRedo([]);
    onChange(normalizeEditFeatures(next));
  };
  const addNewLayer = (def: NewLayerDef) => {
    setRedo([]);
    onChange(normalizeEditFeatures({ ...(settings ?? {}), newLayers: [...(settings?.newLayers ?? []), def] }));
  };
  const addLayerProperty = (layerName: string, def: PropertyDef) => {
    const newLayers = (settings?.newLayers ?? []).map((l) =>
      l.name === layerName ? { ...l, properties: [...(l.properties ?? []).filter((p) => p.name !== def.name), def] } : l,
    );
    onChange(normalizeEditFeatures({ ...(settings ?? {}), newLayers }));
  };

  // The node and every node below it, as an automatic run takes them.
  const targets = useMemo(
    () => autoRunTargets([nodeId], flow?.nodes ?? [], flow?.edges ?? []),
    [nodeId, flow?.nodes, flow?.edges],
  );
  const below = targets.length - 1;
  const status: Record<string, string> = flow?.nodeExecStatus ?? {};
  const outOfDate = targets.filter((id) => status[id] === "stale").length;
  const running = !!flow?.isRunActive || !!flow?.serverRunActive;

  const write = (next: EditFeaturesSettings | undefined, keepRedo = false) => {
    if (!keepRedo) setRedo([]);
    // On a map, every edit names its layer and id column already (writeOn):
    // the log's layer is never the Map view's.
    if (mapId) {
      onChange(normalizeEditFeatures(next));
      return;
    }
    const base: EditFeaturesSettings = { ...(next ?? {}), ...(key ? { key } : {}) };
    if (layer?.name) base.layer = layer.name;
    else delete base.layer;
    onChange(base);
  };

  const onPicked = (op: EditOp, extra: Pick<FeatureEdit, "column" | "value"> = {}) => {
    if (picked.length === 0) return;
    write(withEdit(settings, { op, ids: picked, ...extra }));
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
    if (picked.length === 0 || !nudgeColumn || factor.trim() === "" || !Number.isFinite(by)) return;
    onPicked("scale", { column: nudgeColumn, value: by });
  };

  const edits = settings?.edits ?? [];
  const undo = () => {
    if (edits.length === 0) return;
    setRedo((taken) => [...taken, edits[edits.length - 1]]);
    write(withoutEdit(settings, edits.length - 1), true);
  };
  const redoLast = () => {
    const last = redo[redo.length - 1];
    if (!last) return;
    setRedo((taken) => taken.slice(0, -1));
    write(withEdit(settings, last), true);
  };

  // A condition: whether it reads, and how many features it picks now.
  const whereProblem = where.trim() ? exprProblem(where) : null;
  const matching = useMemo(() => {
    if (!where.trim() || whereProblem) return null;
    const condition = parseExpr(where);
    return edited.rows.filter((row) => row !== null && truthy(evaluate(condition, row))).length;
  }, [where, whereProblem, edited]);
  const writesColumn = whereOp !== "remove" && whereOp !== "restore";
  const whereEdit = (): FeatureEdit | null => {
    if (!where.trim() || whereProblem) return null;
    const edit: FeatureEdit = { op: whereOp, where: where.trim() };
    if (!writesColumn) return edit;
    if (!whereColumn) return null;
    if (whereOp === "scale" || whereOp === "offset") {
      const by = Number(whereValue);
      return whereValue.trim() === "" || !Number.isFinite(by) ? null : { ...edit, column: whereColumn, value: by };
    }
    if (whereOp === "expr") {
      return whereValue.trim() === "" || exprProblem(whereValue) ? null : { ...edit, column: whereColumn, value: whereValue.trim() };
    }
    const value = typedValue(whereValue, layer?.fc, whereColumn);
    return value === undefined ? null : { ...edit, column: whereColumn, value };
  };
  const applyWhere = () => {
    const edit = whereEdit();
    if (edit) write(withEdit(settings, edit));
  };

  const onPick = (details: Record<string, any>) => {
    if (!layer || !key) return;
    const ids = pickedIds(details, layer.fc, key);
    if (ids.length > 0) setPicked((current) => addPicked(current, ids));
    // The keys act on the pick from here.
    bodyRef.current?.focus({ preventScroll: true });
  };

  const editable = writable && !!layer && keys.length > 0;

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!editable) return;
    const target = event.target as HTMLElement;
    // A key typed in one of the node's fields is the field's.
    if (target !== bodyRef.current && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
    const mod = event.metaKey || event.ctrlKey;
    let handled = true;
    if ((event.key === "Delete" || event.key === "Backspace") && picked.length > 0) onPicked("remove");
    else if (event.key === "Escape" && picked.length > 0) setPicked([]);
    else if (event.key === "ArrowUp" && picked.length > 0 && nudgeColumn) nudge(1);
    else if (event.key === "ArrowDown" && picked.length > 0 && nudgeColumn) nudge(-1);
    else if (mod && event.key.toLowerCase() === "z" && event.shiftKey) redoLast();
    else if (mod && event.key.toLowerCase() === "z") undo();
    else handled = false;
    // Handled here, the canvas neither deletes the node nor moves it.
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  // The picked features as the log leaves them, one row per id.
  const pickedRows = useMemo(() => {
    if (!key || !layer) return [];
    const wanted = new Set(picked.map(String));
    const seen = new Set<string>();
    const rows: Row[] = [];
    edited.rows.forEach((row) => {
      if (row === null || rows.length >= TABLE_ROWS) return;
      const id = String(row[key]);
      if (!wanted.has(id) || seen.has(id)) return;
      seen.add(id);
      rows.push(row);
    });
    return rows;
  }, [picked, edited, key, layer]);
  const tableColumns = [
    ...(nudgeColumn ? [nudgeColumn] : []),
    ...numbers.filter((c) => c !== nudgeColumn),
    ...columns.filter((c) => c !== key && !numbers.includes(c)),
  ].slice(0, TABLE_COLUMNS);
  const cellEdit = (id: unknown, cellColumn: string, text: string, before: unknown) => {
    if (typeof id !== "string" && typeof id !== "number") return;
    const value = typedValue(text, layer?.fc, cellColumn);
    if (value === undefined || value === before) return;
    write(withEdit(settings, { op: "set", ids: [id], column: cellColumn, value }));
  };

  // The log, by the layer each edit is on, as the mockup's last step lists it.
  const layerOf = (edit: FeatureEdit) => edit.layer ?? settings?.layer ?? "";
  const logGroups: { layer: string; entries: { edit: FeatureEdit; index: number }[] }[] = [];
  edits.forEach((edit, index) => {
    const layerName = layerOf(edit);
    let group = logGroups.find((g) => g.layer === layerName);
    if (!group) logGroups.push((group = { layer: layerName, entries: [] }));
    group.entries.push({ edit, index });
  });
  // The foot of the log: whether the nodes below have the edits, and Commit
  // edits to run them with them.
  const commitFoot =
    writable && below > 0 && (outOfDate > 0 || running || edits.length > 0) ? (
      <div className={`${styles.commit} ${outOfDate > 0 && !running ? styles.commitStale : ""}`} data-testid="interaction-commit" data-commit-state={running ? "running" : outOfDate > 0 ? "stale" : "done"}>
        {outOfDate > 0 || running ? (
          <>
            {running ? null : <span className={styles.commitText}>The downstream nodes don&apos;t have these edits yet.</span>}
            <button
              type="button"
              className={`nodrag nopan ${styles.commitButton}`}
              data-testid="interaction-update"
              disabled={running}
              title={`Runs this node and the ${below} node${below === 1 ? "" : "s"} below it with the edits`}
              onClick={() => flow?.runDownstream?.([nodeId])}
            >
              {running ? "Running…" : "Commit edits"}
            </button>
          </>
        ) : (
          <span className={styles.commitDone}>✓ Edits committed</span>
        )}
      </div>
    ) : null;
  const editLog = (
    <section className={`nodrag nopan ${styles.log}`} data-testid="interaction-log">
      <div className={styles.logHead}>
        <b>Edits</b>
        <span className={styles.logCount}>{edits.length}</span>
        {!mapId && edits.length > 0 ? (
          <span className={styles.logSummary} data-testid="interaction-counts">
            {`${edited.counts.remove} removed, ${edited.counts.set} changed`}
            {edited.counts.restore > 0 ? `, ${edited.counts.restore} restored` : ""}
          </span>
        ) : null}
        <span style={{ flex: 1 }} />
        {writable ? (
          <span className={styles.history}>
            <button type="button" className="nodrag nopan" data-testid="interaction-undo" disabled={edits.length === 0} title="Undo (Ctrl or Cmd+Z)" onClick={undo}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M9 14L4 9l5-5" />
                <path d="M4 9h10.5a5.5 5.5 0 010 11H11" />
              </svg>
              Undo
            </button>
            <button type="button" className="nodrag nopan" data-testid="interaction-redo" disabled={redo.length === 0} title="Redo (Shift+Ctrl or Cmd+Z)" onClick={redoLast}>
              Redo
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M15 14l5-5-5-5" />
                <path d="M20 9H9.5a5.5 5.5 0 000 11H13" />
              </svg>
            </button>
          </span>
        ) : null}
      </div>
      <div className={`nowheel ${styles.logBody}`} data-edit-list={edits.length}>
        {edits.length === 0 ? (
          <p className={styles.logEmpty}>{mapId ? "No edits yet: the map draws its layers as they came." : "No edits yet: the input is handed on as it came."}</p>
        ) : null}
        {logGroups.map((group) => {
          const target = workbenchLayers.find((l) => l.name === group.layer);
          return (
            <div key={group.layer || "-"} className={styles.logGroup}>
              {group.layer ? (
                <span className={styles.logLayer}>
                  {target?.label ?? group.layer} <span>· {target?.newLayer ? "new layer" : "edited"}</span>
                </span>
              ) : null}
              <ol>
                {group.entries.map(({ edit, index }) => (
                  <li key={`${index}:${edit.op}`} className={`${styles.logRow} ${edit.enabled === false ? styles.logOff : ""}`} data-edit-op={edit.op} data-edit-enabled={edit.enabled === false ? "false" : "true"}>
                    <span className={`${styles.opTag} ${styles[`op_${OP_TAG[edit.op]}`] ?? ""}`}>{OP_TAG[edit.op]}</span>
                    <span className={`${styles.logText} ${edit.enabled === false ? styles.off : ""}`}>
                      {describeEdit(
                        edit,
                        edit.layer ? settings?.keys?.[edit.layer] ?? (settings?.newLayers?.some((l) => l.name === edit.layer) ? "id" : settings?.key) : settings?.key,
                        undefined,
                      )}
                    </span>
                    {writable ? (
                      <>
                        <input
                          type="checkbox"
                          className={`nodrag nopan ${styles.logSwitch}`}
                          aria-label={`Use edit ${index + 1}`}
                          title={edit.enabled === false ? "Switched off: the run skips it" : "Switch off, keeping it in the log"}
                          checked={edit.enabled !== false}
                          onChange={(event) => write(withEditEnabled(settings, index, event.target.checked), true)}
                        />
                        <button type="button" className={`nodrag nopan ${styles.logDelete}`} aria-label={`Delete edit ${index + 1}`} title="Delete this edit" onClick={() => write(withoutEdit(settings, index))}>
                          ×
                        </button>
                      </>
                    ) : null}
                  </li>
                ))}
              </ol>
            </div>
          );
        })}
      </div>
      {commitFoot}
    </section>
  );

  if (mapId) {
    const mapTitle = nodeName(mapNode) || "the Autark map";
    return (
      <div className={`nokey ${styles.body}`} data-edit-body={nodeId} data-edit-map={mapId} ref={bodyRef} tabIndex={0} onKeyDown={onKeyDown}>
        <div className={styles.bar}>
          <span className={styles.connected} data-testid="interaction-connected">
            Linked to {mapTitle}
          </span>
        </div>
        {layers === null ? (
          <NodeEmptyState reason="not-run" hint="Reading the layers." />
        ) : layers.length === 0 ? (
          <NodeEmptyState reason="not-run" hint="Run the nodes that feed this node to edit their layers here." />
        ) : (
          <LayerWorkbench
            layers={workbenchLayers}
            edits={edits}
            nodeLayer={settings?.layer ?? null}
            writable={writable}
            picked={picked}
            setPicked={setPicked}
            onEdit={(edit, target) => writeOn([edit], target)}
            onEdits={(more, target) => writeOn(more, target)}
            onNewLayer={addNewLayer}
            onAddLayerProperty={addLayerProperty}
            mapId={mapId}
            nodeId={nodeId}
          />
        )}
        {edited.problem ? (
          <p className={styles.problem} data-edit-log-problem="true">
            {edited.problem}
          </p>
        ) : null}
        {runError ? (
          <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
            {runError}
          </p>
        ) : null}
        {editLog}
      </div>
    );
  }

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
        <EditFeaturesMap nodeId={nodeId} input={input} docText={editMapDocument(layers, layer.table)} onPick={onPick} />
      </Suspense>
    );
  }

  return (
    <div className={`nokey ${styles.body}`} data-edit-body={nodeId} ref={bodyRef} tabIndex={0} onKeyDown={onKeyDown}>
      {layers && layer ? (
        <div className={styles.bar}>
          {layers.length > 1 && view === "map" ? (
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
          {keys.length > 0 && view === "map" ? (
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
        </div>
      ) : null}
      {key === "building_id" && keys.length > 0 && view === "map" ? (
        <p className={styles.note} data-edit-building-note="true">
          A building&apos;s parts share its building_id, so an edit applies to the whole building, every part.
        </p>
      ) : null}
      {layers && layers.length > 0 ? (
        <span className={styles.segmented} role="tablist" aria-label="View">
          <button type="button" role="tab" aria-selected={view === "edit"} data-testid="interaction-view-edit" className={`nodrag nopan ${view === "edit" ? styles.on : ""}`} onClick={() => setView("edit")}>
            Edit
          </button>
          <button type="button" role="tab" aria-selected={view === "map"} data-testid="interaction-view-map" className={`nodrag nopan ${view === "map" ? styles.on : ""}`} onClick={() => setView("map")}>
            Map and tools
          </button>
        </span>
      ) : null}
      {view === "edit" && layers && layers.length > 0 ? (
        <LayerWorkbench
          layers={workbenchLayers}
          edits={edits}
          nodeLayer={settings?.layer ?? null}
          writable={writable}
          picked={picked}
          setPicked={setPicked}
          onEdit={(edit, target) => writeOn([edit], target)}
          onEdits={(more, target) => writeOn(more, target)}
          onNewLayer={addNewLayer}
          onAddLayerProperty={addLayerProperty}
        />
      ) : (
        <div className={styles.stage}>{stage}</div>
      )}
      {edited.problem ? (
        <p className={styles.problem} data-edit-log-problem="true">
          {edited.problem}
        </p>
      ) : null}
      {editable && view === "map" ? (
        <div className={styles.actions}>
          <span className={styles.picked} data-edit-picked={picked.join(" ")}>
            {picked.length === 0
              ? "Double-click features on the map to pick them."
              : `Picked: ${key} ${picked.map(String).join(", ")}`}
          </span>
          <Button testId="edit-features-remove" disabled={picked.length === 0} title="Delete" onClick={() => onPicked("remove")}>
            Remove
          </Button>
          <Button testId="edit-features-clear" disabled={picked.length === 0} title="Escape" onClick={() => setPicked([])}>
            Clear pick
          </Button>
          {nudgeColumn ? (
            <span className={styles.setValue}>
              <Select label="Nudge" testId="interaction-nudge-column" value={nudgeColumn} options={numbers} onChange={(c) => setNudged(c)} />
              <input
                className={`nodrag nopan ${styles.input} ${styles.short}`}
                aria-label="Step"
                data-testid="interaction-step"
                value={step}
                placeholder={String(defaultStep(nudgeColumn))}
                onChange={(event) => setStep(event.target.value)}
              />
              <Button testId="interaction-raise" disabled={picked.length === 0} title={`Raise ${nudgeColumn} (up arrow)`} onClick={() => nudge(1)}>
                ▲
              </Button>
              <Button testId="interaction-lower" disabled={picked.length === 0} title={`Lower ${nudgeColumn} (down arrow)`} onClick={() => nudge(-1)}>
                ▼
              </Button>
              <input
                className={`nodrag nopan ${styles.input} ${styles.short}`}
                aria-label="Factor"
                data-testid="interaction-factor"
                value={factor}
                onChange={(event) => setFactor(event.target.value)}
              />
              <Button testId="interaction-scale" disabled={picked.length === 0} title={`Multiply ${nudgeColumn} by the factor`} onClick={scale}>
                Scale
              </Button>
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
            <Button testId="edit-features-set" disabled={picked.length === 0 || !column} onClick={setValue}>
              Set value
            </Button>
          </span>
          {valueProblem ? <span className={styles.problem}>{valueProblem}</span> : null}
          {pickedRows.length > 0 && tableColumns.length > 0 ? (
            <table className={`nodrag nopan nowheel ${styles.table}`} data-testid="interaction-table">
              <thead>
                <tr>
                  <th>{key}</th>
                  {tableColumns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pickedRows.map((row) => {
                  const id = row[key as string];
                  return (
                    <tr key={String(id)}>
                      <td>{String(id)}</td>
                      {tableColumns.map((c) => (
                        <td key={c}>
                          <input
                            className={`nodrag nopan ${styles.cell}`}
                            aria-label={`${c} of ${String(id)}`}
                            defaultValue={row[c] === null || row[c] === undefined ? "" : String(row[c])}
                            // A new value from the log shows a fresh field.
                            key={`${c}:${String(row[c])}`}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") (event.target as HTMLInputElement).blur();
                            }}
                            onBlur={(event) => cellEdit(id, c, event.target.value, row[c])}
                          />
                        </td>
                      ))}
                    </tr>
                  );
                })}
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
            {writesColumn ? (
              <>
                <Select
                  label=""
                  testId="interaction-where-column"
                  value={whereColumn}
                  options={["", ...(whereOp === "scale" || whereOp === "offset" ? numbers : columns)]}
                  onChange={(c) => setWhereColumn(c || undefined)}
                />
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
            <Button testId="interaction-where-apply" disabled={whereEdit() === null} onClick={applyWhere}>
              Apply
            </Button>
            {whereProblem ? (
              <span className={styles.problem} data-testid="interaction-where-problem">
                {whereProblem}
              </span>
            ) : matching !== null ? (
              <span className={styles.matching} data-testid="interaction-matching">
                {matching === 1 ? "1 feature" : `${matching} features`}
              </span>
            ) : null}
          </span>
        </div>
      ) : null}
      {runError ? (
        <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
          {runError}
        </p>
      ) : null}
      {editLog}
    </div>
  );
}
