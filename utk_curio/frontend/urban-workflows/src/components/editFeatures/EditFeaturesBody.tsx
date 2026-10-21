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
import React, { useEffect, useMemo, useRef, useState } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { useFlowContext } from "../../providers/FlowProvider";
import { autoRunTargets } from "../../providers/flow/useAutoRun";
import { readAutkInput, autkSourcesFrom } from "../../utils/autkInput";
import type { SelectionId } from "../../utils/references/selectionTags";
import { applyEdits, type EditCounts } from "../../utils/editFeatures/applyEdits";
import {
  defaultKey,
  describeEdit,
  keyColumns,
  normalizeEditFeatures,
  withEdit,
  withEditEnabled,
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
  const [picked, setPicked] = useState<SelectionId[]>([]);
  // The entries Undo took back, the last one first to be made again.
  const [redo, setRedo] = useState<FeatureEdit[]>([]);
  const bodyRef = useRef<HTMLDivElement>(null);

  // A pick names features of one layer by one key: a new choice starts anew.
  useEffect(() => setPicked([]), [layer?.table, key]);

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
    // The linked map applies the edits to its own layers: Commit edits runs it,
    // and the nodes below it, with the node.
    () => autoRunTargets(mapId ? [nodeId, mapId] : [nodeId], flow?.nodes ?? [], flow?.edges ?? []),
    [nodeId, mapId, flow?.nodes, flow?.edges],
  );
  const below = targets.length - 1;
  const status: Record<string, string> = flow?.nodeExecStatus ?? {};
  const outOfDate = targets.filter((id) => status[id] === "stale").length;
  const running = !!flow?.isRunActive || !!flow?.serverRunActive;

  // Every edit names its layer and id column already (writeOn).
  const write = (next: EditFeaturesSettings | undefined, keepRedo = false) => {
    if (!keepRedo) setRedo([]);
    onChange(normalizeEditFeatures(next));
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


  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!writable) return;
    const target = event.target as HTMLElement;
    // A key typed in one of the node's fields is the field's.
    if (target !== bodyRef.current && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
    const mod = event.metaKey || event.ctrlKey;
    let handled = true;
    if (event.key === "Escape" && picked.length > 0) setPicked([]);
    else if (mod && event.key.toLowerCase() === "z" && event.shiftKey) redoLast();
    else if (mod && event.key.toLowerCase() === "z") undo();
    else handled = false;
    // Handled here, the canvas neither deletes the node nor moves it.
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
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
              onClick={() => flow?.runDownstream?.(mapId ? [nodeId, mapId] : [nodeId])}
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

  // Linked to no Autark map, the node edits nothing: its layers are edited on
  // the map it is linked to, so it only says how to link one.
  return (
    <div className={`nokey ${styles.body}`} data-edit-body={nodeId} data-testid="interaction-unlinked">
      <NodeEmptyState
        reason="disconnected"
        title="Link an Autark map to edit"
        hint={
          "Connect the same data nodes to an Autark map, then drag from the dot on top of this node to the dot on top of " +
          "the map. Its layers are edited on that map."
        }
      />
      {edits.length > 0 ? (
        <p className={styles.logEmpty} data-testid="interaction-kept-edits">
          {edits.length === 1 ? "1 edit is kept" : `${edits.length} edits are kept`}; link the map to see and change them.
        </p>
      ) : null}
      {runError ? (
        <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
          {runError}
        </p>
      ) : null}
    </div>
  );
}
