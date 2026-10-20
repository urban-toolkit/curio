
import { useEffect, useRef } from 'react';
import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { useStarterSpec } from '../../hook/useStarterSpec';
import { opensWithPackageStarter } from '../../registry/packageStarter';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { emptyRenderKind, renderOutcome, type RenderCounts } from '../../utils/renderOutcome';
import { defaultSpecText } from '../../utils/vegaDefaultSpec';
import { isEmptySpecBuffer } from '../../utils/starterSpec';
import { toRows } from '../../utils/rowSource';
import { resolveGeometryField } from '../../utils/geometryField';
import { readGrammarInput, type GrammarInput } from '../../utils/grammarInput';
// The chart after a Compare Scenarios node keeps its labels until Compare goes.
import { upstreamCompareLabels } from '../../utils/compare/compareInputs';
import { scenarioScale, type ScenarioLabel } from '../../utils/scenarios/scenarioColors';
import { withScenarioScales } from '../../utils/scenarios/scenarioScales';
import { inputScenarios } from '../../utils/scenarios/inputScenarios';
import type { Scenario } from '../../utils/scenarios/scenarioModel';
import { readsInputs } from '../../utils/vegaDatasets';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { connected, upstreamErrored } = useGrammarInputState(data.nodeId);
  const flow = useFlowContext() as {
    // A failed chart says so to the nodes it feeds, as a failed code node does.
    markNodeErrored?: (nodeId: string) => void;
    nodes?: any[];
    edges?: any[];
    scenarios?: Scenario[];
    isRunActive?: boolean;
    serverRunActive?: boolean;
  };
  const { markNodeErrored } = flow;

  // A chart draws its scenarios in the colors of their boxes and the order of
  // its inputs (utils/scenarios/scenarioScales), whatever the spec writes for
  // them. A spec that reads `inputs` takes them from the boxes its own inputs
  // come from, whose names its rows carry too; any other, from the Compare
  // Scenarios node it reads on its first input, as that node's Chart tab does.
  const nodes = flow.nodes ?? [];
  const edges = flow.edges ?? [];
  const scenarios = flow.scenarios ?? [];
  const inputLabels = inputScenarios(data.nodeId, nodes, edges, scenarios).map((input) => input.label);
  const compareLabels = upstreamCompareLabels(data.nodeId, nodes, edges, scenarios);
  const labelsRef = useRef({ inputs: inputLabels, compare: compareLabels });
  labelsRef.current = { inputs: inputLabels, compare: compareLabels };
  /** What a chart reading `inputs` (*stacked*) or not draws its scenarios with. */
  const labelsOf = (stacked: boolean): readonly ScenarioLabel[] | null =>
    stacked ? labelsRef.current.inputs : labelsRef.current.compare;
  /** What a redraw follows: for a chart reading `inputs`, every label's id,
   * name and color, which its rows carry; else what its scales draw. */
  const keyOf = (stacked: boolean): string =>
    stacked ? stackedKeyOf(labelsRef.current.inputs) : scalesKeyOf(labelsRef.current.compare);

  // A starter spec chosen from the arriving input's column types, the way
  // every grammar node fills an empty editor (hook/useStarterSpec).
  const generatedSpec = useStarterSpec({
    input: data.input,
    buffer: nodeState.code,
    written: data.defaultCode,
    enabled: !opensWithPackageStarter(data.nodeType),
    read: readVegaPreview,
    choose: chooseVegaStarter,
  });

  // dev/136: compiling is not drawing. A schema-valid spec over zero rows
  // renders its axes and nothing else, and a spec whose encoded field is
  // entirely null renders an empty panel — both used to land as `success`, so
  // the node showed a green Done over a blank chart and every agent reading
  // the journal was told the node was fine. The same judgement for a chart's
  // first draw and for every redraw its new rows cause.
  const reportDrawn = (counts: RenderCounts | undefined) => {
    const outcome = renderOutcome(counts ?? {});
    if (outcome.empty) {
      nodeState.setOutput({
        code: 'error', content: outcome.message, outputType: '',
        // dev/136: the harness reads this rather than the prose — the
        // cause rides the kind, because the fix differs per cause.
        kind: emptyRenderKind(outcome.cause),
      } as any);
      showToast(outcome.message, 'error');
      markNodeErrored?.(data.nodeId);
      return;
    }
    nodeState.setOutput({ code: 'success', content: '', outputType: '' });
  };

  const { handleCompileGrammar } = useVega({
    data,
    code: nodeState.code,
    connected,
    upstreamErrored,
    // What the editor holds now, typing included.
    hasSpec: !isEmptySpecBuffer(nodeState.code) || generatedSpec !== undefined,
    // A chart first drawn over zero rows said so; when its rows arrive and it
    // draws them, that has to be said too.
    onRedraw: reportDrawn,
    // The names a spec reading `inputs` gives each input's rows.
    inputLabels,
  });

  // The spec last handed in, whether it reads `inputs`, and the labels it was
  // drawn with.
  const appliedRef = useRef<{ spec: string; stacked: boolean; key: string } | null>(null);
  const draw = async (spec: string, stacked: boolean, how?: typeof AS_THE_CHART_TAB) => {
    try {
      reportDrawn(await handleCompileGrammar(withLabelScales(spec, labelsOf(stacked)), how));
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      showToast(error.message, 'error');
      markNodeErrored?.(data.nodeId);
    }
  };
  const applyGrammar = async (spec: string) => {
    const stacked = specReadsInputs(spec);
    appliedRef.current = { spec, stacked, key: keyOf(stacked) };
    await draw(spec, stacked);
  };
  const labelsKey = appliedRef.current ? keyOf(appliedRef.current.stacked) : '';

  // A scenario renamed or recolored draws the chart again, as it draws the
  // Compare node's Chart tab again, and the same way; a chart that reads
  // `inputs` stacks its rows again under the new names. A run draws it itself,
  // so not during one: once the run ends, the chart is drawn again only if the
  // run did not.
  const runInFlight = !!flow.isRunActive || !!flow.serverRunActive;
  const executing = nodeState.output?.code === 'exec';
  const busyRef = useRef(false);
  busyRef.current = runInFlight || executing;
  // One redraw at a time. A color dragged through the picker is written at
  // each step it passes, and a redraw takes the chart's selection from the
  // view the one before it built, which holds it only once that one is done.
  // Done, it draws again if the labels moved meanwhile.
  const redrawingRef = useRef(false);
  const redraw = async () => {
    redrawingRef.current = true;
    try {
      for (let applied = appliedRef.current; applied && !busyRef.current; applied = appliedRef.current) {
        const drawnKey = keyOf(applied.stacked);
        if (applied.key === drawnKey) break;
        appliedRef.current = { ...applied, key: drawnKey };
        await draw(applied.spec, applied.stacked, AS_THE_CHART_TAB);
      }
    } finally {
      redrawingRef.current = false;
    }
  };
  useEffect(() => {
    const applied = appliedRef.current;
    if (!applied || applied.key === labelsKey || runInFlight || executing || redrawingRef.current) return;
    void redraw();
  }, [labelsKey, runInFlight, executing]);

  // The DOM id useVega renders the compiled view into — pre-Phase-B this was
  // declared in `adapter.editor.outputId`, but the manifest can't carry a
  // function. We own the `"vega" + nodeId` convention here so UniversalNode
  // can mount the matching `<div id={outputIdOverride}>` container.
  return {
    applyGrammar,
    outputIdOverride: 'vega' + data.nodeId,
    // Only ever offered for an empty buffer, so it cannot displace real work.
    defaultValueOverride: generatedSpec,
  };
};

/**
 * How a chart is drawn again when a scenario is recolored or renamed: as the
 * Compare node's Chart tab draws its own (components/compare/CompareChart),
 * with no version recorded in its provenance and nothing handed downstream. A
 * selection made in the chart is kept, which the Chart tab's presets never
 * make.
 */
const AS_THE_CHART_TAB = { recordsProvenance: false, forwardsInput: false, keepsSelection: true };

/**
 * What a chart after a Compare node draws of *labels*: the scenarios' names
 * and colors in the order of its inputs (`scenarioScale`). A scenario id
 * alone, or the order a label's keys are written in, draws nothing different.
 */
function scalesKeyOf(labels: readonly ScenarioLabel[] | null): string {
  return labels ? JSON.stringify(scenarioScale(labels)) : '';
}

/**
 * What a chart reading `inputs` draws of *labels*: each input's scenario id,
 * name and color, in circle order. Its rows carry the id and the name, so a
 * change to any of them draws it again; the order a label's keys are written
 * in draws nothing different.
 */
function stackedKeyOf(labels: readonly ScenarioLabel[]): string {
  return JSON.stringify(labels.map((label) => [label.scenario ?? null, label.name, label.color]));
}

/** Whether the spec *text* reads the stacked dataset `inputs`; not when it is not JSON. */
function specReadsInputs(text: string): boolean {
  try {
    return readsInputs(JSON.parse(text));
  } catch {
    return false;
  }
}

/**
 * *spec* with its channels on `scenario_name` drawn as *labels* say
 * (utils/scenarios/scenarioScales); as written, character for character, with
 * no labels, with nothing to fill, or when it is not JSON, which the compile
 * then reports as it always does.
 */
function withLabelScales(spec: string, labels: readonly ScenarioLabel[] | null): string {
  if (!labels) return spec;
  let parsed: unknown;
  try {
    parsed = JSON.parse(spec);
  } catch {
    return spec;
  }
  const filled = withScenarioScales(parsed, labels);
  return filled === parsed ? spec : JSON.stringify(filled);
}

/** The input's 100-row preview: plenty for classifying columns, and cheaper than /get. */
function readVegaPreview(input: unknown): Promise<GrammarInput> {
  return readGrammarInput(input, { label: 'the 2D Plot (Vega-Lite)', preview: true, circles: true });
}

/** The Vega-Lite ladder over the input's first frame, its first input's (utils/vegaDefaultSpec). */
function chooseVegaStarter(read: GrammarInput): string | null {
  const frame = read.frames[0];
  if (!frame) return null;
  const geo = frame.dataType === 'geodataframe';
  // A FeatureCollection's properties never list its active geometry column,
  // which is why that column is named by the payload rather than found here.
  const rows = geo
    ? (frame.payload?.features ?? []).map((f: any) => f?.properties ?? {})
    : toRows({ data: frame.payload });
  // A DataFrame's geometry column is typed `str` or `object`, so it is found
  // by value, as the Autark node finds it.
  const geometryName = geo ? frame.geometryName : resolveGeometryField(rows, null).field;
  return defaultSpecText(frame.schema, rows, geometryName);
}
