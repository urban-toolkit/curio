import React, { useEffect } from "react";
import styles from "./WidgetTags.module.css";
import {
  INPUT_REF_MIME,
  SCENARIO_REF_MIME,
  SELECTION_REF_MIME,
  SHARED_REF_MIME,
  WIDGET_REF_MIME,
  inWords,
} from "./monacoCodeReferences";
import { STRIP_CATEGORIES, useOpenCategories, useOpenLists, type StripCategory } from "./stripCategories";
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
  type LayerScope,
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

/** A tag that drags (or, clicked, inserts) the reference to *inner*. *label*
 * names it for a screen reader when its text runs words together, as a name
 * beside a swatch does. */
function ReferenceTag({
  className,
  mime,
  inner,
  text,
  label,
  title,
  dataAttributes,
  onInsert,
  disabled = false,
}: {
  className: string;
  mime: string;
  inner: string;
  text: React.ReactNode;
  label?: string;
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
      aria-label={label}
      data-tooltip={title ? `${title}. ${how}` : how}
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

/** The tags of one column list: its layer's (or its input's) columns, every one of them. */
function ColumnTags({
  slot,
  columns,
  dtypes,
  layer,
  onInsert,
  disabled,
}: {
  slot: number;
  columns: string[];
  dtypes?: Record<string, string>;
  layer?: string;
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const owner = layer !== undefined ? `layer ${layer} of input_${slot}` : `input_${slot}`;
  return (
    <>
      {columns.map((column) => (
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
            label={`colors: ${domain.join(", ")}`}
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
            label={`${name}, ${label.name}`}
            title={
              label.scenario != null
                ? `The color of ${label.name}, the scenario box ${name} comes from`
                : `${name}, from ${label.name}, comes from no scenario box: its gray in the scenarios' scale`
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

/** Where a chevron points: right on a closed line's expander and down on an
 * open one; down on a closed category and up on an open one. */
type ChevronDirection = "right" | "down" | "up";

const CHEVRON_PATHS: Record<ChevronDirection, string> = {
  right: "M3.5 2 L6.5 5 L3.5 8",
  down: "M2 3.5 L5 6.5 L8 3.5",
  up: "M2 6.5 L5 3.5 L8 6.5",
};

/** A chevron, pointing *points*. */
function Chevron({ points }: { points: ChevronDirection }) {
  return (
    <svg
      className={styles.chevron}
      data-chevron={points}
      viewBox="0 0 10 10"
      width="10"
      height="10"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={CHEVRON_PATHS[points]}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** *n* things, as a line counts them: "1 column", "5 columns". */
function countOf(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The layers *input* carries, or null when it carries none. */
function layersOf(input: InputScope): LayerScope[] | null {
  return Array.isArray(input.layers) && input.layers.length > 0 ? input.layers : null;
}

/** How much *input* holds, once its columns are read: "5 columns", "no
 * columns", "5 layers", "2 values, a tuple". Null before. */
function heldBy(input: InputScope): string | null {
  if (input.tuple) return `${countOf(input.tuple, "value", "values")}, a tuple`;
  const layers = layersOf(input);
  if (layers) return countOf(layers.length, "layer", "layers");
  if (!Array.isArray(input.columns)) return null;
  return input.columns.length > 0 ? countOf(input.columns.length, "column", "columns") : "no columns";
}

/** What keeps an input's list open: the edge that feeds it, so the list stays
 * with its input when the circles above it close up and goes with its edge,
 * else its circle. */
function listKeyOf(input: InputScope): string {
  return input.edge ? `edge ${input.edge}` : `circle ${input.slot}`;
}

/**
 * What an input's line says it holds: where it comes from, the scenario box
 * its node is in, else the type of that node (its label), then how much it
 * holds once its columns are read. "from Existing: 5 columns", "from Data
 * Loading".
 */
function aboutInput(input: InputScope): string {
  const source = input.scenario?.scenario != null ? input.scenario.name : input.label;
  return [source ? `from ${source}` : null, heldBy(input)].filter(Boolean).join(": ");
}

/**
 * What the line of `inputs` says it holds: the inputs it stacks, then, once
 * every input's columns are read, how many fields its rows carry
 * (`stackedFields`). "input_0 and input_1, stacked: 8 fields".
 */
function aboutStacked(inputs: InputScope[]): string {
  const stacks = `${inWords(inputs.map((input) => inputName(input.slot)))}, stacked`;
  if (!inputs.every((input) => Array.isArray(input.columns))) return stacks;
  return `${stacks}: ${countOf(stackedFields(inputs).fields.length, "field", "fields")}`;
}

/**
 * A line under Inputs (#662): an expander, the input's tag, then what the
 * input holds (*about*). The expander is a square button whose chevron points
 * right while its list is closed and down while it is open, named for what it
 * shows or hides (*what*: "the columns of input_0"). The list comes after the
 * line, never in it. *attributes* name the line for tests.
 */
function InputLine({
  tag,
  about,
  what,
  open,
  onToggle,
  attributes,
}: {
  tag: React.ReactNode;
  about: string;
  what: string;
  open: boolean;
  onToggle: () => void;
  attributes: Record<string, string>;
}) {
  const name = `${open ? "Hide" : "Show"} ${what}`;
  return (
    <div className={styles.inputLine} {...attributes}>
      <button
        type="button"
        className={styles.expand}
        aria-expanded={open}
        aria-label={name}
        data-tooltip={name}
        onClick={onToggle}
      >
        <Chevron points={open ? "down" : "right"} />
      </button>
      {tag}
      <span className={styles.inputAbout} data-tooltip={about} data-input-about="true">
        {about}
      </span>
    </div>
  );
}

/**
 * An open list under Inputs (#662), under its line and past its expander: a
 * group named *name* ("input_0 columns"). *attributes* name it for tests.
 */
function InputList({
  name,
  attributes,
  children,
}: {
  name: string;
  attributes: Record<string, string>;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.inputList} role="group" aria-label={name} {...attributes}>
      {children}
    </div>
  );
}

/**
 * The fields of the dataset `inputs`, open under its line (#662): each a chip
 * that writes its name, the three the stacking adds first, then the inputs'
 * columns (a layer's geometry left out, as the rows leave it out).
 */
function StackedFields({
  inputs,
  onInsert,
  disabled,
}: {
  inputs: InputScope[];
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const { fields, dtypes } = stackedFields(inputs);
  const titleOf = (field: string) =>
    `Field of inputs, ${STACKED_FIELD_TITLES[field] ?? dtypes[field] ?? "a column of its inputs"}`;
  return (
    <InputList name={`${INPUTS_DATASET} fields`} attributes={{ "data-inputs-fields": "true" }}>
      <div className={styles.listChips}>
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
      </div>
    </InputList>
  );
}

/**
 * An input's list, open under its line (#662), in code as in a Vega-Lite or
 * Autark spec: every one of its columns. An input carrying several layers (an
 * Autark node's tables) lists a line per layer instead, its tag and then its
 * columns, the layers' tags in one column. A tuple's list says how to read its
 * values, in code (*code*) by their place in it.
 */
function InputColumns({
  input,
  code,
  onInsert,
  disabled,
}: {
  input: InputScope;
  code: boolean;
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const columns = input.columns;
  const name = inputName(input.slot);
  const layers = layersOf(input);
  const tuple = input.tuple;
  const values = tuple ? Array.from({ length: tuple }, (_, i) => `${name}[${i}]`) : [];
  // The input's own columns: neither layers nor a tuple's values.
  const flat = !tuple && !layers && Array.isArray(columns) ? columns : null;
  return (
    <InputList
      name={`${name} ${tuple ? "values" : layers ? "layers" : "columns"}`}
      attributes={{ "data-input-columns": String(input.slot) }}
    >
      {columns === undefined ? <span className={styles.stripHint}>Reading the columns...</span> : null}
      {columns === null ? (
        <span className={styles.stripHint}>Run the node that feeds this input to see its columns.</span>
      ) : null}
      {tuple ? (
        <span className={styles.stripHint}>
          {code
            ? `Read them in code as ${inWords(values)}.`
            : `It holds ${countOf(tuple, "value", "values")}, a tuple.`}
        </span>
      ) : null}
      {flat && flat.length === 0 ? <span className={styles.stripHint}>This input has no columns.</span> : null}
      {layers ? (
        <div className={styles.layers}>
          {layers.map((layer) => (
            <div key={layer.name} className={styles.layerLine} data-layer-line={layer.name}>
              <ReferenceTag
                className={styles.layerTag}
                mime={INPUT_REF_MIME}
                inner={inputReferenceInner(input.slot, undefined, layer.name)}
                text={layer.name}
                title={`Layer of ${name}`}
                dataAttributes={{ "data-layer-tag": layer.name }}
                onInsert={onInsert}
                disabled={disabled}
              />
              {(layer.columns ?? []).length > 0 ? (
                <div className={styles.listChips}>
                  <ColumnTags
                    slot={input.slot}
                    columns={layer.columns ?? []}
                    dtypes={layer.dtypes}
                    layer={layer.name}
                    onInsert={onInsert}
                    disabled={disabled}
                  />
                </div>
              ) : (
                <span className={styles.layerEmpty}>no columns</span>
              )}
            </div>
          ))}
        </div>
      ) : null}
      {flat && flat.length > 0 ? (
        <div className={styles.listChips}>
          <ColumnTags slot={input.slot} columns={flat} dtypes={input.dtypes} onInsert={onInsert} disabled={disabled} />
        </div>
      ) : null}
    </InputList>
  );
}

/**
 * The Inputs category (#662): a line per input, in circle order, then, in a
 * Vega-Lite spec with an input (*stacked*), the line of `inputs`, whose tag
 * drags the chip of the dataset that stacks every input's rows,
 * `[!! inputs !!]`. A line's expander opens its list right under it, and the
 * lines below move down: an input's columns, its layers or how to read its
 * tuple (*code*: in code), or the fields of `inputs`. Several can be open, and
 * each stays open for its node (*nodeId*) while the dataflow is open
 * (`stripCategories`), with the edge that feeds its input (`listKeyOf`). Open,
 * Inputs reads the columns not read yet of every input, so each line shows
 * what its input holds.
 */
function InputsChips({
  nodeId,
  inputs,
  stacked,
  code,
  onInsert,
  onLoadColumns,
  disabled,
}: {
  nodeId?: string | null;
  inputs: InputScope[];
  stacked: boolean;
  code: boolean;
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled: boolean;
}) {
  const [open, toggle] = useOpenLists(nodeId);
  useEffect(() => {
    for (const input of inputs) if (input.columns === undefined) onLoadColumns?.(input.slot);
  }, [inputs, onLoadColumns]);
  const chip = referenceText(INPUTS_DATASET);
  const fieldsOpen = stacked && open.has(INPUTS_DATASET);
  return (
    <>
      {inputs.map((input) => {
        const circle = String(input.slot);
        const list = listKeyOf(input);
        const name = inputName(input.slot);
        return (
          <React.Fragment key={input.slot}>
            <InputLine
              what={`the columns of ${name}`}
              about={aboutInput(input)}
              open={open.has(list)}
              onToggle={() => toggle(list)}
              attributes={{ "data-input-line": circle }}
              tag={
                <ReferenceTag
                  className={styles.inputTag}
                  mime={INPUT_REF_MIME}
                  inner={inputReferenceInner(input.slot)}
                  text={name}
                  title={input.label ? `From ${input.label}` : undefined}
                  dataAttributes={{ "data-input-tag": circle }}
                  onInsert={onInsert}
                  disabled={disabled}
                />
              }
            />
            {open.has(list) ? <InputColumns input={input} code={code} onInsert={onInsert} disabled={disabled} /> : null}
          </React.Fragment>
        );
      })}
      {stacked ? (
        <>
          <InputLine
            what={`the fields of ${INPUTS_DATASET}`}
            about={aboutStacked(inputs)}
            open={fieldsOpen}
            onToggle={() => toggle(INPUTS_DATASET)}
            attributes={{ "data-inputs-line": "true" }}
            tag={
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
            }
          />
          {fieldsOpen ? <StackedFields inputs={inputs} onInsert={onInsert} disabled={disabled} /> : null}
        </>
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
 * On the canvas the header takes at most half its editor's height, and the
 * open chips scroll inside it. Nothing when the node can use no chip.
 *
 * It reads the editor's *language* and *grammar* and the node's inputs, never
 * its code, so a built-in node and a package node of one grammar list the same
 * chips:
 *
 * - Inputs: a line per input, its tag and what it holds, each opening to its
 *   columns (or its layers, or how to read its tuple) under it; in a Vega-Lite
 *   spec (*grammar* `VEGA_LITE`) with an input, then the line of `inputs`, the
 *   dataset that stacks them, opening to its fields (`InputsChips`).
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
  /** The node whose header this is, which keeps its open categories and lists. */
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
  const opened = shown.filter((category) => open.has(category));

  const chipsOf = (category: StripCategory): React.ReactNode => {
    switch (category) {
      case "inputs":
        return (
          <InputsChips
            nodeId={nodeId}
            inputs={inputs}
            stacked={stacked}
            code={!spec}
            onInsert={onInsert}
            onLoadColumns={onLoadColumns}
            disabled={disabled}
          />
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
              data-tooltip={`${isOpen ? "Hide" : "Show"} the ${CATEGORY_NAMES[category]} chips`}
              data-strip-category={category}
              onClick={() => toggle(category)}
            >
              <span data-strip-name="true" {...(nameAttribute ? { [nameAttribute]: "true" } : {})}>
                {CATEGORY_NAMES[category]}
              </span>
              <span className={styles.categoryCount} data-strip-count="true">
                {counts[category]}
              </span>
              <Chevron points={isOpen ? "up" : "down"} />
            </button>
          );
        })}
      </div>
      {opened.length > 0 ? (
        // The open categories' chips, which scroll when the header is as tall
        // as it gets.
        <div className={styles.stripOpen}>
          {opened.map((category) => (
            // A category's tags are one row; Inputs is a line per input, each
            // open list under its line.
            <div
              key={category}
              className={category === "inputs" ? styles.categoryStack : styles.categoryChips}
              role="group"
              aria-label={`${CATEGORY_NAMES[category]} chips`}
              data-strip-chips={category}
            >
              {chipsOf(category)}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default WidgetTag;
