/**
 * The right pane of the Map Edits node. With a feature selected, it holds the
 * feature's properties as the map drew them, as JSON in a field set up as a
 * grammar field is (`nodeEditorLook`). Apply writes each value that differs
 * into the node's edits (`changeFromField`), for every feature that holds the
 * selected one's id, and Remove takes those features out. With nothing
 * selected, it lists what the node holds: the ids removed, each a button that
 * puts its features back, and the ids changed, each a button that selects its
 * feature.
 *
 * Code the node cannot read gets its reason and no action. On the dashboard
 * and in a shared view, the panel only shows: the field is read-only, and
 * there is no Apply, Remove or put back.
 */
import React, { useMemo, useState } from "react";
import Editor from "@monaco-editor/react";
import { useMonacoExternalValue } from "../../hook/useMonacoExternalValue";
import { nodeEditorLook } from "../editing/nodeEditorLook";
import { NODE_EDITOR_SCROLLING } from "../editing/nodeEditorScrolling";
import {
  changeFromField,
  type ChangeValues,
  type FeatureId,
  type JsonValue,
  type MapEdits,
} from "../../utils/mapEdits/mapEdits";
import styles from "./MapEdits.module.css";

/** How many ids the Removed and Changed lines list before "and N more". */
const LISTED_IDS = 40;

/** The feature the panel shows. */
export interface SelectedFeature {
  id: FeatureId;
  /** Its row in the input's layer. */
  row: number;
  /** Its properties as the map drew them: the input's, with the node's change for its id written in. */
  shown: Record<string, JsonValue>;
  /** Its properties as the input has them. */
  original: Record<string, JsonValue>;
  /** The values the node's change for its id writes now. */
  current?: ChangeValues;
  /** How many features of the layer hold its id. */
  count: number;
}

const idKey = (id: FeatureId) => `${typeof id}:${id}`;

/** "Removed: 8 10 12 and 3 more", each id shown as *item* makes it. */
function IdLine({
  testId,
  lead,
  ids,
  item,
}: {
  testId: string;
  lead: string;
  ids: readonly FeatureId[];
  item: (id: FeatureId) => React.ReactNode;
}) {
  const more = ids.length - LISTED_IDS;
  return (
    <p className={styles.ids} data-testid={testId}>
      {lead}{" "}
      {ids.slice(0, LISTED_IDS).map((id, i) => (
        <React.Fragment key={idKey(id)}>
          {i > 0 ? " " : null}
          {item(id)}
        </React.Fragment>
      ))}
      {more > 0 ? ` and ${more} more` : null}
    </p>
  );
}

/** The selected feature's properties, and Apply. Made anew for each feature selected. */
function PropertiesField({
  selected,
  keyName,
  readOnly,
  dashboardOn,
  onApply,
}: {
  selected: SelectedFeature;
  keyName: string;
  readOnly: boolean;
  dashboardOn: boolean;
  onApply: (values: ChangeValues, written: ChangeValues) => void;
}) {
  const shownText = useMemo(() => JSON.stringify(selected.shown, null, 2), [selected.shown]);
  const [text, setText] = useState(shownText);
  // Why the last Apply wrote nothing; it goes with the next keystroke.
  const [refusal, setRefusal] = useState<string | null>(null);
  // The field is uncontrolled while someone types, as the grammar field is: a
  // run that lands meanwhile keeps their text, and only new values for the
  // feature (an Apply, a run's code put back) are written in.
  const { attachEditor } = useMonacoExternalValue({
    externalValue: shownText,
    initialContent: shownText,
    onExternalApply: (value) => {
      setText(value);
      setRefusal(null);
    },
  });
  const parsed = useMemo((): { value: unknown } | { error: string } => {
    try {
      return { value: JSON.parse(text) };
    } catch (error) {
      return { error: error instanceof Error ? error.message : String(error) };
    }
  }, [text]);
  const problem = "error" in parsed ? parsed.error : refusal;
  const look = nodeEditorLook(dashboardOn);

  const apply = () => {
    if ("error" in parsed) return;
    const change = changeFromField({
      shown: selected.shown,
      original: selected.original,
      edited: parsed.value,
      key: keyName,
      current: selected.current,
    });
    if ("problem" in change) {
      setRefusal(change.problem);
      return;
    }
    setRefusal(null);
    // An Apply that changes nothing writes nothing.
    if ("noChange" in change) return;
    onApply(change.values, change.written);
  };

  return (
    <>
      <div
        className={`nodrag nopan nowheel nokey ${styles.field}${look.wrapperClassName ? ` ${look.wrapperClassName}` : ""}`}
        data-testid="map-edits-field"
      >
        <Editor
          height="100%"
          language="json"
          theme="vs"
          defaultValue={shownText}
          onChange={(value) => {
            setText(value ?? "");
            setRefusal(null);
          }}
          onMount={(editor: any) => attachEditor(editor)}
          options={{
            fontSize: 13,
            fontFamily: "'Source Code Pro', Consolas, 'Courier New', monospace",
            minimap: { enabled: false },
            readOnly,
            scrollBeyondLastLine: false,
            formatOnType: true,
            autoClosingBrackets: "always",
            ...NODE_EDITOR_SCROLLING,
            ...look.editorOptions,
          }}
        />
      </div>
      {problem ? (
        <p className={styles.problem} data-testid="map-edits-problem">
          {problem}
        </p>
      ) : null}
      {selected.count > 1 ? (
        <p className={styles.note} data-testid="map-edits-applies-to">
          Applies to the {selected.count} features with {keyName} {String(selected.id)}
        </p>
      ) : null}
      {!readOnly ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={`nodrag nopan ${styles.button}`}
            data-testid="map-edits-apply"
            disabled={"error" in parsed}
            onClick={apply}
          >
            Apply
          </button>
        </div>
      ) : null}
    </>
  );
}

export function MapEditsPanel({
  nodeId,
  keyName,
  buildings,
  unreadable,
  edits,
  selected,
  readOnly,
  dashboardOn,
  onApply,
  onRemove,
  onPutBack,
  onShow,
}: {
  nodeId: string;
  /** The column that identifies a feature. */
  keyName: string;
  /** Whether the layer to edit holds buildings, which the hint names. */
  buildings: boolean;
  /** Why the node's code is not one it writes, or null. */
  unreadable: string | null;
  edits: MapEdits | null;
  selected: SelectedFeature | null;
  readOnly: boolean;
  dashboardOn: boolean;
  onApply: (values: ChangeValues, written: ChangeValues) => void;
  onRemove: () => void;
  onPutBack: (id: FeatureId) => void;
  onShow: (id: FeatureId) => void;
}) {
  let content: React.ReactNode;
  if (unreadable !== null || edits === null) {
    content = (
      <p className={styles.problem} data-testid="map-edits-unreadable">
        Map Edits cannot read this code, so its map draws the input as it came and the node offers no edits. The code
        still runs as it is. {unreadable}
      </p>
    );
  } else if (selected) {
    content = (
      <>
        <div className={styles.head}>
          <span className={styles.title}>
            {keyName} {String(selected.id)}
          </span>
          {!readOnly ? (
            <button
              type="button"
              className={`nodrag nopan ${styles.button}`}
              data-testid="edit-features-remove"
              title="Delete"
              onClick={onRemove}
            >
              Remove
            </button>
          ) : null}
        </div>
        <PropertiesField
          key={`${selected.row}:${idKey(selected.id)}`}
          selected={selected}
          keyName={keyName}
          readOnly={readOnly}
          dashboardOn={dashboardOn}
          onApply={onApply}
        />
      </>
    );
  } else {
    const idButton = (id: FeatureId, kind: "put-back" | "show", title: string, onClick: () => void) => (
      <button
        type="button"
        className={`nodrag nopan ${styles.id}`}
        data-map-edits-put-back={kind === "put-back" ? String(id) : undefined}
        data-map-edits-show={kind === "show" ? String(id) : undefined}
        title={title}
        onClick={onClick}
      >
        {String(id)}
      </button>
    );
    content = (
      <>
        <p className={styles.hint}>
          {buildings
            ? "Double-click a building to see and edit its OSM information."
            : "Double-click a feature to see and edit its properties."}
        </p>
        {edits.remove.length > 0 ? (
          <IdLine
            testId="map-edits-removed"
            lead="Removed:"
            ids={edits.remove}
            item={(id) => (readOnly
              ? <span>{String(id)}</span>
              : idButton(id, "put-back", `Put back ${keyName} ${String(id)}`, () => onPutBack(id)))}
          />
        ) : null}
        {edits.change.length > 0 ? (
          <IdLine
            testId="map-edits-changed"
            lead="Changed:"
            ids={edits.change.map((c) => c.id)}
            item={(id) => idButton(id, "show", `Show ${keyName} ${String(id)}`, () => onShow(id))}
          />
        ) : null}
      </>
    );
  }
  return (
    <div
      className={styles.panel}
      data-map-edits-panel={nodeId}
      data-map-edits-selected={selected && edits !== null && unreadable === null ? String(selected.id) : undefined}
    >
      {content}
    </div>
  );
}
