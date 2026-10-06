/**
 * The Edit Features node's body (#662): the layer to edit and the column that
 * identifies its features, the input drawn on a map whose features are picked
 * with a click, the actions on what is picked (Remove, Set value, Restore),
 * and the edit list, the node's setting (`utils/editFeatures/editFeatures`).
 *
 * A layer with no column that identifies its features (no `osm_id` or
 * `building_id`, and no column whose values differ in every feature) is
 * refused: a feature's place in a layer is not an id.
 */
import React, { Suspense, useEffect, useMemo, useState } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { useFlowContext } from "../../providers/FlowProvider";
import { readAutkInput, autkSourcesFrom } from "../../utils/autkInput";
import type { SelectionId } from "../../utils/references/selectionTags";
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
  withoutEdit,
  type EditFeaturesSettings,
  type EditOp,
} from "../../utils/editFeatures/editFeatures";
import styles from "./EditFeatures.module.css";

/** The map's code loads with the first layer to draw. */
const EditFeaturesMap = React.lazy(() => import("./EditFeaturesMap"));

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
}: {
  label: string;
  value: string | undefined;
  options: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
  testId: string;
}) {
  return (
    <label className={styles.field}>
      {label}
      <select
        className="nodrag nopan"
        aria-label={label}
        data-testid={testId}
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
  const [picked, setPicked] = useState<SelectionId[]>([]);
  const [column, setColumn] = useState<string | undefined>(undefined);
  const [valueText, setValueText] = useState("");
  const [valueProblem, setValueProblem] = useState<string | null>(null);

  // A pick names features of one layer by one key: a new choice starts anew.
  useEffect(() => setPicked([]), [layer?.table, key]);

  const write = (next: EditFeaturesSettings) => {
    const base: EditFeaturesSettings = { ...next, ...(key ? { key } : {}) };
    if (layer?.name) base.layer = layer.name;
    else delete base.layer;
    onChange(base);
  };

  const act = (op: EditOp) => {
    if (picked.length === 0) return;
    if (op === "set") {
      if (!column) return;
      const value = typedValue(valueText, layer?.fc, column);
      if (value === undefined) {
        setValueProblem(`${column} holds numbers; type a number.`);
        return;
      }
      setValueProblem(null);
      write(withEdit(settings, { op, ids: picked, column, value }));
    } else {
      write(withEdit(settings, { op, ids: picked }));
    }
    setPicked([]);
  };

  const onPick = (details: Record<string, any>) => {
    if (!layer || !key) return;
    const ids = pickedIds(details, layer.fc, key);
    if (ids.length > 0) setPicked((current) => addPicked(current, ids));
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
        <EditFeaturesMap nodeId={nodeId} input={input} docText={editMapDocument(layers, layer.table)} onPick={onPick} />
      </Suspense>
    );
  }

  const editable = writable && !!layer && keys.length > 0;
  return (
    <div className={styles.body} data-edit-body={nodeId}>
      {layers && layer ? (
        <div className={styles.bar}>
          {layers.length > 1 ? (
            <Select
              label="Layer"
              testId="edit-features-layer"
              value={layer.table}
              options={layers.map((l) => l.table)}
              disabled={!writable}
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
              disabled={!writable}
              onChange={(nextKey) => write({ ...(settings ?? {}), key: nextKey })}
            />
          ) : null}
        </div>
      ) : null}
      {key === "building_id" && keys.length > 0 ? (
        <p className={styles.note} data-edit-building-note="true">
          A building&apos;s parts share its building_id, so an edit applies to the whole building, every part.
        </p>
      ) : null}
      <div className={styles.stage}>{stage}</div>
      {editable ? (
        <div className={styles.actions}>
          <span className={styles.picked} data-edit-picked={picked.join(" ")}>
            {picked.length === 0
              ? "Double-click features on the map to pick them."
              : `Picked: ${key} ${picked.map(String).join(", ")}`}
          </span>
          <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="edit-features-remove" disabled={picked.length === 0} onClick={() => act("remove")}>
            Remove
          </button>
          <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="edit-features-restore" disabled={picked.length === 0} onClick={() => act("restore")}>
            Restore
          </button>
          <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="edit-features-clear" disabled={picked.length === 0} onClick={() => setPicked([])}>
            Clear pick
          </button>
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
            <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="edit-features-set" disabled={picked.length === 0 || !column} onClick={() => act("set")}>
              Set value
            </button>
          </span>
          {valueProblem ? <span className={styles.problem}>{valueProblem}</span> : null}
        </div>
      ) : null}
      {runError ? (
        <p className={`nodrag nopan ${styles.problem}`} data-edit-run-error="true">
          {runError}
        </p>
      ) : null}
      <ol className={`nodrag nopan nowheel ${styles.edits}`} data-edit-list={edits.length}>
        {edits.length === 0 ? <li className={styles.empty}>No edits yet: the input is handed on as it came.</li> : null}
        {edits.map((edit, index) => (
          <li key={`${index}:${edit.op}`} className={styles.edit} data-edit-op={edit.op}>
            <span>{describeEdit(edit, settings?.key)}</span>
            {writable ? (
              <button
                type="button"
                className={`nodrag nopan ${styles.delete}`}
                aria-label={`Delete edit ${index + 1}`}
                onClick={() => onChange(withoutEdit(settings, index))}
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
