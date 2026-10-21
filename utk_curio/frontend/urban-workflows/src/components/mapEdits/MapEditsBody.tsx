/**
 * The Map Edits node's body (its type id is still `curio.builtin/edit-features`):
 * the layer to edit and the column that identifies its features, above two
 * panes, the map on the left and the selected feature's properties on the
 * right (`MapEditsPanel`).
 *
 * The node's code is its only state. The body reads the edits from it on every
 * render (`readMapEdits`) and writes a new code for each change. The code is
 * mirrored into the node's data without a change of the flow's state, so the
 * body listens for code edits, as the Parameter node does: a run's or an
 * edit's code put back from the Provenance drawer shows its edits at once.
 *
 * The map draws the layer as the edits leave it (`applyMapEdits`). A
 * double-click on it selects the first feature the pick names, one at a time;
 * Escape clears it, and so do a Remove, a put back and a new layer or id
 * column. Delete removes the selected feature while the body, not the field,
 * has the focus.
 *
 * Code the node cannot read is never rewritten: the panel says why and offers
 * nothing, and the map draws the input as it came. A layer with no column
 * that identifies its features is refused: a feature's place in a layer is
 * not an id.
 */
import React, { Suspense, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { useFlowContext } from "../../providers/FlowProvider";
import { readAutkInput, autkSourcesFrom } from "../../utils/autkInput";
import { codeEditRevision, subscribeToCodeEdits } from "../../utils/references/codeEdits";
import {
  applyMapEdits,
  changeFor,
  changeLabel,
  isFeatureId,
  isRemoved,
  mapEditsCode,
  putBackLabel,
  readMapEdits,
  removeLabel,
  sameId,
  withChange,
  withPutBack,
  withRemoved,
  type ChangeValues,
  type FeatureId,
  type MapEdits,
  type MapFeature,
} from "../../utils/mapEdits/mapEdits";
import {
  chosenLayer,
  defaultKey,
  fieldProperties,
  keptRows,
  keyColumns,
  keyRefusal,
  mapDocument,
  mapInput,
  pickedRow,
  type InputLayer,
} from "../../utils/mapEdits/mapEditsLayers";
import { MapEditsPanel, type SelectedFeature } from "./MapEditsPanel";
import styles from "./MapEdits.module.css";

/** Why the Layer and Id menus are held while the node has edits. */
const HELD = "The edits name features of this layer by this column, so neither can change while the node holds any.";

/** The map's code loads with the first layer to draw. */
const MapEditsMap = React.lazy(() => import("./MapEditsMap"));

/** The layers of *input*, read as the Autark map reads them. */
function useInputLayers(input: unknown): InputLayer[] | null {
  const [layers, setLayers] = useState<InputLayer[] | null>(null);
  useEffect(() => {
    let current = true;
    if (input == null || input === "") {
      setLayers([]);
      return;
    }
    // The layers read last stay until the new ones come, so the map stays,
    // with its view.
    setLayers((previous) => (previous && previous.length > 0 ? previous : null));
    readAutkInput(input)
      .then((read) => {
        const named = new Set(read.frames.map((frame) => frame.name));
        const { sources } = autkSourcesFrom(read, {}, { alias: false });
        return sources.map((source) => ({
          table: source.outputTableName,
          name: named.has(source.outputTableName) ? source.outputTableName : null,
          layerType: source.layerType,
          fc: source.geojsonObject as InputLayer["fc"],
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
    <label className={styles.menu}>
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

/** A feature picked on the map: its row in the input's layer, and its id. */
type Picked = { table: string; row: number; id: FeatureId };

const NO_FEATURES: MapFeature[] = [];

export function MapEditsBody({
  nodeId,
  runError = null,
  onWrite,
}: {
  nodeId: string;
  /** Why the node's last run failed. */
  runError?: string | null;
  /** Writes *code* into the node; *label* names an edit for the node's Provenance drawer. */
  onWrite: (code: string, label?: string) => void;
}) {
  const flow = useFlowContext() as any;
  useSyncExternalStore(subscribeToCodeEdits, codeEditRevision);
  const live = (flow?.nodes ?? []).find((n: any) => n.id === nodeId)?.data;
  const input = live?.input;
  const code: string = typeof live?.code === "string" ? live.code : "";
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";
  const read = useMemo(() => readMapEdits(code), [code]);
  const edits = "edits" in read ? read.edits : null;
  const comments = "edits" in read ? read.comments : undefined;
  const unreadable = "problem" in read ? read.problem : null;

  const layers = useInputLayers(input);
  const layer = layers ? chosenLayer(layers, edits?.layer) : undefined;
  const keys = useMemo(() => (layer ? keyColumns(layer.fc) : []), [layer]);
  const key = edits?.key ?? defaultKey(keys) ?? keys[0];
  const keyOptions = key && !keys.includes(key) ? [key, ...keys] : keys;
  const features: MapFeature[] = layer?.fc.features ?? NO_FEATURES;
  // With several layers, the edits name theirs; with one, the code keeps what it says.
  const layerName = layers && layers.length > 1 ? layer?.name ?? undefined : edits?.layer;
  const held = !!edits && (edits.remove.length > 0 || edits.change.length > 0);
  const bodyRef = useRef<HTMLDivElement>(null);

  // The layer as the edits leave it, and the input row each of its rows is.
  const drawn = useMemo(() => (edits ? applyMapEdits(features, edits) : features), [features, edits]);
  const rows = useMemo(() => (edits ? keptRows(features, edits) : features.map((_, row) => row)), [features, edits]);
  const inline = useMemo(() => (layers && layer ? mapInput(layers, layer.table, drawn) : null), [layers, layer, drawn]);
  const docText = useMemo(() => (layers && layer ? mapDocument(layers, layer.table) : ""), [layers, layer]);

  const [picked, setPicked] = useState<Picked | null>(null);
  // A pick names a feature of one layer by one column: a new choice starts anew.
  useEffect(() => setPicked(null), [layer?.table, key]);

  const holdsId = (feature: MapFeature | undefined, id: FeatureId) => {
    const value = key ? feature?.properties?.[key] : undefined;
    return isFeatureId(value) && sameId(value, id);
  };

  // The feature selected, while the edits keep it: its row, or the first that
  // holds its id when the input's rows moved.
  const selected = useMemo((): SelectedFeature | null => {
    if (!picked || !edits || !key || picked.table !== layer?.table || isRemoved(edits, picked.id)) return null;
    const row = holdsId(features[picked.row], picked.id)
      ? picked.row
      : features.findIndex((feature) => holdsId(feature, picked.id));
    if (row < 0) return null;
    const feature = features[row];
    const [after] = applyMapEdits([feature], edits);
    return {
      id: picked.id,
      row,
      shown: fieldProperties(after?.properties),
      original: fieldProperties(feature?.properties),
      current: changeFor(edits, picked.id),
      count: features.filter((other) => holdsId(other, picked.id)).length,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picked, edits, key, layer, features]);

  /** Writes *next* as the node's code, keeping the comment lines the code has. */
  const writeCode = (next: MapEdits, label?: string) => {
    if (!writable || !edits) return;
    onWrite(mapEditsCode(next, comments), label);
  };
  /** Writes an edit, by the column and the layer the body shows. */
  const writeEdit = (next: MapEdits, label: string) => writeCode({ ...next, key, layer: layerName }, label);

  const remove = () => {
    if (!selected || !edits) return;
    writeEdit(withRemoved(edits, [selected.id]), removeLabel(key, [selected.id]));
    setPicked(null);
  };
  const putBack = (id: FeatureId) => {
    if (!edits) return;
    writeEdit(withPutBack(edits, id), putBackLabel(key, id));
    setPicked(null);
  };
  const apply = (values: ChangeValues, written: ChangeValues) => {
    if (!selected || !edits) return;
    writeEdit(withChange(edits, selected.id, values), changeLabel(key, selected.id, written));
  };
  const show = (id: FeatureId) => {
    const row = features.findIndex((feature) => holdsId(feature, id));
    if (layer && row >= 0) setPicked({ table: layer.table, row, id });
  };

  const onPick = (details: Record<string, any>) => {
    if (!layer || !key || !edits) return;
    const at = pickedRow(details, drawn);
    const row = at === null ? undefined : rows[at];
    const id = row === undefined ? undefined : features[row]?.properties?.[key];
    // A pick on nothing keeps the feature selected.
    if (row === undefined || !isFeatureId(id)) return;
    setPicked({ table: layer.table, row, id });
    // The keys act on the feature from here.
    bodyRef.current?.focus({ preventScroll: true });
  };

  const fieldHasKey = (target: HTMLElement) =>
    target !== bodyRef.current
    && (/^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName) || !!target.closest?.('[data-testid="map-edits-field"]'));

  const onKeyDown = (event: React.KeyboardEvent) => {
    // A key typed in the field or a menu is theirs.
    if (!selected || fieldHasKey(event.target as HTMLElement)) return;
    if (event.key === "Escape") setPicked(null);
    else if ((event.key === "Delete" || event.key === "Backspace") && writable && edits) remove();
    else return;
    // Handled here, the canvas neither deletes the node nor moves it.
    event.preventDefault();
    event.stopPropagation();
  };

  let stage: React.ReactNode;
  let editable = false;
  if (input == null || input === "") {
    stage = <NodeEmptyState reason="disconnected" hint="Connect a layer, or the layers an Autark node hands on, to edit its features." />;
  } else if (layers === null) {
    stage = <NodeEmptyState reason="not-run" hint="Reading the input." />;
  } else if (!layer) {
    stage = <NodeEmptyState reason="not-tabular" hint="The input carries no layer with features to edit." />;
  } else if (!key) {
    stage = (
      <p className={styles.problem} data-map-edits-refusal="true">
        {keyRefusal(keys, layer.name ?? "This layer")}
      </p>
    );
  } else {
    editable = true;
    stage = (
      <Suspense fallback={<NodeEmptyState reason="not-run" hint="Loading the map." />}>
        <MapEditsMap nodeId={nodeId} input={inline} docText={docText} onPick={onPick} />
      </Suspense>
    );
  }

  return (
    <div className={`nokey ${styles.body}`} data-map-edits-body={nodeId} ref={bodyRef} tabIndex={0} onKeyDown={onKeyDown}>
      {layers && layer && (layers.length > 1 || keyOptions.length > 0) ? (
        <div className={styles.bar}>
          {layers.length > 1 ? (
            <Select
              label="Layer"
              testId="edit-features-layer"
              value={layer.table}
              options={layers.map((l) => l.table)}
              disabled={!writable || !edits || held}
              title={held ? HELD : undefined}
              onChange={(table) => {
                const next = layers.find((l) => l.table === table);
                if (!next || !edits) return;
                const nextKeys = keyColumns(next.fc);
                writeCode({ ...edits, key: defaultKey(nextKeys) ?? nextKeys[0], layer: next.name ?? undefined });
              }}
            />
          ) : null}
          {keyOptions.length > 0 ? (
            <Select
              label="Id"
              testId="edit-features-key"
              value={key}
              options={keyOptions}
              disabled={!writable || !edits || held}
              title={held ? HELD : undefined}
              onChange={(nextKey) => edits && writeCode({ ...edits, key: nextKey, layer: layerName })}
            />
          ) : null}
        </div>
      ) : null}
      <div className={styles.panes}>
        <div className={styles.stage}>{stage}</div>
        {editable && key ? (
          <MapEditsPanel
            nodeId={nodeId}
            keyName={key}
            buildings={layer?.layerType === "buildings"}
            unreadable={unreadable}
            edits={edits}
            selected={selected}
            readOnly={!writable}
            dashboardOn={!!flow?.dashboardOn}
            onApply={apply}
            onRemove={remove}
            onPutBack={putBack}
            onShow={show}
          />
        ) : null}
      </div>
      {runError ? (
        <p className={`nodrag nopan ${styles.problem}`} data-map-edits-run-error="true">
          {runError}
        </p>
      ) : null}
    </div>
  );
}
