/**
 * The Map Editor node's body (#662; its type id is still
 * `curio.builtin/edit-features`): the layers it is fed, what can be done with
 * each (`LayerWorkbench`), on the Autark map it feeds and is linked to, and
 * its edit log:
 *
 * - each entry of the log can be switched off or deleted;
 * - Undo puts back the entry before in the node's Provenance drawer, and Redo
 *   the newest one after it (or Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z); neither adds
 *   an entry, and the next change branches from there;
 * - Delete removes the picked features, and Escape clears the pick;
 * - Commit edits runs the node and every node below it, so their results
 *   have the edits; the log's foot says whether they do.
 *
 * The node's code is its only state. The body reads the edits from it on every
 * render (`readEditFeaturesCode`) and writes a new code for each change, which
 * adds an entry to the node's Provenance drawer. The code is mirrored into the
 * node's data without a change of the flow's state (useNodeState), so the body
 * listens for code edits, as the Parameter node does: a code put back from the
 * Provenance drawer shows its edits at once, in the list and on the map.
 *
 * Code the node cannot read is never rewritten: the body says why and offers
 * nothing, and a run still runs the code. A layer with no column that
 * identifies its features (no `osm_id` or `building_id`, and no column whose
 * values differ in every feature) cannot be edited: a feature's place in a
 * layer is not an id.
 *
 * Linked to no Autark map it feeds, the node says to link one, and its list
 * stays.
 */
import React, { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRotateLeft, faRotateRight, faXmark } from "@fortawesome/free-solid-svg-icons";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { MOD_KEY_LABEL, isTypingTarget } from "../canvasKeyBindings";
import { useFlowContext } from "../../providers/FlowProvider";
import { useProvenanceContext, type NodeExecRecord } from "../../providers/ProvenanceProvider";
import { autoRunTargets } from "../../providers/flow/useAutoRun";
import { readAutkInput, autkSourcesFrom } from "../../utils/autkInput";
import { codeEditRevision, subscribeToCodeEdits } from "../../utils/references/codeEdits";
import type { SelectionId } from "../../utils/references/selectionTags";
import { applyEdits, type EditCounts } from "../../utils/editFeatures/applyEdits";
import {
  defaultKey,
  describeEdit,
  editFeaturesCode,
  keyColumns,
  normalizeEdit,
  normalizeEditFeatures,
  readEditFeaturesCode,
  withEdit,
  withEditEnabled,
  withoutEdit,
  type EditFeaturesSettings,
  type EditOp,
  type FeatureEdit,
  type NewLayerDef,
  type PropertyDef,
} from "../../utils/editFeatures/editFeatures";
import { crsName } from "../../utils/editFeatures/layerModel";
import LayerWorkbench, { type EditSurface, type WorkbenchLayer } from "./LayerWorkbench";
import { CheckboxInput, FieldTheme } from "./fields";
import { getUnversionedFlowNodeType } from "../../utils/flowNodeCanonicalType";
import { NodeType, VisInteractionType } from "../../constants";
import { inputSlotOf, isDataEdge, wiredInputSlots } from "../../utils/inputSlots";
import { EDIT_SELECTION } from "../../utils/editFeatures/mapEditSelection";
import { circlesInto, circleTitles, linkedMaps, nodeCode, nodeName } from "../../utils/editFeatures/mapLayerEdits";
import { redoStep, undoStep, type HistoryStep } from "../../utils/nodeRuns";
import styles from "./EditFeatures.module.css";

/** How a change is written into the node. */
export interface CodeWrite {
  /** What the change was, for the entry it adds to the node's Provenance drawer; none adds no entry. */
  label?: string;
  /** A rewrite that changes nothing the node does (its circles): no Unsaved mark, no stale marks, no entry. */
  quiet?: boolean;
}

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

/** The status tone a tag takes (ScenarioLayers' tones): an addition done, a removal danger, the rest none. */
const OP_TONE: Partial<Record<EditOp, "done" | "error">> = { add: "done", remove: "error" };

/** At most this many edits name an entry of the Provenance drawer, then how many more. */
const LABEL_EDITS = 3;
const NO_ENTRIES: NodeExecRecord[] = [];

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
  const isMap = !!source && getUnversionedFlowNodeType(source) === NodeType.AUTK_GRAMMAR;
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
    const named = layers.find((layer) => (layer.name ?? layer.table) === settings.layer);
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

export function EditFeaturesBody({
  nodeId,
  runError = null,
  onWrite,
}: {
  nodeId: string;
  /** Why the node's last run failed. */
  runError?: string | null;
  /** Writes *code* into the node; *change* says whether it is an entry of its history. */
  onWrite: (code: string, change?: CodeWrite) => void;
}) {
  const flow = useFlowContext() as any;
  // A code put back, or typed, reaches the node's data with no change of the flow's state.
  useSyncExternalStore(subscribeToCodeEdits, codeEditRevision);
  const { provenanceGraphNodes, selectedParentExecRef, setSelectedExec } = useProvenanceContext();
  const live = (flow?.nodes ?? []).find((n: any) => n.id === nodeId)?.data;
  // The Autark maps the node feeds and is linked to: it picks and draws on
  // each, and names the first.
  const linked = linkedMaps(nodeId, flow?.nodes ?? [], flow?.edges ?? []);
  const linkedKey = linked.join(" ");
  const mapId = linked[0] ?? null;
  const mapNode = mapId ? (flow?.nodes ?? []).find((n: any) => n.id === mapId) : undefined;
  const surfaces = useMemo<EditSurface[]>(() => {
    const edges: any[] = flow?.edges ?? [];
    return linked.map((id) => {
      const wired = wiredInputSlots(edges, id);
      const into = edges.find((edge) => edge.source === nodeId && edge.target === id && isDataEdge(edge));
      return { mapId: id, position: Math.max(0, wired.indexOf(inputSlotOf(into?.targetHandle))), several: wired.length > 1 };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedKey, flow?.edges, nodeId]);
  const input = live?.input;
  const code = nodeCode(live);
  const read = useMemo(() => readEditFeaturesCode(code), [code]);
  const unreadable = "problem" in read ? read.problem : null;
  const settings = "problem" in read ? undefined : read.settings;
  const comments = "problem" in read ? undefined : read.comments;
  const circles = circlesInto(nodeId, flow?.edges ?? []);
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";
  const editable = writable && unreadable === null;
  const layers = useInputLayers(input);
  const layer = layers ? chosenLayer(layers, settings) : undefined;
  const keys = useMemo(() => (layer ? keyColumns(layer.fc) : []), [layer]);
  const key = settings?.key && keys.includes(settings.key) ? settings.key : defaultKey(keys) ?? keys[0];
  // The features picked in the layer the Edit view works on: the workbench
  // starts the pick anew when that layer, its id column or the linked maps
  // change (LayerWorkbench).
  const [picked, setPicked] = useState<SelectionId[]>([]);
  const bodyRef = useRef<HTMLDivElement>(null);
  // Removes the picked features of the layer the Edit view works on (Delete).
  const removePickedRef = useRef<(() => boolean) | null>(null);

  // What the node selects, sent once for each change: the interaction edges
  // carry it to the maps, which light it up.
  const sentRef = useRef<string | null>(null);
  const lastSentRef = useRef<Record<string, any> | null>(null);
  const sendSelection = (details: Record<string, any> | null) => {
    // Nothing selected: what the maps lit up last is cleared, once.
    const last = lastSentRef.current?.[EDIT_SELECTION];
    const next = details ?? (last && (last.data?.length ?? 0) > 0 ? { [EDIT_SELECTION]: { ...last, type: VisInteractionType.UNDETERMINED, data: [] } } : null);
    if (!next) return;
    const text = JSON.stringify(next);
    if (text === sentRef.current) return;
    sentRef.current = text;
    lastSentRef.current = next;
    live?.interactionsCallback?.(next, nodeId);
  };

  // The layer as the log leaves it: what the counts read.
  const logKey = JSON.stringify(settings?.edits ?? []);
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

  // Every layer the Edit view offers: the input's, each with its id column,
  // then the node's own.
  const labels = useMemo(() => {
    // Fed by several nodes, each circle's layer is named after its circle.
    if (circlesInto(nodeId, flow?.edges ?? []) <= 1) return upstreamLabels(nodeId, flow?.nodes ?? [], flow?.edges ?? []);
    const titles = circleTitles(nodeId, flow?.nodes ?? [], flow?.edges ?? []);
    return Object.fromEntries(Object.entries(titles).map(([k, title]) => [`input_${k}`, title]));
  }, [nodeId, flow?.nodes, flow?.edges]);
  // The layer the node's own edits apply to: the one its code names, else
  // the only one there is, as the map's preview (`targetOf`) and a run read it.
  const inputNames = (layers ?? []).map((l) => l.name ?? l.table);
  const ownLayer = settings?.layer ?? (inputNames.length === 1 ? inputNames[0] : undefined);
  const workbenchLayers = useMemo<WorkbenchLayer[]>(() => {
    const input = (layers ?? []).map((l) => {
      const name = l.name ?? l.table;
      const label = l.name ? l.name : labels[l.table] ?? l.table;
      const ids = keyColumns(l.fc);
      const saved = settings?.keys?.[name] ?? (name === ownLayer ? settings?.key : undefined);
      const layerKey = saved && ids.includes(saved) ? saved : defaultKey(ids) ?? ids[0];
      return { name, label, table: l.table, ownName: l.name !== null, fc: l.fc as WorkbenchLayer["fc"], key: layerKey };
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
  }, [layers, labels, settings?.keys, ownLayer, settings?.key, JSON.stringify(settings?.newLayers ?? [])]);

  /** The column an edit names its features by, in *of* (the node's code). */
  const keyOf = (edit: FeatureEdit, of: EditFeaturesSettings | undefined = settings) =>
    edit.layer ? of?.keys?.[edit.layer] ?? (of?.newLayers?.some((l) => l.name === edit.layer) ? "id" : of?.key) : of?.key;
  /** An entry's name in the Provenance drawer: what its edits do, by the id columns of *of*, the code they are written into. */
  const labelOf = (edits: readonly FeatureEdit[], of: EditFeaturesSettings | undefined) => {
    const named = edits.slice(0, LABEL_EDITS).map((edit) => describeEdit(edit, keyOf(edit, of)));
    return edits.length > LABEL_EDITS ? `${named.join("; ")} and ${edits.length - LABEL_EDITS} more` : named.join("; ");
  };

  /** Writes *next* as the node's code, keeping the comment lines it has; *label* names the change. */
  const writeSettings = (next: EditFeaturesSettings | undefined, label: string) => {
    if (!editable) return;
    onWrite(editFeaturesCode(normalizeEditFeatures(next), circles, comments), { label });
  };

  /** *more* written into the log as edits of *target*: the node's layer's
   * plainly, another layer's naming it, with its id column in `keys`; with
   * *property*, the one a new layer's next features are asked for, in the
   * same change. */
  const writeOn = (more: FeatureEdit[], target: WorkbenchLayer, property?: PropertyDef) => {
    let next: EditFeaturesSettings = { ...(settings ?? {}) };
    // A shape is drawn in its layer's own coordinates (a new layer's, the
    // first layer's), so each drawn edit names that CRS: layers in different
    // CRSs, such as degrees beside metres, each read their own shapes.
    const drawnIn = crsName(target.newLayer ? workbenchLayers.find((l) => !l.newLayer)?.fc : target.fc);
    const tagged: FeatureEdit[] = [];
    for (const raw of more) {
      let edit = raw.geometry && drawnIn ? { ...raw, crs: drawnIn } : raw;
      if (target.newLayer) edit = { ...edit, layer: target.name };
      else {
        if (!next.layer) {
          next.layer = target.name;
          if (target.key) next.key = target.key;
        }
        if (target.name !== next.layer) {
          edit = { ...edit, layer: target.name };
          if (target.key) next.keys = { ...(next.keys ?? {}), [target.name]: target.key };
        }
      }
      if (normalizeEdit(edit)) tagged.push(edit);
    }
    if (tagged.length === 0) return;
    if (tagged.some((e) => e.geometry) && !next.crs && drawnIn) next.crs = drawnIn;
    if (property && target.newLayer) {
      next.newLayers = (next.newLayers ?? []).map((l) =>
        l.name === target.name ? { ...l, properties: [...(l.properties ?? []).filter((p) => p.name !== property.name), property] } : l,
      );
    }
    for (const edit of tagged) next = withEdit(next, edit);
    // Named by the code it writes: a node's first edit gives it its id column.
    writeSettings(next, labelOf(tagged, next));
  };
  const addNewLayer = (def: NewLayerDef) => {
    writeSettings({ ...(settings ?? {}), newLayers: [...(settings?.newLayers ?? []), def] }, `New layer ${def.name}`);
  };

  // The node and every node below it, as an automatic run takes them: the
  // map it feeds among them.
  const targets = useMemo(
    () => autoRunTargets([nodeId], flow?.nodes ?? [], flow?.edges ?? []),
    [nodeId, flow?.nodes, flow?.edges],
  );
  const below = targets.length - 1;
  const status: Record<string, string> = flow?.nodeExecStatus ?? {};
  const outOfDate = targets.filter((id) => status[id] === "stale").length;
  // Committed once the node and every node below it ran with the edits.
  const committed = targets.every((id) => status[id] === "executed");
  const running = !!flow?.isRunActive || !!flow?.serverRunActive;

  const edits = settings?.edits ?? [];

  // Undo and Redo walk the node's entries in its Provenance drawer.
  const records = provenanceGraphNodes[nodeId] ?? NO_ENTRIES;
  const current = selectedParentExecRef.current[nodeId];
  const undoTo = editable ? undoStep(records, current, code) : null;
  const redoTo = editable ? redoStep(records, current, code) : null;
  const go = (step: HistoryStep | null) => {
    if (!step || !editable) return;
    setSelectedExec(nodeId, step.current);
    setPicked([]);
    onWrite(step.code);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!editable) return;
    // A key typed in one of the node's fields is the field's.
    if (event.target !== bodyRef.current && isTypingTarget(event.target)) return;
    const mod = event.metaKey || event.ctrlKey;
    let handled = true;
    if (event.key === "Escape" && picked.length > 0) setPicked([]);
    else if (event.key === "Delete" && picked.length > 0 && removePickedRef.current?.()) setPicked([]);
    else if (mod && event.key.toLowerCase() === "z" && event.shiftKey) go(redoTo);
    else if (mod && event.key.toLowerCase() === "z") go(undoTo);
    else handled = false;
    // Handled here, the canvas neither deletes the node nor moves it.
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  };

  // The log, by the layer each edit is on.
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
      <div className={styles.commit} data-testid="interaction-commit" data-commit-state={running ? "running" : committed ? "done" : "stale"}>
        {!committed || running ? (
          <>
            {running ? null : (
              <span className={styles.commitText}>
                {below === 1 ? "The node below does not have these edits yet." : `The ${below} nodes below do not have these edits yet.`}
              </span>
            )}
            <button
              type="button"
              className={`nodrag nopan ${styles.primary}`}
              data-testid="interaction-update"
              disabled={running}
              data-tooltip={`Runs this node and the ${below} node${below === 1 ? "" : "s"} below it with the edits`}
              onClick={() => flow?.runDownstream?.([nodeId])}
            >
              {running ? "Running…" : "Commit edits"}
            </button>
          </>
        ) : (
          <span>✓ Edits committed</span>
        )}
      </div>
    ) : null;
  const editLog = (
    <section className={`nodrag nopan ${styles.log}`} data-testid="interaction-log">
      <div className={styles.logHead}>
        <span className={styles.logTitle}>Edits</span>
        <span className={styles.logCount}>{edits.length}</span>
        {edits.length > 0 ? (
          <span className={styles.hint} data-testid="interaction-counts">
            {`${edited.counts.remove} removed, ${edited.counts.set} changed`}
            {edited.counts.restore > 0 ? `, ${edited.counts.restore} restored` : ""}
          </span>
        ) : null}
        {editable ? (
          <span className={styles.history}>
            <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-undo" disabled={!undoTo} data-tooltip={`Undo (${MOD_KEY_LABEL}+Z)`} onClick={() => go(undoTo)}>
              <FontAwesomeIcon icon={faRotateLeft} aria-hidden />
              Undo
            </button>
            <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-redo" disabled={!redoTo} data-tooltip={`Redo (Shift+${MOD_KEY_LABEL}+Z)`} onClick={() => go(redoTo)}>
              <FontAwesomeIcon icon={faRotateRight} aria-hidden />
              Redo
            </button>
          </span>
        ) : null}
      </div>
      <div className={`nowheel ${styles.logBody}`} data-edit-list={edits.length}>
        {edits.length === 0 ? (
          <p className={styles.note}>{mapId ? "No edits yet. The map draws its layers as they came." : "No edits yet. The input is handed on as it came."}</p>
        ) : null}
        {logGroups.map((group) => {
          const target = workbenchLayers.find((l) => l.name === group.layer);
          return (
            <div key={group.layer || "-"}>
              {group.layer ? (
                <span className={styles.logTitle}>
                  {target?.label ?? group.layer} <span className={styles.hint}>· {target?.newLayer ? "new layer" : "edited"}</span>
                </span>
              ) : null}
              <ol className={styles.logList}>
                {group.entries.map(({ edit, index }) => (
                  <li key={`${index}:${edit.op}`} className={`${styles.logRow} ${edit.enabled === false ? styles.logOff : ""}`} data-edit-op={edit.op} data-edit-enabled={edit.enabled === false ? "false" : "true"}>
                    {editable ? (
                      <CheckboxInput
                        label={`Use edit ${index + 1}`}
                        title={edit.enabled === false ? "Switched off: the run skips it" : "Switch off, keeping it in the list"}
                        checked={edit.enabled !== false}
                        onChange={(checked) =>
                          writeSettings(withEditEnabled(settings, index, checked), `${checked ? "Switch on" : "Switch off"}: ${describeEdit(edit, keyOf(edit))}`)
                        }
                      />
                    ) : null}
                    <span className={styles.opTag} data-tone={OP_TONE[edit.op]}>
                      {OP_TAG[edit.op]}
                    </span>
                    <span className={styles.logText}>{describeEdit(edit, keyOf(edit), undefined)}</span>
                    {editable ? (
                      <button
                        type="button"
                        className={`nodrag nopan ${styles.iconButton}`}
                        aria-label={`Delete edit ${index + 1}`}
                        data-tooltip="Delete this edit"
                        onClick={() => writeSettings(withoutEdit(settings, index), `Delete: ${describeEdit(edit, keyOf(edit))}`)}
                      >
                        <FontAwesomeIcon icon={faXmark} aria-hidden />
                      </button>
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

  // Code of another shape: the node says why it cannot read it, and offers
  // nothing. A run still runs the code, and the map draws what the run hands on.
  if (unreadable) {
    return (
      <div className={`nokey nodrag nopan nowheel ${styles.body}`} data-edit-body={nodeId} data-testid="interaction-unreadable">
        <NodeEmptyState reason="code-unreadable" hint={unreadable} />
        <p className={styles.note}>A run still runs it. Put back a code from the node&apos;s Provenance to edit on the map again.</p>
        {runError ? (
          <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
            {runError}
          </p>
        ) : null}
      </div>
    );
  }

  if (mapId) {
    const mapTitle = nodeName(mapNode) || "the Autark map";
    return (
      <FieldTheme>
        <div className={`nokey nodrag nopan nowheel ${styles.body}`} data-edit-body={nodeId} data-edit-map={mapId} ref={bodyRef} tabIndex={0} onKeyDown={onKeyDown}>
          <span className={styles.connected} data-testid="interaction-connected">
            Linked to {mapTitle}
          </span>
          {layers === null ? (
            <NodeEmptyState reason="upstream-not-run" hint="Reading the layers." />
          ) : layers.length === 0 ? (
            <NodeEmptyState reason="upstream-not-run" hint="Run the nodes that feed this node to edit their layers here." />
          ) : (
            <LayerWorkbench
              layers={workbenchLayers}
              edits={edits}
              nodeLayer={ownLayer ?? null}
              writable={editable}
              picked={picked}
              setPicked={setPicked}
              onEdit={(edit, target, property) => writeOn([edit], target, property)}
              onEdits={(more, target) => writeOn(more, target)}
              onNewLayer={addNewLayer}
              removePickedRef={removePickedRef}
              surfaces={surfaces}
              circles={circles}
              incoming={live?.interactions}
              onSelection={sendSelection}
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
      </FieldTheme>
    );
  }

  // Linked to no Autark map it feeds, the node edits nothing on a map: it says
  // how to link one, and its list stays, to switch off, delete or undo.
  return (
    <FieldTheme>
      <div className={`nokey nodrag nopan nowheel ${styles.body}`} data-edit-body={nodeId} data-testid="interaction-unlinked" ref={bodyRef} tabIndex={0} onKeyDown={onKeyDown}>
        <NodeEmptyState reason="unlinked" />
        {runError ? (
          <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
            {runError}
          </p>
        ) : null}
        {editLog}
      </div>
    </FieldTheme>
  );
}
