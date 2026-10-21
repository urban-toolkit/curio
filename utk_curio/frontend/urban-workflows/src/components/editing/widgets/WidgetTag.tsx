import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import {
  INPUT_REF_MIME,
  SCENARIO_REF_MIME,
  SELECTION_REF_MIME,
  SHARED_REF_MIME,
  WIDGET_REF_MIME,
} from "./monacoCodeReferences";
import { STRIP_CATEGORIES, useOpenCategories, type StripCategory } from "./stripCategories";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";
import type { SelectionTag as SelectionTagDef } from "../../../utils/references/selectionTags";
import {
  SCENARIO_LISTS,
  VEGA_LITE,
  inputName,
  inputReferenceInner,
  referenceText,
  scenarioColorScale,
  scenarioInputColor,
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
  type ScenarioLabel,
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

/** What each field the stacking adds holds, for its title. */
const STACKED_FIELD_TITLES: Record<string, string> = {
  [SCENARIO_NAME_FIELD]: "text: the name of the scenario box each row's input comes from, or of its node",
  [SCENARIO_FIELD]: "text: the id of that box, empty for an input from no box",
  [INPUT_FIELD]: "number: the circle each row came in on",
};

/** Whether *inputs*, each one's label known, has one from a scenario box: then
 * the header has its Scenarios category. */
function fedFromABox(inputs: readonly InputScope[]): boolean {
  if (inputs.length === 0 || inputs.some((input) => input.scenario == null)) return false;
  return anyFromABox(inputs.map((input) => input.scenario as ScenarioLabel));
}

/**
 * The Scenarios category of a spec whose node receives an edge from a scenario
 * box (#662). In a Vega-Lite spec (*lists*): a swatch per box with its name, in
 * the order the dataflow lists the boxes, then each input from no box in a
 * grey of its own, all one chip, `[!! scenario colors !!]`, the scale of their
 * colors; then the same colors in the shades a text mark reads in,
 * `[!! scenario text_colors !!]`, and their names alone, `[!! scenario order !!]`,
 * for an axis's, an offset's or a facet's order. Then, in a Vega-Lite or an
 * Autark spec, a tag per input, `input_1 ■ Baseline`, which drags
 * `[!! scenario input_1 !!]`, the color of the box that input comes from, or its
 * grey. Each color shown is the one its chip writes (`scenarioColorScale`,
 * `scenarioInputColor`).
 */
function ScenarioChips({
  inputs,
  lists,
  onInsert,
  disabled,
}: {
  inputs: InputScope[];
  lists: boolean;
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const { domain, range } = scenarioColorScale(inputs);
  return (
    <>
      {lists ? (
        <>
          <ReferenceTag
            className={styles.swatches}
            mime={SCENARIO_REF_MIME}
            inner={scenarioReferenceInner("colors")}
            text={domain.map((name, i) => (
              <span key={name} className={styles.swatch} data-scenario-swatch={name} data-color={range[i]}>
                <SwatchColor color={range[i]} />
                {name}
              </span>
            ))}
            title={`The scenarios' colors, a color scale: ${domain.map((name, i) => `${name} ${range[i]}`).join(", ")}`}
            dataAttributes={{ "data-scenario-swatches": "true" }}
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
        </>
      ) : null}
      {inputs.map((input) => {
        const label = input.scenario as ScenarioLabel;
        const color = scenarioInputColor(input.slot, inputs);
        const name = inputName(input.slot);
        return (
          <ReferenceTag
            key={input.slot}
            className={styles.scenarioTag}
            mime={SCENARIO_REF_MIME}
            inner={scenarioInputReferenceInner(input.slot)}
            text={
              <>
                {name}
                <span className={styles.swatch} data-scenario-swatch={label.name} data-color={color}>
                  <SwatchColor color={color} />
                  {label.name}
                </span>
              </>
            }
            title={
              label.scenario != null
                ? `The color of ${label.name}, the scenario box ${name} comes from`
                : `${name}, from ${label.name}, comes from no scenario box: its grey in the scenarios' scale`
            }
            dataAttributes={{ "data-scenario-input": String(input.slot), "data-color": color }}
            onInsert={onInsert}
            disabled={disabled}
          />
        );
      })}
    </>
  );
}

/**
 * The `inputs` tag of a Vega-Lite node with an input, one or several (#662),
 * after the inputs' own: it drags the chip of the dataset that stacks every
 * input's rows, in circle order, `[!! inputs !!]`, which a spec reads as
 * `"data": {"name": "[!! inputs !!]"}`. Opened, it lists the fields its rows
 * carry, each a chip that writes its name, the three the stacking adds first,
 * then the inputs' columns (a layer's geometry left out, as the rows leave it
 * out).
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
            <ReferenceTag
              key={field}
              className={styles.columnTag}
              mime={INPUT_REF_MIME}
              inner={stackedReferenceInner(field)}
              text={field}
              title={titleOf(field)}
              dataAttributes={{ "data-inputs-field": field }}
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
 * One input's tag, and its columns when expanded (#662). An input carrying
 * several layers (an Autark node's tables) opens to a tag per layer instead,
 * each followed by that layer's columns, in code as in a Vega-Lite or Autark
 * spec.
 */
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

/** Each category's name in the header's row. */
const CATEGORY_NAMES: Record<StripCategory, string> = {
  inputs: "Inputs",
  scenarios: "Scenarios",
  widgets: "Widgets",
  selections: "Selections",
  shared: "Shared",
};

/** The attribute a category's name carries, which tests find it by. */
const CATEGORY_NAME_ATTRIBUTES: Partial<Record<StripCategory, string>> = {
  inputs: "data-input-strip",
  selections: "data-selection-strip",
  shared: "data-shared-strip",
};

/**
 * The header above a code or grammar editor (#662): every chip the node can
 * use, whatever its code or spec uses, in one row of categories, each with its
 * count and shown only when it has chips: Inputs, Scenarios, Widgets,
 * Selections and Shared. Every category starts closed; a click opens its chips
 * under the row, and another closes them. Several can be open, and one stays
 * open for its node (*nodeId*) while the dataflow is open (`stripCategories`).
 * Nothing when the node can use no chip.
 *
 * It reads the editor's *language* and *grammar* and the node's inputs, never
 * its code, so a built-in node and a package node of one grammar list the same
 * chips:
 *
 * - Inputs: a tag per input, each opening to its columns (or its layers); in a
 *   Vega-Lite spec (*grammar* `VEGA_LITE`) with an input, then the `inputs`
 *   tag, the dataset that stacks them, opening to its fields.
 * - Scenarios, in a spec (*language* `json`) whose node receives an edge from a
 *   scenario box: in a Vega-Lite spec the boxes' swatches, text colors and
 *   order, then, in a Vega-Lite or an Autark spec, a tag per input in its color
 *   (`ScenarioChips`).
 * - Widgets, Selections and Shared: the node's widgets, its selection tags and
 *   the dataflow's shared tags.
 *
 * Code shows no Scenarios and no `inputs` tag.
 */
export function ReferenceStrip({
  nodeId,
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
  /** The node whose header this is, which keeps its open categories. */
  nodeId?: string | null;
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
  const [open, toggle] = useOpenCategories(nodeId);
  const sharedNames = uniqueSharedNames(shared);
  const spec = language === "json";
  const vegaLite = spec && grammar === VEGA_LITE;
  // A spec that reads inputs stacks one input as it stacks several.
  const stacked = vegaLite && inputs.length > 0;
  const scenarios = spec && fedFromABox(inputs);
  const counts: Record<StripCategory, number> = {
    inputs: inputs.length + (stacked ? 1 : 0),
    // The swatches are one chip, then text colors and order, in Vega-Lite.
    scenarios: scenarios ? (vegaLite ? SCENARIO_LISTS.length : 0) + inputs.length : 0,
    widgets: widgets.length,
    selections: selections.length,
    shared: sharedNames.length,
  };
  const shown = STRIP_CATEGORIES.filter((category) => counts[category] > 0);
  if (shown.length === 0) return null;

  const chipsOf = (category: StripCategory): React.ReactNode => {
    switch (category) {
      case "inputs":
        return (
          <>
            {inputs.map((input) => (
              <InputTags
                key={input.slot}
                input={input}
                onInsert={onInsert}
                onLoadColumns={onLoadColumns}
                disabled={disabled}
              />
            ))}
            {stacked ? (
              <StackedTags inputs={inputs} onInsert={onInsert} onLoadColumns={onLoadColumns} disabled={disabled} />
            ) : null}
          </>
        );
      case "scenarios":
        return <ScenarioChips inputs={inputs} lists={vegaLite} onInsert={onInsert} disabled={disabled} />;
      case "widgets":
        return widgets.map((w) => <WidgetTag key={w.name} name={w.name} onInsert={onInsert} disabled={disabled} />);
      case "selections":
        return selections.map((tag) => (
          <SelectionTag key={tag.name} name={tag.name} onInsert={onInsert} disabled={disabled} />
        ));
      case "shared":
        return sharedNames.map((name) => <SharedTag key={name} name={name} onInsert={onInsert} disabled={disabled} />);
    }
  };

  return (
    <div className={styles.strip} aria-label="Reference tags" data-widget-strip="true">
      <div className={styles.categories}>
        {shown.map((category) => {
          const isOpen = open.has(category);
          const nameAttribute = CATEGORY_NAME_ATTRIBUTES[category];
          return (
            <button
              key={category}
              type="button"
              className={styles.category}
              aria-expanded={isOpen}
              aria-label={`${CATEGORY_NAMES[category]} ${counts[category]}`}
              title={`${isOpen ? "Hide" : "Show"} the ${CATEGORY_NAMES[category]} chips`}
              data-strip-category={category}
              onClick={() => toggle(category)}
            >
              <span data-strip-name="true" {...(nameAttribute ? { [nameAttribute]: "true" } : {})}>
                {CATEGORY_NAMES[category]}
              </span>
              <span className={styles.categoryCount} data-strip-count="true">
                {counts[category]}
              </span>
              <span className={styles.categoryArrow} aria-hidden="true">
                {isOpen ? "▾" : "▸"}
              </span>
            </button>
          );
        })}
      </div>
      {shown
        .filter((category) => open.has(category))
        .map((category) => (
          <div
            key={category}
            className={styles.categoryChips}
            role="group"
            aria-label={`${CATEGORY_NAMES[category]} chips`}
            data-strip-chips={category}
          >
            {chipsOf(category)}
          </div>
        ))}
    </div>
  );
}

export default WidgetTag;
