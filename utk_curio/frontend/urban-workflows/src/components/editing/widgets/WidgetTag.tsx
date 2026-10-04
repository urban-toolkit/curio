import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import { INPUT_REF_MIME, WIDGET_REF_MIME } from "./monacoCodeReferences";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";
import {
  inputReferenceInner,
  referenceText,
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

/** One input's tag, and its columns when expanded (#662). */
function InputTags({
  input,
  onInsert,
  onLoadColumns,
  disabled,
}: {
  input: InputScope;
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const columns = input.columns;
  useEffect(() => {
    if (open && columns === undefined) onLoadColumns?.(input.slot);
  }, [open, columns, input.slot]);
  const shown = (columns ?? []).filter((c) => c.toLowerCase().includes(filter.trim().toLowerCase()));
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
          {Array.isArray(columns) && columns.length === 0 ? (
            <span className={styles.stripHint}>This input has no columns.</span>
          ) : null}
          {Array.isArray(columns) && columns.length > COLUMN_FILTER_FROM ? (
            <input
              type="search"
              className={styles.columnFilter}
              placeholder="Filter columns"
              aria-label={`Filter the columns of input ${input.slot}`}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          ) : null}
          {shown.map((column) => (
            <ReferenceTag
              key={column}
              className={styles.columnTag}
              mime={INPUT_REF_MIME}
              inner={inputReferenceInner(input.slot, column)}
              text={column}
              title={input.dtypes?.[column] ? `Column of input ${input.slot}, ${input.dtypes[column]}` : `Column of input ${input.slot}`}
              dataAttributes={{ "data-column-tag": column }}
              onInsert={onInsert}
              disabled={disabled}
            />
          ))}
        </span>
      ) : null}
    </>
  );
}

/**
 * The tags above a code or grammar editor: the node's inputs, each opening to
 * its columns, then its widgets. Nothing when it has neither.
 */
export function ReferenceStrip({
  widgets,
  inputs = [],
  onInsert,
  onLoadColumns,
  disabled = false,
}: {
  widgets: WidgetDef[];
  inputs?: InputScope[];
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled?: boolean;
}) {
  if (widgets.length === 0 && inputs.length === 0) return null;
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
    </div>
  );
}

export default WidgetTag;
