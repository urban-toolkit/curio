import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import {
  INPUT_REF_MIME,
  SCENARIO_REF_MIME,
  SELECTION_REF_MIME,
  SHARED_REF_MIME,
  WIDGET_REF_MIME,
} from "./monacoCodeReferences";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";
import type { SelectionTag as SelectionTagDef } from "../../../utils/references/selectionTags";
import {
  VEGA_LITE,
  inputReferenceInner,
  referenceText,
  scenarioInputReferenceInner,
  scenarioReferenceInner,
  selectionReferenceInner,
  sharedReferenceInner,
  stackedFields,
  stackedReferenceInner,
  type CodeLanguage,
  type InputScope,
} from "../../../utils/references/codeReferences";
import {
  SCENARIO_FIELD,
  SCENARIO_NAME_FIELD,
  anyFromABox,
  scaleLabels,
  scenarioScale,
} from "../../../utils/scenarios/scenarioColors";
import { INPUT_FIELD } from "../../../utils/scenarios/stackedInputs";
import { INPUTS_DATASET } from "../../../utils/vegaDatasets";

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
  const owner = layer !== undefined ? `layer ${layer} of input_${slot}` : `input_${slot}`;
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

/** A square of *color*, as a swatch shows a scenario's. */
function SwatchColor({ color }: { color: string }) {
  return <span className={styles.swatchColor} style={{ background: color }} />;
}

/**
 * The swatch of the box an input comes from, on its tag in a spec (#662): it
 * drags the input's scenario chip, `[!! scenario input_1 !!]`, which writes
 * that box's color, as a map's layer or a chart's mark takes it.
 */
function InputSwatch({
  input,
  onInsert,
  disabled,
}: {
  input: InputScope;
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const label = input.scenario;
  if (label?.scenario == null) return null;
  return (
    <ReferenceTag
      className={styles.inputSwatch}
      mime={SCENARIO_REF_MIME}
      inner={scenarioInputReferenceInner(input.slot)}
      text={<SwatchColor color={label.color} />}
      title={`The color of ${label.name}, the scenario box input_${input.slot} comes from`}
      dataAttributes={{ "data-input-swatch": String(input.slot), "data-color": label.color }}
      onInsert={onInsert}
      disabled={disabled}
    />
  );
}

/** What each field the stacking adds holds, for its title. */
const STACKED_FIELD_TITLES: Record<string, string> = {
  [SCENARIO_NAME_FIELD]: "text: the name of the scenario box each row's input comes from, or of its node",
  [SCENARIO_FIELD]: "text: the id of that box, empty for an input from no box",
  [INPUT_FIELD]: "number: the circle each row came in on",
};

/**
 * The scenarios of a node's inputs, on the `scenario_name` field of inputs
 * (#662): a swatch per box with its name, in the order the dataflow lists the
 * boxes, then each input from no box in a grey of its own. The swatches are
 * one chip, `[!! scenario colors !!]`, the scale of their colors. With no input
 * from a box the chip writes the names alone, which the grammar's own palette
 * colors, and the names show with no swatch. Two small tags beside them drag
 * their names alone, `[!! scenario order !!]`, for an axis's or an offset's
 * order, and their colors in the shades a text mark reads in,
 * `[!! scenario text_colors !!]`.
 */
function ScenarioSwatches({
  inputs,
  onInsert,
  disabled,
}: {
  inputs: InputScope[];
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const labels = inputs.flatMap((input) => (input.scenario ? [input.scenario] : []));
  const { domain, range } = scenarioScale(scaleLabels(labels));
  if (domain.length === 0) return null;
  const colored = anyFromABox(labels);
  const title = colored
    ? `The scenarios' colors, a color scale: ${domain.map((name, i) => `${name} ${range[i]}`).join(", ")}`
    : `The scenarios' names, ${domain.join(", ")}: no input comes from a box, so the chip writes the names alone `
      + "and the grammar's own palette colors them";
  return (
    <>
      <ReferenceTag
        className={styles.swatches}
        mime={SCENARIO_REF_MIME}
        inner={scenarioReferenceInner("colors")}
        text={domain.map((name, i) => (
          <span key={name} className={styles.swatch} data-scenario-swatch={name} data-color={colored ? range[i] : undefined}>
            {colored ? <SwatchColor color={range[i]} /> : null}
            {name}
          </span>
        ))}
        title={title}
        dataAttributes={{ "data-scenario-swatches": "true" }}
        onInsert={onInsert}
        disabled={disabled}
      />
      <ReferenceTag
        className={styles.scenarioTag}
        mime={SCENARIO_REF_MIME}
        inner={scenarioReferenceInner("order")}
        text="order"
        title="The scenarios' names in the order of their boxes, for an axis's, an offset's or a facet's sort"
        dataAttributes={{ "data-scenario-chip": "order" }}
        onInsert={onInsert}
        disabled={disabled}
      />
      <ReferenceTag
        className={styles.scenarioTag}
        mime={SCENARIO_REF_MIME}
        inner={scenarioReferenceInner("text_colors")}
        text="text colors"
        title="The scenarios' colors in shades that read on white, a color scale for a text mark"
        dataAttributes={{ "data-scenario-chip": "text_colors" }}
        onInsert={onInsert}
        disabled={disabled}
      />
    </>
  );
}

/**
 * The `inputs` tag of a Vega-Lite node with an input, one or several (#662),
 * beside the inputs' own: it drags the chip of the dataset that stacks every
 * input's rows, in circle order, `[!! inputs !!]`, which a spec reads as
 * `"data": {"name": "[!! inputs !!]"}`. Opened, it lists the fields its rows
 * carry, each a chip that writes its name, the three the stacking adds first,
 * then the inputs' columns (a layer's geometry left out, as the rows leave it
 * out). Its `scenario_name` field shows the scenarios' swatches.
 */
function StackedTags({
  inputs,
  onInsert,
  onLoadColumns,
  disabled,
}: {
  inputs: InputScope[];
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    for (const input of inputs) if (input.columns === undefined) onLoadColumns?.(input.slot);
  }, [open, inputs]);
  const { fields, dtypes } = stackedFields(inputs);
  const titleOf = (field: string) =>
    `Field of inputs, ${STACKED_FIELD_TITLES[field] ?? dtypes[field] ?? "a column of its inputs"}`;
  const chip = referenceText(INPUTS_DATASET);
  return (
    <>
      <ReferenceTag
        className={styles.inputTag}
        mime={INPUT_REF_MIME}
        inner={INPUTS_DATASET}
        text={INPUTS_DATASET}
        title={`The dataset ${chip}: every input's rows, stacked in circle order, as a spec reads them in "data": {"name": "${chip}"}`}
        dataAttributes={{ "data-inputs-tag": "true" }}
        onInsert={onInsert}
        disabled={disabled}
      />
      <button
        type="button"
        className={styles.expand}
        aria-expanded={open}
        aria-label={`${open ? "Hide" : "Show"} the fields of inputs`}
        onClick={() => setOpen(!open)}
      >
        {open ? "▾" : "▸"}
      </button>
      {open ? (
        <span className={styles.columns} data-inputs-fields="true">
          {fields.map((field) => (
            <React.Fragment key={field}>
              <ReferenceTag
                className={styles.columnTag}
                mime={INPUT_REF_MIME}
                inner={stackedReferenceInner(field)}
                text={field}
                title={titleOf(field)}
                dataAttributes={{ "data-inputs-field": field }}
                onInsert={onInsert}
                disabled={disabled}
              />
              {field === SCENARIO_NAME_FIELD ? (
                <ScenarioSwatches inputs={inputs} onInsert={onInsert} disabled={disabled} />
              ) : null}
            </React.Fragment>
          ))}
        </span>
      ) : null}
    </>
  );
}

/**
 * One input's tag, and its columns when expanded (#662). An input carrying
 * several layers (an Autark node's tables) opens to a tag per layer instead,
 * each followed by that layer's columns, in code as in a Vega-Lite or Autark
 * spec. In a spec, an input whose feeding node is in a scenario box shows that
 * box's swatch.
 */
function InputTags({
  input,
  onInsert,
  onLoadColumns,
  disabled,
  swatch,
}: {
  input: InputScope;
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled: boolean;
  swatch: boolean;
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
        text={`input_${input.slot}`}
        title={input.label ? `From ${input.label}` : undefined}
        dataAttributes={{ "data-input-tag": String(input.slot) }}
        onInsert={onInsert}
        disabled={disabled}
      />
      {swatch ? <InputSwatch input={input} onInsert={onInsert} disabled={disabled} /> : null}
      <button
        type="button"
        className={styles.expand}
        aria-expanded={open}
        aria-label={`${open ? "Hide" : "Show"} the columns of input_${input.slot}`}
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
          {!layers && Array.isArray(columns) && columns.length === 0 ? (
            <span className={styles.stripHint}>This input has no columns.</span>
          ) : null}
          {count > COLUMN_FILTER_FROM ? (
            <input
              type="search"
              className={styles.columnFilter}
              placeholder="Filter columns"
              aria-label={`Filter the columns of input_${input.slot}`}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          ) : null}
          {layers
            ? layers.map((layer) => (
                <React.Fragment key={layer.name}>
                  <ReferenceTag
                    className={styles.inputTag}
                    mime={INPUT_REF_MIME}
                    inner={inputReferenceInner(input.slot, undefined, layer.name)}
                    text={layer.name}
                    title={`Layer of input_${input.slot}`}
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
 * its columns (or its layers), then its widgets, then its selection tags, then
 * the dataflow's shared tags. Nothing when there are none.
 *
 * In a spec (*language* `json`), an input from a scenario box shows its box's
 * swatch; a Vega-Lite spec (*grammar* `VEGA_LITE`) with an input has the
 * `inputs` tag too, the dataset that stacks them. Code shows neither.
 */
export function ReferenceStrip({
  widgets,
  inputs = [],
  shared = [],
  selections = [],
  language,
  grammar,
  onInsert,
  onLoadColumns,
  disabled = false,
}: {
  widgets: WidgetDef[];
  inputs?: InputScope[];
  shared?: WidgetDef[];
  selections?: SelectionTagDef[];
  /** The editor's language: a spec's chips are `json`. */
  language?: CodeLanguage;
  /** A spec's grammar, as the editor resolves its chips (`VEGA_LITE`). */
  grammar?: string | null;
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled?: boolean;
}) {
  const sharedNames = uniqueSharedNames(shared);
  if (widgets.length === 0 && inputs.length === 0 && sharedNames.length === 0 && selections.length === 0) {
    return null;
  }
  const spec = language === "json";
  // A spec that reads inputs stacks one input as it stacks several.
  const stacked = grammar === VEGA_LITE && inputs.length > 0;
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
              swatch={spec}
            />
          ))}
          {stacked ? (
            <StackedTags inputs={inputs} onInsert={onInsert} onLoadColumns={onLoadColumns} disabled={disabled} />
          ) : null}
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
