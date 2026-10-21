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

/** A chevron, pointing down on a closed list or category and up on an open one. */
function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={styles.chevron}
      data-chevron={open ? "up" : "down"}
      viewBox="0 0 10 10"
      width="10"
      height="10"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={open ? "M2 6.5 L5 3.5 L8 6.5" : "M2 3.5 L5 6.5 L8 3.5"}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * A tag that opens a list, as one pill (#662): the tag, then on its right a
 * chevron button, named for what it shows or hides (*what*: "the columns of
 * input_0"). The pill shows as pressed while its list is open.
 */
function TagPill({
  tag,
  what,
  open,
  onToggle,
}: {
  tag: React.ReactNode;
  what: string;
  open: boolean;
  onToggle: () => void;
}) {
  const name = `${open ? "Hide" : "Show"} ${what}`;
  return (
    <span className={styles.tagPill} data-tag-pill="true" data-open={open ? "true" : "false"}>
      {tag}
      <button
        type="button"
        className={styles.expand}
        aria-expanded={open}
        aria-label={name}
        title={name}
        onClick={onToggle}
      >
        <Chevron open={open} />
      </button>
    </span>
  );
}

/**
 * An open list under Inputs, below its row of tags (#662): a panel headed by
 * its tag's name (*name*: "input_0 columns"), holding its chips. *attributes*
 * name it for tests.
 */
function ListPanel({
  name,
  attributes,
  children,
}: {
  name: string;
  attributes: Record<string, string>;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.list} role="group" aria-label={name} {...attributes}>
      <span className={styles.listName} data-list-name="true">
        {name}
      </span>
      <div className={styles.listChips}>{children}</div>
    </div>
  );
}

/**
 * The fields of the dataset `inputs`, open below the Inputs row (#662): each a
 * chip that writes its name, the three the stacking adds first, then the
 * inputs' columns (a layer's geometry left out, as the rows leave it out).
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
    <ListPanel name={`${INPUTS_DATASET} fields`} attributes={{ "data-inputs-fields": "true" }}>
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
    </ListPanel>
  );
}

/**
 * An input's columns, open below the Inputs row (#662). An input carrying
 * several layers (an Autark node's tables) lists a tag per layer instead, each
 * followed by that layer's columns, in code as in a Vega-Lite or Autark spec.
 * More than `COLUMN_FILTER_FROM` of them get a filter box.
 */
function InputColumns({
  input,
  onInsert,
  disabled,
}: {
  input: InputScope;
  onInsert: (inner: string) => void;
  disabled: boolean;
}) {
  const [filter, setFilter] = useState("");
  const columns = input.columns;
  const name = inputName(input.slot);
  const layers = Array.isArray(input.layers) && input.layers.length > 0 ? input.layers : null;
  const count = layers
    ? layers.reduce((n, l) => n + 1 + (l.columns?.length ?? 0), 0)
    : (columns ?? []).length;
  return (
    <ListPanel name={`${name} ${layers ? "layers" : "columns"}`} attributes={{ "data-input-columns": String(input.slot) }}>
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
          aria-label={`Filter the columns of ${name}`}
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
                title={`Layer of ${name}`}
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
    </ListPanel>
  );
}

/** What a list under Inputs is opened by: an input's circle, or the dataset `inputs`. */
type InputList = number | typeof INPUTS_DATASET;

/**
 * The Inputs category (#662): its tags on one row, in circle order, each input
 * a pill that opens to its columns, then, in a Vega-Lite spec with an input
 * (*stacked*), the `inputs` tag, which drags the chip of the dataset that stacks
 * every input's rows, `[!! inputs !!]`, and opens to its fields. An open list
 * is a panel below the row, so the tags never move; several stack in the tags'
 * order, whatever order they were opened in. Opening one reads the columns not
 * read yet of the inputs it lists.
 */
function InputsChips({
  inputs,
  stacked,
  onInsert,
  onLoadColumns,
  disabled,
}: {
  inputs: InputScope[];
  stacked: boolean;
  onInsert: (inner: string) => void;
  onLoadColumns?: (slot: number) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState<ReadonlySet<InputList>>(() => new Set());
  const toggle = (list: InputList) =>
    setOpen((previous) => {
      const next = new Set(previous);
      if (next.has(list)) next.delete(list);
      else next.add(list);
      return next;
    });
  useEffect(() => {
    for (const input of inputs) {
      if (input.columns === undefined && (open.has(input.slot) || open.has(INPUTS_DATASET))) {
        onLoadColumns?.(input.slot);
      }
    }
  }, [open, inputs]);
  const chip = referenceText(INPUTS_DATASET);
  const fieldsOpen = stacked && open.has(INPUTS_DATASET);
  return (
    <>
      <div className={styles.tagRow} data-strip-tags="inputs">
        {inputs.map((input) => (
          <TagPill
            key={input.slot}
            what={`the columns of ${inputName(input.slot)}`}
            open={open.has(input.slot)}
            onToggle={() => toggle(input.slot)}
            tag={
              <ReferenceTag
                className={styles.inputTag}
                mime={INPUT_REF_MIME}
                inner={inputReferenceInner(input.slot)}
                text={inputName(input.slot)}
                title={input.label ? `From ${input.label}` : undefined}
                dataAttributes={{ "data-input-tag": String(input.slot) }}
                onInsert={onInsert}
                disabled={disabled}
              />
            }
          />
        ))}
        {stacked ? (
          <TagPill
            what={`the fields of ${INPUTS_DATASET}`}
            open={fieldsOpen}
            onToggle={() => toggle(INPUTS_DATASET)}
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
        ) : null}
      </div>
      {inputs
        .filter((input) => open.has(input.slot))
        .map((input) => (
          <InputColumns key={input.slot} input={input} onInsert={onInsert} disabled={disabled} />
        ))}
      {fieldsOpen ? <StackedFields inputs={inputs} onInsert={onInsert} disabled={disabled} /> : null}
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
          <InputsChips
            inputs={inputs}
            stacked={stacked}
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
              <Chevron open={isOpen} />
            </button>
          );
        })}
      </div>
      {shown
        .filter((category) => open.has(category))
        .map((category) => (
          // A category's tags are one row; Inputs stacks its open lists below
          // its row.
          <div
            key={category}
            className={category === "inputs" ? styles.categoryStack : styles.categoryChips}
            role="group"
            aria-label={`${CATEGORY_NAMES[category]} chips`}
            data-strip-chips={category}
            {...(category === "inputs" ? {} : { "data-strip-tags": category })}
          >
            {chipsOf(category)}
          </div>
        ))}
    </div>
  );
}

export default WidgetTag;
