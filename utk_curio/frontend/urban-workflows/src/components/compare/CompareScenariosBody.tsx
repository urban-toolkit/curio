/**
 * The Compare Scenarios node's body (#662), its output pane: the warnings, the
 * Chart tab (its settings and the chart of the stacked table) or, in
 * Difference, the Difference tab (its settings and the map of the difference),
 * and the What differs tab. Read from the live graph, so a renamed scenario, a
 * new widget value or an edited line shows at once; the chart and the map
 * redraw when the node runs.
 */
import React, { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useFlowContext } from "../../providers/FlowProvider";
import NodeEmptyState from "../nodes/NodeEmptyState";
import { readGrammarInput, type GrammarInput } from "../../utils/grammarInput";
import { toRows } from "../../utils/rowSource";
import { codeEditRevision, subscribeToCodeEdits } from "../../utils/references/codeEdits";
import type { ClassifiedColumn } from "../../utils/starterSpec";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import { compareInputs, labelWarnings } from "../../utils/compare/compareInputs";
import {
  AGGREGATE_LABELS,
  PRESET_FIELDS,
  PRESET_LABELS,
  chartColumns,
  compareChartSpec,
  resolveChart,
} from "../../utils/compare/comparePresets";
import {
  COMPARE_AGGREGATES,
  COMPARE_MODES,
  COMPARE_PRESETS,
  normalizeCompareSettings,
  type CompareAggregate,
  type CompareChart as ChartSettings,
  type CompareDifference as DifferenceSettings,
  type CompareMode,
  type ComparePreset,
} from "../../utils/compare/compareSettings";
import { inputKinds, resolveMode } from "../../utils/compare/compareMode";
import { comparedScenarios, contextWarnings, whatDiffers } from "../../utils/compare/whatDiffers";
import { CompareChart } from "./CompareChart";
import { CompareDifference } from "./CompareDifference";
import { WhatDiffersList } from "./WhatDiffersList";
import styles from "./CompareScenarios.module.css";

const LABEL = "Compare Scenarios";

const MODE_LABELS: Record<CompareMode, string> = { chart: "Chart", difference: "Difference" };

/** The node's output as the reference a chart reads, or null before a run. */
function stackedRef(raw: unknown): { path: string; dataType?: string } | null {
  if (typeof raw === "string") return raw.trim() ? { path: raw.trim() } : null;
  if (!raw || typeof raw !== "object") return null;
  const r = raw as { path?: unknown; dataType?: unknown };
  if (typeof r.path !== "string" || !r.path.trim()) return null;
  return typeof r.dataType === "string" ? { path: r.path, dataType: r.dataType } : { path: r.path };
}

type StackedRef = { path: string; dataType?: string };

function columnsOf(read: GrammarInput): { columns: ClassifiedColumn[]; dataType: string } | null {
  const frame = read.frames[0];
  if (!frame) return null;
  const rows =
    frame.dataType === "geodataframe"
      ? (frame.payload?.features ?? []).map((f: any) => f?.properties ?? {})
      : toRows({ data: frame.payload });
  return { columns: chartColumns(frame.schema, rows, frame.geometryName), dataType: frame.dataType };
}

/**
 * The latest stacked table whose columns have been read, with them: from its
 * 100-row preview, else from the whole table. The chart draws this pair, so a
 * spec is never compiled against a table it was not made for; while a new
 * output is read, the chart keeps the last one. A restored output names its
 * file alone, so the reference takes the type the read found.
 */
function useStackedRead(stacked: StackedRef | null): { ref: StackedRef; columns: ClassifiedColumn[] } | null {
  const [read, setRead] = useState<{ ref: StackedRef; columns: ClassifiedColumn[] } | null>(null);
  useEffect(() => {
    if (!stacked) {
      setRead(null);
      return;
    }
    let current = true;
    const attempt = (preview: boolean) =>
      readGrammarInput(stacked, { label: LABEL, preview }).then(columnsOf, () => null);
    void attempt(true)
      .then((found) => found ?? attempt(false))
      .then((found) => {
        if (!current) return;
        const dataType = stacked.dataType ?? found?.dataType;
        setRead({ ref: dataType ? { ...stacked, dataType } : stacked, columns: found?.columns ?? [] });
      });
    return () => {
      current = false;
    };
  }, [stacked]);
  return stacked ? read : null;
}

function Select<T extends string>({
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  label: string;
  value: T | undefined;
  options: { value: T; text: string }[];
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  return (
    <label className={styles.field}>
      {label}
      <select
        className="nodrag nopan"
        aria-label={label}
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function CompareScenariosBody({
  nodeId,
  runError = null,
  savedPath = null,
}: {
  nodeId: string;
  /** Why the node's last run failed, shown where the chart goes. */
  runError?: string | null;
  /** The file the node's last successful run saved its output to. */
  savedPath?: string | null;
}) {
  const flow = useFlowContext() as any;
  const nodes: any[] = flow?.nodes ?? [];
  const edges: any[] = flow?.edges ?? [];
  const scenarios: Scenario[] = flow?.scenarios ?? [];
  const outputs: any[] = flow?.outputs ?? [];
  const dashboardOn = !!flow?.dashboardOn;
  const editable = !dashboardOn && flow?.viewerMode !== "shared";
  const node = nodes.find((n) => n.id === nodeId);
  const settings = normalizeCompareSettings(node?.data?.compareScenarios);
  const [view, setView] = useState<"chart" | "differs">("chart");

  // Code is mirrored into node data without a state change, so What differs
  // is read again on every code edit.
  useSyncExternalStore(subscribeToCodeEdits, codeEditRevision);
  const inputs = compareInputs(nodeId, nodes, edges, scenarios);
  const compared = comparedScenarios(inputs);
  const warnings = [...labelWarnings(inputs), ...contextWarnings(compared, nodes, edges)];
  const differs = whatDiffers(compared, nodes, edges);

  // Chart or Difference: the user's choice, else what the inputs call for
  // (utils/compare/compareMode). The node's behavior writes its code for it.
  const slots: unknown[] = Array.isArray(node?.data?.inputSlots) ? node.data.inputSlots : [];
  const kinds = inputKinds(slots, inputs.map((input) => input.slot));
  const { mode } = resolveMode(settings, kinds, node?.data?.code ?? node?.data?.defaultCode);

  // The node's own output: the file its outcome names, which a load restores
  // with the node (the flow's outputs list starts empty after a load), else,
  // while a run is in flight, the last output the flow holds for it.
  const live = stackedRef(outputs.find((o) => o?.nodeId === nodeId)?.output);
  const rawRef = savedPath ? (live?.path === savedPath ? live : { path: savedPath }) : live;
  const stackedKey = rawRef ? `${rawRef.path}|${rawRef.dataType ?? ""}` : "";
  const stacked = useMemo(() => rawRef, [stackedKey]);
  const read = useStackedRead(mode === "chart" ? stacked : null);
  const columns = read?.columns ?? [];
  const chart = resolveChart(settings?.chart, columns);
  const labels = settings?.inputs ?? inputs.map((input) => input.label);
  const drawn = compareChartSpec(chart, labels, columns);
  const specText = "spec" in drawn ? JSON.stringify(drawn.spec) : "";

  const setChart = (next: ChartSettings) => {
    if (!node || !editable) return;
    flow.updateDataNode?.(nodeId, { ...node.data, compareScenarios: { ...(settings ?? {}), chart: next } });
    flow.markDirty?.();
  };
  // A choice of view, or of the key rows are joined on, rewrites the node's
  // code (its behavior does), which makes a node that has run stale.
  const setMode = (next: CompareMode) => {
    if (!node || !editable || next === mode) return;
    flow.updateDataNode?.(nodeId, { ...node.data, compareScenarios: { ...(settings ?? {}), mode: next } });
    flow.markDirty?.();
  };
  const setDifference = (next: DifferenceSettings) => {
    if (!node || !editable) return;
    const updated = { ...(settings ?? {}) };
    if (Object.keys(next).length > 0) updated.difference = next;
    else delete updated.difference;
    flow.updateDataNode?.(nodeId, { ...node.data, compareScenarios: updated });
    flow.markDirty?.();
  };
  const inputRefs = inputs.map((input) => stackedRef(slots[input.slot]));
  const choose = (patch: Partial<ChartSettings>) =>
    setChart({ preset: chart.preset, ...(chart.x ? { x: chart.x } : {}), ...(chart.y ? { y: chart.y } : {}),
      ...(chart.aggregate ? { aggregate: chart.aggregate } : {}), ...patch });

  const fields = PRESET_FIELDS[chart.preset];
  const named = (roles: string[]) =>
    columns.filter((c) => roles.includes(c.role)).map((c) => ({ value: c.name, text: c.name }));
  const xOptions =
    fields.x === "category" ? named(["nominal"])
      : fields.x === "axis" ? named(["temporal", "quantitative", "nominal"])
        : fields.x === "measure" ? named(["quantitative"])
          : [];

  let stage: React.ReactNode;
  if (mode === "difference") {
    stage = (
      <CompareDifference
        nodeData={node?.data ?? { nodeId }}
        output={stacked}
        inputRefs={inputRefs}
        rastersIn={kinds.length > 0 && kinds.every((kind) => kind === "raster")}
        settings={settings?.difference}
        editable={editable}
        dashboardOn={dashboardOn}
        connected={inputs.length > 0}
        runError={runError}
        onChange={setDifference}
      />
    );
  } else if (runError !== null) {
    stage = (
      <p className={`nodrag nopan ${styles.problem}`} data-compare-run-error="true">
        {runError}
      </p>
    );
  } else if (inputs.length === 0) {
    stage = <NodeEmptyState reason="disconnected" hint="Connect each scenario's outcome to one of its input circles." />;
  } else if (!stacked) {
    stage = <NodeEmptyState reason="not-run" hint="Run this node to stack its inputs and draw them." />;
  } else if (!read) {
    stage = <NodeEmptyState reason="not-run" hint="Reading the stacked table." />;
  } else if (!("spec" in drawn)) {
    stage = <p className={styles.problem} data-compare-chart-problem="true">{drawn.problem}</p>;
  } else {
    stage = <CompareChart nodeData={node?.data ?? { nodeId }} stacked={read.ref} specText={specText} />;
  }

  return (
    <div className={styles.body} data-compare-body={nodeId} data-compare-mode={mode}>
      {warnings.length > 0 ? (
        <ul className={`nodrag nopan nowheel ${styles.warnings}`} data-compare-warnings="true">
          {warnings.map((warning) => (
            <li key={warning} data-compare-warning="true">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
      <div className={styles.bar}>
        <div role="tablist" aria-label="Compare Scenarios views" className={styles.bar}>
          <button
            type="button"
            role="tab"
            className={`nodrag nopan ${styles.tab}`}
            aria-selected={view === "chart"}
            onClick={() => setView("chart")}
          >
            {MODE_LABELS[mode]}
          </button>
          <button
            type="button"
            role="tab"
            className={`nodrag nopan ${styles.tab}`}
            aria-selected={view === "differs"}
            onClick={() => setView("differs")}
          >
            What differs
          </button>
        </div>
        {view === "chart" && !dashboardOn ? (
          <Select<CompareMode>
            label="Compare as"
            value={mode}
            disabled={!editable}
            options={COMPARE_MODES.map((option) => ({ value: option, text: MODE_LABELS[option] }))}
            onChange={setMode}
          />
        ) : null}
        {view === "chart" && mode === "chart" && read && !dashboardOn ? (
          <>
            <Select<ComparePreset>
              label="Chart"
              value={chart.preset}
              disabled={!editable}
              options={COMPARE_PRESETS.map((preset) => ({ value: preset, text: PRESET_LABELS[preset] }))}
              onChange={(preset) => setChart({ preset })}
            />
            {fields.x !== "none" && xOptions.length > 0 ? (
              <Select<string> label="X" value={chart.x} disabled={!editable} options={xOptions} onChange={(x) => choose({ x })} />
            ) : null}
            {fields.y && chart.aggregate !== "count" && named(["quantitative"]).length > 0 ? (
              <Select<string>
                label="Y"
                value={chart.y}
                disabled={!editable}
                options={named(["quantitative"])}
                onChange={(y) => choose({ y })}
              />
            ) : null}
            {fields.aggregate ? (
              <Select<CompareAggregate>
                label="Combine"
                value={chart.aggregate ?? undefined}
                disabled={!editable}
                options={COMPARE_AGGREGATES.map((a) => ({ value: a, text: AGGREGATE_LABELS[a] }))}
                onChange={(aggregate) => choose({ aggregate })}
              />
            ) : null}
          </>
        ) : null}
      </div>
      <div className={styles.stage}>
        <div className={`${styles.pane} ${view === "chart" ? "" : styles.hidden}`} data-compare-preset={chart.preset}>
          {stage}
        </div>
        {view === "differs" ? (
          <div className={`nodrag nopan nowheel ${styles.differs}`}>
            <WhatDiffersList compared={compared} differs={differs} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
