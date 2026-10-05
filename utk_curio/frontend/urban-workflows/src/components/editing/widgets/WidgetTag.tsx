import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import { INPUT_REF_MIME, SELECTION_REF_MIME, SHARED_REF_MIME, WIDGET_REF_MIME } from "./monacoCodeReferences";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";
import type { SelectionTag as SelectionTagDef } from "../../../utils/references/selectionTags";
import {
  inputReferenceInner,
  referenceText,
  selectionReferenceInner,
  sharedReferenceInner,
  type InputScope,
} from "../../../utils/references/codeReferences";

/** One widget's tag (#662): dragged into a code editor, or clicked to insert
 * the reference at the cursor. */
export function WidgetTag({
  name,
  onInsert,
  disabled = false,
}: {
  name: string;
  onInsert?: (name: string) => void;
  disabled?: boolean;
}) {
  return (
    <ReferenceTag
      className={styles.tag}
      mime={WIDGET_REF_MIME}
      inner={name}
      text={name}
      dataAttributes={{ "data-widget-tag": name }}
      onInsert={onInsert}
      disabled={disabled}
    />
  );
}

/** A shared tag (#662): a Parameter node's widget, which any node's code can
 * name as `[!! @name !!]`. */
export function SharedTag({
  name,
  onInsert,
  disabled = false,
}: {
  name: string;
  onInsert?: (inner: string) => void;
  disabled?: boolean;
}) {
  return (
    <ReferenceTag
      className={styles.sharedTag}
      mime={SHARED_REF_MIME}
      inner={sharedReferenceInner(name)}
      text={sharedReferenceInner(name)}
      title={`The value of the Parameter node ${name}`}
      dataAttributes={{ "data-shared-tag": name }}
      onInsert={onInsert}
      disabled={disabled}
    />
  );
}

/** A selection tag (#662): the ids of the rows a view's selection picks, which
 * the node's code names as `[!! selection name !!]`. */
export function SelectionTag({
  name,
  onInsert,
  disabled = false,
}: {
  name: string;
  onInsert?: (inner: string) => void;
  disabled?: boolean;
}) {
  return (
    <ReferenceTag
      className={styles.selectionTag}
      mime={SELECTION_REF_MIME}
      inner={selectionReferenceInner(name)}
      text={selectionReferenceInner(name)}
      title="The ids of the rows selected in its view"
      dataAttributes={{ "data-selection-tag": name }}
      onInsert={onInsert}
      disabled={disabled}
    />
  );
}

/** One tag per shared name, in order: two Parameter nodes with one name are
 * one tag, whose reference reports the clash. */
export function uniqueSharedNames(shared: WidgetDef[]): string[] {
  return Array.from(new Set(shared.map((w) => w.name)));
}

/** A tag that drags (or, clicked, inserts) the reference to *inner*. */
function ReferenceTag({
  className,
  mime,
  inner,
  text,
  title,
  dataAttributes,
  onInsert,
  disabled = false,
}: {
  className: string;
  mime: string;
  inner: string;
  text: React.ReactNode;
  title?: string;
  dataAttributes: Record<string, string>;
  onInsert?: (inner: string) => void;
  disabled?: boolean;
}) {
  const how = onInsert ? "Drag into the code, or click to insert it at the cursor" : "Drag into the code";
  return (
    <span
      className={className}
      draggable={!disabled}
      role={onInsert ? "button" : undefined}
      tabIndex={onInsert ? 0 : undefined}
      title={title ? `${title}. ${how}` : how}
      {...dataAttributes}
      onDragStart={(event) => {
        event.dataTransfer.setData(mime, inner);
        event.dataTransfer.setData("text/plain", referenceText(inner));
        event.dataTransfer.effectAllowed = "copy";
        event.stopPropagation();
      }}
      onClick={() => {
        if (!disabled) onInsert?.(inner);
      }}
      onKeyDown={(event) => {
        if (!onInsert || disabled) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onInsert(inner);
        }
      }}
    >
      {text}
    </span>
  );
}

/** More columns than this get a filter box. */
const COLUMN_FILTER_FROM = 12;

/** The tags of one column list: its layer's (or its input's) columns. */
function ColumnTags({
  slot,
  columns,
  dtypes,
  layer,
  filter,
  onInsert,
  disabled,
}: {
  slot: number;
  columns: string[];
  dtypes?: Record<string, string>;
  layer?: string;
  filter: string;
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const owner = layer !== undefined ? `layer ${layer} of input ${slot}` : `input ${slot}`;
  const shown = columns.filter((c) => c.toLowerCase().includes(filter.trim().toLowerCase()));
  return (
    <>
      {shown.map((column) => (
        <ReferenceTag
          key={`${layer ?? ""}.${column}`}
          className={styles.columnTag}
          mime={INPUT_REF_MIME}
          inner={inputReferenceInner(slot, column, layer)}
          text={column}
          title={dtypes?.[column] ? `Column of ${owner}, ${dtypes[column]}` : `Column of ${owner}`}
          dataAttributes={{ "data-column-tag": column, ...(layer !== undefined ? { "data-column-layer": layer } : {}) }}
          onInsert={onInsert}
          disabled={disabled}
        />
      ))}
    </>
  );
}

/**
 * One input's tag, and its columns when expanded (#662). In a Vega-Lite or
 * Autark spec (*layerChips*), an input carrying several layers opens to a tag
 * per layer instead, each followed by that layer's columns.
 */
function InputTags({
  input,
  onInsert,
  onLoadColumns,
  layerChips,
  disabled,
}: {
  input: InputScope;
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  layerChips: boolean;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const columns = input.columns;
  useEffect(() => {
    if (open && columns === undefined) onLoadColumns?.(input.slot);
  }, [open, columns, input.slot]);
  const layers = Array.isArray(input.layers) && input.layers.length > 0 ? input.layers : null;
  const count = layers
    ? layers.reduce((n, l) => n + 1 + (l.columns?.length ?? 0), 0)
    : (columns ?? []).length;
  return (
    <>
      <ReferenceTag
        className={styles.inputTag}
        mime={INPUT_REF_MIME}
        inner={inputReferenceInner(input.slot)}
        text={`input ${input.slot}`}
        title={input.label ? `From ${input.label}` : undefined}
        dataAttributes={{ "data-input-tag": String(input.slot) }}
        onInsert={onInsert}
        disabled={disabled}
      />
      <button
        type="button"
        className={styles.expand}
        aria-expanded={open}
        aria-label={`${open ? "Hide" : "Show"} the columns of input ${input.slot}`}
        onClick={() => setOpen(!open)}
      >
        {open ? "▾" : "▸"}
      </button>
      {open ? (
        <span className={styles.columns} data-input-columns={String(input.slot)}>
          {columns === undefined ? <span className={styles.stripHint}>Reading the columns...</span> : null}
          {columns === null ? (
            <span className={styles.stripHint}>Run the node that feeds this input to see its columns.</span>
          ) : null}
          {layers && !layerChips ? (
            <span className={styles.stripHint}>
              This input carries the layers {layers.map((l) => l.name).join(", ")}.
            </span>
          ) : null}
          {!layers && Array.isArray(columns) && columns.length === 0 ? (
            <span className={styles.stripHint}>This input has no columns.</span>
          ) : null}
          {count > COLUMN_FILTER_FROM && (layerChips || !layers) ? (
            <input
              type="search"
              className={styles.columnFilter}
              placeholder="Filter columns"
              aria-label={`Filter the columns of input ${input.slot}`}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          ) : null}
          {layers && layerChips
            ? layers.map((layer) => (
                <React.Fragment key={layer.name}>
                  <ReferenceTag
                    className={styles.inputTag}
                    mime={INPUT_REF_MIME}
                    inner={inputReferenceInner(input.slot, undefined, layer.name)}
                    text={layer.name}
                    title={`Layer of input ${input.slot}`}
                    dataAttributes={{ "data-layer-tag": layer.name }}
                    onInsert={onInsert}
                    disabled={disabled}
                  />
                  <ColumnTags
                    slot={input.slot}
                    columns={layer.columns ?? []}
                    dtypes={layer.dtypes}
                    layer={layer.name}
                    filter={filter}
                    onInsert={onInsert}
                    disabled={disabled}
                  />
                </React.Fragment>
              ))
            : null}
          {!layers ? (
            <ColumnTags
              slot={input.slot}
              columns={columns ?? []}
              dtypes={input.dtypes}
              filter={filter}
              onInsert={onInsert}
              disabled={disabled}
            />
          ) : null}
        </span>
      ) : null}
    </>
  );
}

/**
 * The tags above a code or grammar editor: the node's inputs, each opening to
 * its columns (or, with *layerChips*, its layers), then its widgets, then its
 * selection tags, then the dataflow's shared tags. Nothing when there are none.
 */
export function ReferenceStrip({
  widgets,
  inputs = [],
  shared = [],
  selections = [],
  onInsert,
  onLoadColumns,
  layerChips = false,
  disabled = false,
}: {
  widgets: WidgetDef[];
  inputs?: InputScope[];
  shared?: WidgetDef[];
  selections?: SelectionTagDef[];
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  layerChips?: boolean;
  disabled?: boolean;
}) {
  const sharedNames = uniqueSharedNames(shared);
  if (widgets.length === 0 && inputs.length === 0 && sharedNames.length === 0 && selections.length === 0) {
    return null;
  }
  return (
    <div className={styles.strip} aria-label="Reference tags" data-widget-strip="true">
      {inputs.length > 0 ? (
        <>
          <span className={styles.stripHint} data-input-strip="true">Inputs</span>
          {inputs.map((input) => (
            <InputTags
              key={input.slot}
              input={input}
              onInsert={onInsert}
              onLoadColumns={onLoadColumns}
              layerChips={layerChips}
              disabled={disabled}
            />
          ))}
        </>
      ) : null}
      {widgets.length > 0 ? (
        <>
          <span className={styles.stripHint}>Widgets</span>
          {widgets.map((w) => (
            <WidgetTag key={w.name} name={w.name} onInsert={onInsert} disabled={disabled} />
          ))}
        </>
      ) : null}
      {selections.length > 0 ? (
        <>
          <span className={styles.stripHint} data-selection-strip="true">Selections</span>
          {selections.map((tag) => (
            <SelectionTag key={tag.name} name={tag.name} onInsert={onInsert} disabled={disabled} />
          ))}
        </>
      ) : null}
      {sharedNames.length > 0 ? (
        <>
          <span className={styles.stripHint} data-shared-strip="true">Shared</span>
          {sharedNames.map((name) => (
            <SharedTag key={name} name={name} onInsert={onInsert} disabled={disabled} />
          ))}
        </>
      ) : null}
    </div>
  );
}

export default WidgetTag;
